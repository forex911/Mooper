from __future__ import annotations

import errno
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional


class ConversionError(Exception):
    pass


class UnsupportedFormatError(ConversionError):
    pass


# ---------------------------------------------------------------------------
# Format classification
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif",
    ".webp", ".ico", ".ppm", ".pgm", ".pbm", ".pcx", ".tga",
}

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv", ".ts", ".ogv",
}

AUDIO_EXTENSIONS = {
    ".mp3", ".aac", ".wav", ".flac", ".ogg", ".m4a",
}

# Media-kind pairs that convert() knows how to handle.
SUPPORTED_PAIRS = {
    ("image", "image"),
    ("video", "video"),
    ("video", "image"),
    ("video", "audio"),
    ("audio", "audio"),
    ("directory", "video"),
}

# Extensions that mean the same format (used to skip pointless "jpg -> jpeg").
_CANONICAL_EXT = {".jpeg": ".jpg", ".tif": ".tiff"}

_CRF = {"high": 10, "mid": 23, "low": 32}


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def _looks_like_mpegts(path: str) -> bool:
    """'.ts' is also TypeScript. MPEG-TS packets start with 0x47 every 188 bytes."""
    try:
        with open(path, "rb") as f:
            head = f.read(189)
        return len(head) >= 189 and head[0] == 0x47 and head[188] == 0x47
    except OSError:
        return False


def _kind(path: str, sniff: bool = True) -> str:
    """Classify a path as directory, image, video, or audio.

    * Existing directories -> "directory".
    * Known extensions     -> by extension (".ts" files are sniffed so that
                              TypeScript sources are not mistaken for video).
    * No extension         -> "directory" only if the path is NOT an existing
                              file (i.e. a folder or a not-yet-created output
                              folder). An existing extensionless file such as
                              README or .DS_Store is unsupported.
    Pass sniff=False for output paths that are only *going* to be written.
    """
    if os.path.isdir(path):
        return "directory"

    ext = _ext(path)
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        if sniff and ext == ".ts" and os.path.isfile(path) and not _looks_like_mpegts(path):
            raise UnsupportedFormatError(f"{path!r} is not an MPEG transport stream")
        return "video"
    if ext in AUDIO_EXTENSIONS:
        return "audio"

    if not ext:
        if os.path.isfile(path):
            raise UnsupportedFormatError(f"File has no extension: {path!r}")
        return "directory"

    raise UnsupportedFormatError(f"Unsupported file extension: {ext!r}")


# ---------------------------------------------------------------------------
# Encoder selection helpers
# ---------------------------------------------------------------------------

# container -> (video encoder candidates, audio encoder candidates)
_H264_SET = (["libx264", "mpeg4"], ["aac"])
_VIDEO_ENCODERS = {
    ".mp4": _H264_SET,
    ".mov": _H264_SET,
    ".mkv": _H264_SET,
    ".flv": _H264_SET,
    ".ts": _H264_SET,
    ".avi": (["libx264", "mpeg4"], ["libmp3lame", "aac"]),
    ".webm": (["libvpx-vp9", "libvpx"], ["libopus", "libvorbis"]),
    ".ogv": (["libtheora"], ["libvorbis", "libopus", "vorbis"]),
    ".wmv": (["wmv2", "msmpeg4v3"], ["wmav2"]),
}

_AUDIO_ENCODERS = {
    ".mp3": ["libmp3lame", "mp3"],
    ".aac": ["aac"],
    ".m4a": ["aac"],
    ".wav": ["pcm_s16le"],
    ".flac": ["flac"],
    ".ogg": ["libvorbis", "libopus", "vorbis"],
}

_EXPERIMENTAL_ENCODERS = {"vorbis", "opus"}

# Codecs each container can hold when *copying* streams (remux). None = anything.
_REMUX_VIDEO = {
    ".mp4": {"h264", "hevc", "mpeg4", "av1", "vp9"},
    ".mov": {"h264", "hevc", "mpeg4", "prores", "mjpeg"},
    ".mkv": None,
    ".avi": {"h264", "mpeg4", "msmpeg4v3", "mjpeg"},
    ".webm": {"vp8", "vp9", "av1"},
    ".flv": {"h264", "flv1"},
    ".ts": {"h264", "hevc", "mpeg2video"},
    ".wmv": {"wmv1", "wmv2", "wmv3"},
    ".ogv": {"theora"},
}
_PCM = {"pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_u8", "pcm_f32le"}
_REMUX_AUDIO = {
    ".mp4": {"aac", "mp3", "alac", "ac3"},
    ".mov": {"aac", "mp3", "alac", "ac3"} | _PCM,
    ".mkv": None,
    ".avi": {"mp3", "ac3"} | _PCM,
    ".webm": {"opus", "vorbis"},
    ".flv": {"aac", "mp3"},
    ".ts": {"aac", "mp3", "ac3"},
    ".wmv": {"wmav1", "wmav2"},
    ".ogv": {"vorbis", "opus", "flac"},
    ".mp3": {"mp3"},
    ".aac": {"aac"},
    ".m4a": {"aac", "alac"},
    ".wav": _PCM,
    ".flac": {"flac"},
    ".ogg": {"vorbis", "opus", "flac"},
}


def _pick_encoder(candidates: list[str], ext: str, what: str) -> str:
    """Return the first encoder that this PyAV/FFmpeg build actually provides."""
    from av.codec import Codec

    for name in candidates:
        try:
            Codec(name, "w")
            return name
        except Exception:
            continue
    raise ConversionError(
        f"No {what} encoder available for '{ext}' in this FFmpeg build "
        f"(tried: {', '.join(candidates)})."
    )


def _ffmpeg_error():
    import av
    return getattr(av.error, "FFmpegError", OSError)


def _encoder_rate(codec: str, rate: int) -> int:
    """Clamp the sample rate to what the encoder accepts."""
    rate = int(rate or 44100)
    if codec in ("libmp3lame", "mp3"):
        ok = {8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000}
        return rate if rate in ok else 44100
    if codec in ("libopus", "opus"):
        ok = {8000, 12000, 16000, 24000, 48000}
        return rate if rate in ok else 48000
    return rate


def _video_options(codec: str, low_resource: bool, quality: Optional[str]) -> dict:
    """Encoder options.

    Precedence: `quality` decides the CRF, `low_resource` decides the speed
    preset/threads. If the user asked for low-resource mode without an explicit
    non-default quality, the cheaper CRF 28 is used (original intent).
    """
    q = quality if quality in _CRF else None

    if codec == "libx264":
        crf = _CRF[q] if q else 23
        preset = "medium"
        if low_resource:
            preset = "ultrafast"
            if q in (None, "mid"):
                crf = 28
        elif q == "high":
            preset = "slow"
        return {"preset": preset, "crf": str(crf)}

    if codec == "libvpx-vp9":
        crf = {"high": 20, "mid": 31, "low": 40}[q or "mid"]
        if low_resource and q in (None, "mid"):
            crf = 40
        return {"crf": str(crf), "b:v": "0", "cpu-used": "8" if low_resource else "4"}

    if codec == "libvpx":
        crf = {"high": 10, "mid": 20, "low": 35}[q or "mid"]
        return {"crf": str(crf), "b:v": "2M"}

    return {}


class _Muxer:
    """Mux packets; surface real errors instead of swallowing them.

    Some containers reject an occasional non-monotonic packet with EINVAL on
    variable-frame-rate input. That is tolerated *only after* at least one
    packet was written successfully (a header/codec problem fails on the very
    first packet and must be reported).
    """

    def __init__(self, container):
        self.container = container
        self.written = 0
        self.dropped = 0
        self._err = _ffmpeg_error()

    def __call__(self, packet) -> None:
        try:
            self.container.mux(packet)
        except self._err as e:
            if self.written and getattr(e, "errno", None) == errno.EINVAL:
                self.dropped += 1
                return
            raise
        self.written += 1


def _as_list(x) -> list:
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


class _AudioPipe:
    """decode -> resample -> encode -> mux, including proper flushing."""

    def __init__(self, mux: _Muxer, out_stream, fmt: str, layout: str, rate: int):
        import av
        self._mux = mux
        self._out = out_stream
        self._resampler = av.AudioResampler(format=fmt, layout=layout, rate=rate)

    def _encode(self, frame) -> None:
        for packet in self._out.encode(frame):
            self._mux(packet)

    def feed(self, frame) -> None:
        frame.pts = None
        for rf in _as_list(self._resampler.resample(frame)):
            self._encode(rf)

    def flush(self) -> None:
        try:
            tail = _as_list(self._resampler.resample(None))
        except Exception:
            tail = []
        for rf in tail:
            self._encode(rf)
        self._encode(None)


def _setup_audio_stream(out_container, codec: str, ext: str, in_audio):
    """Create the output audio stream; returns (stream, fmt, layout, rate)."""
    rate = _encoder_rate(codec, in_audio.rate)
    stream = out_container.add_stream(codec, rate=rate)
    layout = "mono" if in_audio.channels == 1 else "stereo"
    try:
        stream.layout = layout
    except Exception:
        pass
    if codec in _EXPERIMENTAL_ENCODERS:
        stream.options = {"strict": "experimental"}
    if codec.startswith("wma"):
        stream.bit_rate = 128_000  # WMA encoders refuse to open without a bitrate
    fmt = "s16" if codec in ("pcm_s16le", "flac") else "fltp"
    return stream, fmt, layout, rate


def _safe_close(container) -> None:
    if container is not None:
        try:
            container.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Image <-> Image (Pillow)
# ---------------------------------------------------------------------------

def _has_alpha(img) -> bool:
    return (
        img.mode in ("RGBA", "LA", "PA", "RGBa", "La")
        or "transparency" in img.info
    )


def _flatten_to_rgb(img):
    """Composite transparency onto white instead of letting it turn black."""
    from PIL import Image

    if _has_alpha(img):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return img.convert("RGB")


def _prepare_for_target(img, target_ext: str):
    """Convert the image to a mode the target format can store."""
    if target_ext in {".jpg", ".jpeg", ".bmp", ".pcx", ".ppm", ".pgm", ".pbm"}:
        if img.mode in ("I;16", "I;16L", "I;16B", "I"):
            try:
                img = img.point(lambda i: i * (1 / 256)).convert("L")
            except Exception:
                img = img.convert("L")
        if target_ext == ".pgm":
            img = _flatten_to_rgb(img).convert("L") if _has_alpha(img) else img.convert("L")
        elif target_ext == ".pbm":
            img = (_flatten_to_rgb(img) if _has_alpha(img) else img).convert("1")
        elif img.mode not in ("RGB", "L") or _has_alpha(img):
            img = _flatten_to_rgb(img)
    if target_ext == ".ico" and max(img.size) > 256:
        img = img.copy()
        img.thumbnail((256, 256))
    return img


def _quality_kwargs(target_ext: str, quality: Optional[str]) -> dict:
    if quality is not None and target_ext in {".jpg", ".jpeg", ".webp"}:
        return {"quality": {"high": 100, "mid": 80, "low": 60}.get(quality, 80)}
    return {}


def _save_image(img, output_path: str, quality: Optional[str]) -> None:
    target_ext = _ext(output_path)
    if not target_ext:
        raise ConversionError(f"Cannot determine target format from output path: {output_path}")
    img = _prepare_for_target(img, target_ext)
    img.save(output_path, **_quality_kwargs(target_ext, quality))


def _convert_image(input_path: str, output_path: str, quality: Optional[str] = None) -> None:
    from PIL import Image, ImageOps, ImageSequence

    target_ext = _ext(output_path)
    if not target_ext:
        raise ConversionError(f"Cannot determine target format from output path: {output_path}")

    try:
        with Image.open(input_path) as src:
            # Animated GIF/WebP/APNG -> animated GIF/WebP keeps every frame.
            if getattr(src, "n_frames", 1) > 1 and target_ext in {".gif", ".webp"}:
                frames, durations = [], []
                for frame in ImageSequence.Iterator(src):
                    durations.append(frame.info.get("duration", 100))
                    frames.append(frame.convert("RGBA"))
                frames[0].save(
                    output_path,
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations,
                    loop=src.info.get("loop", 0),
                    **_quality_kwargs(target_ext, quality),
                )
                return

            # Bake the EXIF orientation into the pixels (metadata is not copied).
            img = ImageOps.exif_transpose(src) or src
            _save_image(img, output_path, quality)
    except ConversionError:
        raise
    except Exception as e:
        raise ConversionError(f"Image conversion failed: {e}") from e


# ---------------------------------------------------------------------------
# Remux (stream copy) - only when the target container can hold the codecs
# ---------------------------------------------------------------------------

def _codec_name(stream) -> str:
    codec = stream.codec_context.codec
    return getattr(codec, "canonical_name", None) or stream.codec_context.name


def _codec_fits(table: dict, ext: str, name: str) -> bool:
    if ext not in table:
        return False
    allowed = table[ext]
    return allowed is None or name in allowed


def _add_template_stream(out_container, stream):
    """PyAV >= 14 renamed add_stream(template=...) to add_stream_from_template()."""
    if hasattr(out_container, "add_stream_from_template"):
        return out_container.add_stream_from_template(stream)
    return out_container.add_stream(template=stream)


def _try_remux(input_path: str, output_path: str, media: str = "video") -> bool:
    """Copy streams without re-encoding when the codecs fit the target container.

    media="video": first video + first audio stream.
    media="audio": first audio stream only (never drags a video track along).
    Returns False (and leaves no output behind) if remuxing isn't possible.
    """
    import av

    ext = _ext(output_path)
    try:
        in_container = av.open(input_path)
    except Exception:
        return False

    out_container = None
    success = False
    try:
        chosen = []
        if media == "video":
            if in_container.streams.video:
                chosen.append(in_container.streams.video[0])
            if in_container.streams.audio:
                chosen.append(in_container.streams.audio[0])
        elif in_container.streams.audio:
            chosen.append(in_container.streams.audio[0])
        if not chosen:
            return False

        for s in chosen:
            table = _REMUX_VIDEO if s.type == "video" else _REMUX_AUDIO
            if not _codec_fits(table, ext, _codec_name(s)):
                return False

        out_container = av.open(output_path, mode="w")
        stream_map = {s: _add_template_stream(out_container, s) for s in chosen}

        from tqdm import tqdm
        written = 0
        with tqdm(desc="Remuxing", unit="pkt", leave=False) as pbar:
            for packet in in_container.demux(list(stream_map.keys())):
                if packet.dts is None:  # demuxer flush packet: nothing to copy
                    continue
                packet.stream = stream_map[packet.stream]
                out_container.mux(packet)
                written += 1
                pbar.update(1)

        if written == 0:
            return False
        out_container.close()
        out_container = None
        success = True
        return True
    except Exception:
        return False
    finally:
        _safe_close(in_container)
        _safe_close(out_container)
        if not success and os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Audio <-> Audio
# ---------------------------------------------------------------------------

def _convert_audio(input_path: str, output_path: str) -> None:
    if _try_remux(input_path, output_path, media="audio"):
        return

    import av

    ext = _ext(output_path)
    codec = _pick_encoder(_AUDIO_ENCODERS.get(ext, ["aac"]), ext, "audio")

    in_container = out_container = None
    try:
        in_container = av.open(input_path)
        if not in_container.streams.audio:
            raise ConversionError("No audio stream found in input.")
        in_audio = in_container.streams.audio[0]

        out_container = av.open(output_path, mode="w")
        mux = _Muxer(out_container)
        out_audio, fmt, layout, rate = _setup_audio_stream(out_container, codec, ext, in_audio)
        pipe = _AudioPipe(mux, out_audio, fmt, layout, rate)

        from tqdm import tqdm
        total = in_audio.frames if in_audio.frames > 0 else None
        with tqdm(total=total, desc="Converting Audio", unit="frame", leave=False) as pbar:
            for frame in in_container.decode(in_audio):
                pipe.feed(frame)
                pbar.update(1)
        pipe.flush()

        out_container.close()
        out_container = None
    except ConversionError:
        raise
    except Exception as e:
        raise ConversionError(f"Audio conversion failed: {e}") from e
    finally:
        _safe_close(in_container)
        _safe_close(out_container)


# ---------------------------------------------------------------------------
# Video <-> Video (PyAV) - remux-first, encode fallback
# ---------------------------------------------------------------------------

def _transcode_video(
    input_path: str,
    output_path: str,
    low_resource: bool = False,
    quality: Optional[str] = None,
) -> None:
    import av
    from fractions import Fraction

    ext = _ext(output_path)
    v_cands, a_cands = _VIDEO_ENCODERS.get(ext, _H264_SET)

    in_container = out_container = None
    try:
        in_container = av.open(input_path)
        in_video = in_container.streams.video[0] if in_container.streams.video else None
        in_audio = in_container.streams.audio[0] if in_container.streams.audio else None
        if in_video is None and in_audio is None:
            raise ConversionError("Input has no audio or video stream.")

        vcodec = _pick_encoder(v_cands, ext, "video") if in_video is not None else None
        acodec = _pick_encoder(a_cands, ext, "audio") if in_audio is not None else None

        out_container = av.open(output_path, mode="w")
        mux = _Muxer(out_container)

        out_video = None
        w = h = 0
        if in_video is not None:
            fps = in_video.average_rate
            if not fps:
                fps = in_video.guessed_rate
            if not fps:
                fps = Fraction(24, 1)

            # yuv420p needs even dimensions
            w = max(2, in_video.codec_context.width - in_video.codec_context.width % 2)
            h = max(2, in_video.codec_context.height - in_video.codec_context.height % 2)

            out_video = out_container.add_stream(vcodec, rate=fps)
            out_video.width = w
            out_video.height = h
            out_video.pix_fmt = "yuv420p"
            out_video.thread_count = 1 if low_resource else 0
            out_video.options = _video_options(vcodec, low_resource, quality)

        pipe = None
        if in_audio is not None:
            out_audio, fmt, layout, rate = _setup_audio_stream(out_container, acodec, ext, in_audio)
            pipe = _AudioPipe(mux, out_audio, fmt, layout, rate)

        from tqdm import tqdm
        streams = [s for s in (in_video, in_audio) if s is not None]
        with tqdm(desc="Transcoding", unit="pkt", leave=False) as pbar:
            for packet in in_container.demux(streams):
                # NOTE: empty flush packets (dts None) are deliberately NOT skipped:
                # decoding them drains the decoder so the last frames aren't lost.
                if packet.stream.type == "video" and out_video is not None:
                    for frame in packet.decode():
                        pts, time_base = frame.pts, frame.time_base
                        frame = frame.reformat(width=w, height=h, format="yuv420p")
                        frame.pts = pts
                        if time_base is not None:
                            frame.time_base = time_base
                        for out_packet in out_video.encode(frame):
                            mux(out_packet)
                elif packet.stream.type == "audio" and pipe is not None:
                    for frame in packet.decode():
                        pipe.feed(frame)
                pbar.update(1)

        if out_video is not None:
            for out_packet in out_video.encode(None):
                mux(out_packet)
        if pipe is not None:
            pipe.flush()

        if mux.written == 0:
            raise ConversionError("Encoder produced no data.")

        out_container.close()
        out_container = None
    except ConversionError:
        raise
    except Exception as e:
        raise ConversionError(f"Video transcode failed: {e}") from e
    finally:
        _safe_close(in_container)
        _safe_close(out_container)


def _convert_video(
    input_path: str,
    output_path: str,
    low_resource: bool = False,
    quality: Optional[str] = None,
) -> None:
    # Stream-copy is only appropriate when the user hasn't asked for a specific
    # quality level; an explicit low/high request must re-encode.
    if quality in (None, "mid") and _try_remux(input_path, output_path, media="video"):
        return
    _transcode_video(input_path, output_path, low_resource=low_resource, quality=quality)


# ---------------------------------------------------------------------------
# Video -> Image (single frame extraction)
# ---------------------------------------------------------------------------

def _extract_frame(
    input_path: str,
    output_path: str,
    frame_number: int = 0,
    quality: Optional[str] = None,
) -> None:
    import av

    if frame_number < 0:
        raise ConversionError("Frame number must be 0 or greater.")

    container = None
    try:
        container = av.open(input_path)
        if not container.streams.video:
            raise ConversionError("No video stream found.")
        stream = container.streams.video[0]

        image = None
        seen = 0
        for i, frame in enumerate(container.decode(stream)):
            seen = i + 1
            if i == frame_number:
                image = frame.to_image()
                break
        if image is None:
            raise ConversionError(
                f"Video has only {seen} frame(s); frame {frame_number} does not exist."
            )
        _save_image(image, output_path, quality)
    except ConversionError:
        raise
    except Exception as e:
        raise ConversionError(f"Frame extraction failed: {e}") from e
    finally:
        _safe_close(container)


# ---------------------------------------------------------------------------
# Image Sequence -> Video
# ---------------------------------------------------------------------------

def _natural_sort_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _images_to_video(
    input_dir: str,
    output_path: str,
    fps: int = 24,
    low_resource: bool = False,
    quality: Optional[str] = None,
) -> None:
    import av
    from PIL import Image, ImageOps

    if fps <= 0:
        raise ConversionError("FPS must be greater than 0.")

    ext = _ext(output_path)
    v_cands, _ = _VIDEO_ENCODERS.get(ext, _H264_SET)
    vcodec = _pick_encoder(v_cands, ext, "video")

    images = []
    for f in sorted(os.listdir(input_dir), key=_natural_sort_key):
        p = os.path.join(input_dir, f)
        if os.path.isfile(p) and _ext(p) in IMAGE_EXTENSIONS:
            images.append(p)
    if not images:
        raise ConversionError(f"No images found in {input_dir}")

    def _load(path: str):
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im) or im
            return _flatten_to_rgb(im)

    out_container = None
    try:
        first = _load(images[0])
        w = max(2, first.width - first.width % 2)   # yuv420p needs even sizes
        h = max(2, first.height - first.height % 2)

        out_container = av.open(output_path, mode="w")
        mux = _Muxer(out_container)
        out_video = out_container.add_stream(vcodec, rate=fps)
        out_video.width = w
        out_video.height = h
        out_video.pix_fmt = "yuv420p"
        out_video.thread_count = 1 if low_resource else 0
        out_video.options = _video_options(vcodec, low_resource, quality)

        from tqdm import tqdm
        with tqdm(total=len(images), desc="Encoding sequence", unit="img", leave=False) as pbar:
            for idx, img_path in enumerate(images):
                rgb = first if idx == 0 else _load(img_path)
                # Letterbox instead of stretching images of a different size.
                if rgb.size != (w, h):
                    scale = min(w / rgb.width, h / rgb.height)
                    nw, nh = max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale))
                    canvas = Image.new("RGB", (w, h), (0, 0, 0))
                    canvas.paste(rgb.resize((nw, nh), Image.LANCZOS), ((w - nw) // 2, (h - nh) // 2))
                    rgb = canvas
                frame = av.VideoFrame.from_image(rgb)
                for packet in out_video.encode(frame):
                    mux(packet)
                pbar.update(1)

        for packet in out_video.encode(None):
            mux(packet)
        if mux.written == 0:
            raise ConversionError("Encoder produced no data.")
        out_container.close()
        out_container = None
    except ConversionError:
        raise
    except Exception as e:
        raise ConversionError(f"Image sequence encoding failed: {e}") from e
    finally:
        _safe_close(out_container)


# ---------------------------------------------------------------------------
# Video -> Audio (Extraction)
# ---------------------------------------------------------------------------

def _extract_audio(input_path: str, output_path: str) -> None:
    # Audio-only remux (or decode + encode); never copies the video track.
    _convert_audio(input_path, output_path)


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------

def _tmp_output_path(output_path: str) -> str:
    """Hidden sibling temp file that keeps the real extension (format detection)."""
    directory, name = os.path.split(os.path.abspath(output_path))
    stem, ext = os.path.splitext(name)
    return os.path.join(directory, f".{stem}.{uuid.uuid4().hex[:8]}.mooper-part{ext}")


def convert(
    input_path: str,
    output_path: str,
    low_resource: bool = False,
    frame_number: Optional[int] = None,
    fps: int = 24,
    quality: Optional[str] = None,
    overwrite: str = "overwrite",
) -> bool:
    """Convert one file (or an image-sequence folder).

    overwrite: "overwrite" (default) | "skip" | "error" - what to do when
    `output_path` already exists. Output is written to a temp file and moved into
    place only on success, so a failed conversion never leaves a broken file and
    never destroys an existing one.

    Returns True if a conversion happened, False if it was skipped.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(input_path)

    if os.path.realpath(input_path) == os.path.realpath(output_path):
        raise ConversionError(
            "Input and output paths cannot be identical. "
            "This would overwrite and destroy the original file."
        )

    in_kind = _kind(input_path)
    out_kind = _kind(output_path, sniff=False)

    if (in_kind, out_kind) not in SUPPORTED_PAIRS:
        raise UnsupportedFormatError(
            f"Conversion from {in_kind} to {out_kind} is not supported."
        )

    if os.path.isdir(output_path):
        raise ConversionError(
            f"Output '{output_path}' is a directory; give a file name with an extension."
        )

    if os.path.exists(output_path):
        if overwrite == "skip":
            return False
        if overwrite == "error":
            raise FileExistsError(output_path)

    parent = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(parent, exist_ok=True)

    tmp = _tmp_output_path(output_path)
    try:
        if in_kind == "image" and out_kind == "image":
            _convert_image(input_path, tmp, quality=quality)
        elif in_kind == "video" and out_kind == "video":
            _convert_video(input_path, tmp, low_resource=low_resource, quality=quality)
        elif in_kind == "video" and out_kind == "image":
            _extract_frame(input_path, tmp, frame_number=frame_number or 0, quality=quality)
        elif in_kind == "audio" and out_kind == "audio":
            _convert_audio(input_path, tmp)
        elif in_kind == "video" and out_kind == "audio":
            _extract_audio(input_path, tmp)
        elif in_kind == "directory" and out_kind == "video":
            _images_to_video(input_path, tmp, fps=fps, low_resource=low_resource, quality=quality)

        if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            raise ConversionError("Conversion produced an empty file.")
        os.replace(tmp, output_path)
        return True
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Batch conversion
# ---------------------------------------------------------------------------

@dataclass
class BatchResult:
    converted: int = 0
    skipped: list = field(default_factory=list)   # [(path, reason)]
    failed: list = field(default_factory=list)    # [(path, error message)]

    @property
    def ok(self) -> bool:
        return not self.failed


def _normalize_target(ext: str) -> str:
    ext = ext.strip().lower()
    if not ext.startswith("."):
        ext = "." + ext
    if ext not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS:
        raise UnsupportedFormatError(f"Unsupported target format: {ext!r}")
    return ext


def convert_batch(
    input_dir: str,
    output_dir: str,
    target_ext: "str | dict",
    low_resource: bool = False,
    quality: Optional[str] = None,
    recursive: bool = False,
    fps: int = 24,
    frame_number: Optional[int] = None,
    overwrite: str = "overwrite",
    on_conflict: Optional[Callable[[str], str]] = None,
) -> BatchResult:
    """Convert every compatible file in `input_dir`.

    target_ext: one extension for everything, or {source_ext: target_ext}.
    overwrite:  "overwrite" | "skip" | "ask" (ask uses `on_conflict(path)` which
                must return "overwrite" or "skip"; without a callback -> skip).
    Files that cannot be converted to the target kind (e.g. mp3 -> jpg), files
    already in the target format and non-media files are skipped, not failed.
    """
    is_mapping = isinstance(target_ext, dict)
    if is_mapping:
        mapping = {k.lower() if k.startswith(".") else "." + k.lower(): _normalize_target(v)
                   for k, v in target_ext.items()}
    else:
        single = _normalize_target(target_ext)

    result = BatchResult()
    out_abs = os.path.abspath(output_dir)
    files_to_process = []

    for root, dirs, files in os.walk(input_dir):
        # Never descend into our own output folder (re-runs would re-convert it).
        dirs[:] = sorted(d for d in dirs if os.path.abspath(os.path.join(root, d)) != out_abs)
        if not recursive:
            dirs.clear()

        for f in sorted(files):
            in_path = os.path.join(root, f)
            try:
                in_kind = _kind(in_path)
            except UnsupportedFormatError:
                continue  # not a media file: ignore silently
            if in_kind == "directory":
                continue
            in_ext = _ext(in_path)

            if is_mapping:
                if in_ext not in mapping:
                    continue
                tgt = mapping[in_ext]
            else:
                tgt = single

            out_kind = _kind("x" + tgt, sniff=False)
            if (in_kind, out_kind) not in SUPPORTED_PAIRS:
                result.skipped.append((in_path, f"{in_kind} -> {out_kind} is not supported"))
                continue
            if _CANONICAL_EXT.get(in_ext, in_ext) == _CANONICAL_EXT.get(tgt, tgt):
                result.skipped.append((in_path, f"already {tgt}"))
                continue
            files_to_process.append((root, f, in_path, in_ext, tgt))

    total = len(files_to_process)
    if total == 0:
        print("No files to convert.")
        return result

    os.makedirs(output_dir, exist_ok=True)
    print(f"Found {total} files to convert.")

    for i, (root, f, in_path, in_ext, tgt) in enumerate(files_to_process, 1):
        rel_path = os.path.relpath(root, input_dir)
        cat_folder = f"{in_ext.strip('.')}_to_{tgt.strip('.')}"
        target_out_dir = (
            os.path.join(output_dir, cat_folder)
            if rel_path == "."
            else os.path.join(output_dir, rel_path, cat_folder)
        )
        out_path = os.path.join(target_out_dir, os.path.splitext(f)[0] + tgt)

        print(f"\n[{i}/{total}] Processing {f}...")

        policy = overwrite
        if os.path.exists(out_path) and policy == "ask":
            policy = on_conflict(out_path) if on_conflict else "skip"
        if os.path.exists(out_path) and policy == "skip":
            result.skipped.append((in_path, "output already exists"))
            print(f"Skipped (exists): {out_path}")
            continue

        try:
            convert(in_path, out_path, low_resource=low_resource, quality=quality,
                    fps=fps, frame_number=frame_number, overwrite="overwrite")
            result.converted += 1
            print(f"Successfully converted -> {out_path}")
        except Exception as e:
            result.failed.append((in_path, str(e)))
            print(f"Failed to convert {in_path}: {e}")

    return result
