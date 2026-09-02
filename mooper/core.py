from __future__ import annotations

import os
from typing import Optional


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


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def _kind(path: str) -> str:
    """Classify a path as directory, image, video, or audio.
    
    Works for both existing files (checks isdir first) and
    non-existent output paths (classifies purely by extension).
    """
    if os.path.isdir(path):
        return "directory"
    
    ext = _ext(path)
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    
    # If path has no extension and doesn't exist yet, treat as directory
    # (e.g. output folder for batch conversion)
    if not ext:
        return "directory"
    
    raise UnsupportedFormatError(f"Unsupported file extension: {ext!r}")


# ---------------------------------------------------------------------------
# Image <-> Image (Pillow)
# ---------------------------------------------------------------------------

def _convert_image(input_path: str, output_path: str, quality: Optional[str] = None) -> None:
    from PIL import Image

    try:
        with Image.open(input_path) as img:
            target_ext = _ext(output_path)

            needs_rgb = target_ext in {".jpg", ".jpeg", ".bmp", ".pcx"}
            if needs_rgb and img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")

            save_kwargs = {}
            if quality is not None and target_ext in {".jpg", ".jpeg", ".webp"}:
                q_map = {"high": 100, "mid": 80, "low": 60}
                save_kwargs["quality"] = q_map.get(quality, 80)

            img.save(output_path, **save_kwargs)
    except Exception as e:
        raise ConversionError(f"Image conversion failed: {e}")


# ---------------------------------------------------------------------------
# Audio <-> Audio
# ---------------------------------------------------------------------------

def _convert_audio(input_path: str, output_path: str) -> None:
    if _try_remux(input_path, output_path):
        return

    import av

    try:
        in_container = av.open(input_path)
        out_container = av.open(output_path, mode="w")

        in_audio = in_container.streams.audio[0] if in_container.streams.audio else None
        if not in_audio:
            raise ConversionError("No audio stream found in input.")

        codec_map = {
            ".mp3": "mp3",
            ".aac": "aac",
            ".wav": "pcm_s16le",
            ".flac": "flac",
            ".ogg": "libvorbis",
            ".m4a": "aac"
        }
        target_ext = _ext(output_path)
        codec = codec_map.get(target_ext, "aac")

        out_audio = out_container.add_stream(codec, rate=in_audio.rate)
        
        audio_resampler = av.AudioResampler(
            format="s16" if target_ext == ".wav" else "fltp",
            layout='stereo',
            rate=in_audio.rate
        )

        from tqdm import tqdm
        total_frames = in_audio.frames if in_audio.frames > 0 else None
        
        with tqdm(total=total_frames, desc="Converting Audio", unit="frame", leave=False) as pbar:
            for frame in in_container.decode(in_audio):
                frame.pts = None # Reset pts to avoid issues
                r_frames = audio_resampler.resample(frame)
                if r_frames is not None:
                    if not isinstance(r_frames, list):
                        r_frames = [r_frames]
                    for rf in r_frames:
                        for packet in out_audio.encode(rf):
                            out_container.mux(packet)
                pbar.update(1)

        for packet in out_audio.encode():
            out_container.mux(packet)

        out_container.close()
        in_container.close()
    except Exception as e:
        raise ConversionError(f"Audio conversion failed: {e}")


# ---------------------------------------------------------------------------
# Video <-> Video (PyAV) - remux-first, encode fallback
# ---------------------------------------------------------------------------

def _try_remux(input_path: str, output_path: str) -> bool:
    import av

    try:
        in_container = av.open(input_path)
    except Exception:
        return False
        
    out_container = None
    success = False
    try:
        out_container = av.open(output_path, mode="w")
        stream_map = {}

        for stream in in_container.streams:
            if stream.type not in ("video", "audio"):
                continue
            out_stream = out_container.add_stream(template=stream)
            stream_map[stream] = out_stream

        if not stream_map:
            return False

        from tqdm import tqdm
        with tqdm(desc="Remuxing", unit="pkt", leave=False) as pbar:
            for packet in in_container.demux(list(stream_map.keys())):
                if packet.dts is None:
                    continue
                packet.stream = stream_map[packet.stream]
                out_container.mux(packet)
                pbar.update(1)

        success = True
        return True

    except Exception:
        return False

    finally:
        in_container.close()
        if out_container is not None:
            out_container.close()
        # Clean up partial/corrupt output if remux failed
        if not success and os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass


def _transcode_video(
    input_path: str,
    output_path: str,
    low_resource: bool = False,
    quality: Optional[str] = None,
) -> None:
    import av
    from fractions import Fraction

    # Remove any leftover file from a failed remux attempt
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass

    try:
        in_container = av.open(input_path)
        out_container = av.open(output_path, mode="w")

        thread_count = 1 if low_resource else 0

        in_video = in_container.streams.video[0] if in_container.streams.video else None
        in_audio = in_container.streams.audio[0] if in_container.streams.audio else None

        out_video = None
        w, h = 0, 0
        fps = Fraction(24, 1)
        if in_video is not None:
            # Determine frame rate safely
            fps = in_video.average_rate
            if fps is None or fps == 0:
                fps = in_video.guessed_rate
            if fps is None or fps == 0:
                fps = Fraction(24, 1)

            # Ensure even dimensions (required by h264)
            w = in_video.codec_context.width
            h = in_video.codec_context.height
            if w % 2 != 0:
                w -= 1
            if h % 2 != 0:
                h -= 1

            out_video = out_container.add_stream("libx264", rate=fps)
            out_video.width = w
            out_video.height = h
            out_video.pix_fmt = "yuv420p"
            out_video.thread_count = thread_count
            out_video.options = {"preset": "medium", "crf": "23"}
            if low_resource:
                out_video.options = {"preset": "ultrafast", "crf": "28"}
            if quality is not None:
                q_map = {"high": 10, "mid": 23, "low": 32}
                crf_val = q_map.get(quality, 23)
                out_video.options["crf"] = str(crf_val)
                if quality == "high":
                    out_video.options["preset"] = "slow"

        out_audio = None
        if in_audio is not None:
            out_audio = out_container.add_stream("aac", rate=in_audio.rate)

        def _safe_mux(container, packet):
            """Mux a packet, ignoring EINVAL from the MP4 muxer on VFR content."""
            try:
                container.mux(packet)
            except Exception:
                pass

        # --- Pass 1: Video ---
        from tqdm import tqdm
        if in_video is not None and out_video is not None:
            total_frames = in_video.frames if in_video.frames > 0 else None
            frame_count = 0

            with tqdm(total=total_frames, desc="Transcoding Video", unit="frame", leave=False) as pbar:
                for frame in in_container.decode(in_video):
                    frame = frame.reformat(width=w, height=h, format="yuv420p")
                    frame.time_base = Fraction(fps.denominator, fps.numerator) if hasattr(fps, 'denominator') else Fraction(1, int(fps))
                    frame.pts = frame_count
                    frame_count += 1
                    for packet in out_video.encode(frame):
                        _safe_mux(out_container, packet)
                    pbar.update(1)

            # Flush video encoder
            try:
                for packet in out_video.encode():
                    _safe_mux(out_container, packet)
            except Exception:
                pass

        in_container.close()

        # --- Pass 2: Audio (re-open input to get a fresh demux position) ---
        if out_audio is not None:
            in_container2 = av.open(input_path)
            in_audio2 = in_container2.streams.audio[0] if in_container2.streams.audio else None

            if in_audio2 is not None:
                audio_resampler = av.AudioResampler(
                    format='fltp',
                    layout='stereo',
                    rate=in_audio2.rate,
                )

                for frame in in_container2.decode(in_audio2):
                    frame.pts = None
                    r_frames = audio_resampler.resample(frame)
                    if r_frames is not None:
                        if not isinstance(r_frames, list):
                            r_frames = [r_frames]
                        for rf in r_frames:
                            for packet in out_audio.encode(rf):
                                _safe_mux(out_container, packet)

                # Flush audio encoder
                try:
                    for packet in out_audio.encode():
                        _safe_mux(out_container, packet)
                except Exception:
                    pass

            in_container2.close()

        out_container.close()
    except Exception as e:
        raise ConversionError(f"Video transcode failed: {e}")


def _convert_video(
    input_path: str,
    output_path: str,
    low_resource: bool = False,
    quality: Optional[str] = None,
) -> None:
    if _try_remux(input_path, output_path):
        return
    _transcode_video(input_path, output_path, low_resource=low_resource, quality=quality)


# ---------------------------------------------------------------------------
# Video -> Image (single frame extraction)
# ---------------------------------------------------------------------------

def _extract_frame(
    input_path: str,
    output_path: str,
    frame_number: int = 0,
) -> None:
    import av

    try:
        container = av.open(input_path)
        if not container.streams.video:
            raise ConversionError("No video stream found.")
        stream = container.streams.video[0]

        for i, frame in enumerate(container.decode(stream)):
            if i == frame_number:
                frame.to_image().save(output_path)
                break
        else:
            raise ConversionError(f"Video has fewer frames than {frame_number}.")

        container.close()
    except Exception as e:
        raise ConversionError(f"Frame extraction failed: {e}")

# ---------------------------------------------------------------------------
# Image Sequence -> Video
# ---------------------------------------------------------------------------

def _images_to_video(
    input_dir: str,
    output_path: str,
    fps: int = 24,
    low_resource: bool = False,
    quality: Optional[str] = None,
) -> None:
    import av
    from PIL import Image

    try:
        images = []
        for f in sorted(os.listdir(input_dir)):
            p = os.path.join(input_dir, f)
            if os.path.isfile(p) and _ext(p) in IMAGE_EXTENSIONS:
                images.append(p)
                
        if not images:
            raise ConversionError(f"No images found in {input_dir}")

        out_container = av.open(output_path, mode="w")
        out_video = out_container.add_stream("libx264", rate=fps)
        if low_resource:
            out_video.options = {"preset": "ultrafast", "crf": "28"}
        if quality is not None:
            q_map = {"high": 10, "mid": 23, "low": 32}
            crf_val = q_map.get(quality, 23)
            if not out_video.options:
                out_video.options = {}
            out_video.options["crf"] = str(crf_val)
            if quality == "high":
                out_video.options["preset"] = "slow"
            
        first_img = Image.open(images[0])
        w, h = first_img.size
        # h264 requires even dimensions
        if w % 2 != 0: w -= 1
        if h % 2 != 0: h -= 1
        out_video.width = w
        out_video.height = h
        out_video.pix_fmt = "yuv420p"

        from tqdm import tqdm
        with tqdm(total=len(images), desc="Encoding sequence", unit="img", leave=False) as pbar:
            for img_path in images:
                with Image.open(img_path) as img:
                    img_rgb = img.convert("RGB").resize((w, h))
                    frame = av.VideoFrame.from_image(img_rgb)
                    for packet in out_video.encode(frame):
                        out_container.mux(packet)
                pbar.update(1)
        for packet in out_video.encode():
            out_container.mux(packet)
            
        out_container.close()
    except Exception as e:
        raise ConversionError(f"Image sequence encoding failed: {e}")

# ---------------------------------------------------------------------------
# Video -> Audio (Extraction)
# ---------------------------------------------------------------------------

def _extract_audio(input_path: str, output_path: str) -> None:
    # Under the hood, this is just audio-to-audio extraction/transcode
    _convert_audio(input_path, output_path)

# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------

def convert(
    input_path: str,
    output_path: str,
    low_resource: bool = False,
    frame_number: Optional[int] = None,
    fps: int = 24,
    quality: Optional[str] = None,
) -> None:
    if not os.path.exists(input_path):
        raise FileNotFoundError(input_path)

    # Protect against identical paths which cause file truncation/deletion
    if os.path.abspath(input_path) == os.path.abspath(output_path):
        raise ConversionError("Input and output paths cannot be identical. This would overwrite and destroy the original file.")

    in_kind = _kind(input_path)
    out_kind = _kind(output_path)

    if in_kind == "image" and out_kind == "image":
        _convert_image(input_path, output_path, quality=quality)

    elif in_kind == "video" and out_kind == "video":
        _convert_video(input_path, output_path, low_resource=low_resource, quality=quality)

    elif in_kind == "video" and out_kind == "image":
        _extract_frame(input_path, output_path, frame_number=frame_number or 0)
        
    elif in_kind == "audio" and out_kind == "audio":
        _convert_audio(input_path, output_path)
        
    elif in_kind == "video" and out_kind == "audio":
        _extract_audio(input_path, output_path)
        
    elif in_kind == "directory" and out_kind == "video":
        _images_to_video(input_path, output_path, fps=fps, low_resource=low_resource, quality=quality)

    else:
        raise UnsupportedFormatError(
            f"Conversion from {in_kind} to {out_kind} is not supported."
        )


def convert_batch(
    input_dir: str,
    output_dir: str,
    target_ext: str | dict,
    low_resource: bool = False,
    quality: Optional[str] = None,
    recursive: bool = False,
) -> None:
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    is_mapping = isinstance(target_ext, dict)
    
    if not is_mapping and not target_ext.startswith("."):
        target_ext = "." + target_ext

    files_to_process = []
    
    for root, dirs, files in os.walk(input_dir):
        if not recursive:
            dirs.clear()  # Prevent os.walk from descending into subdirectories
            
        for f in files:
            in_path = os.path.join(root, f)
            try:
                kind = _kind(in_path)
                in_ext = _ext(in_path)
                
                # If mapping is provided, only process files that the user selected a target for
                if is_mapping and in_ext not in target_ext:
                    continue
                    
                tgt = target_ext[in_ext] if is_mapping else target_ext
                if not tgt.startswith("."): tgt = "." + tgt
                    
                files_to_process.append((root, f, in_path, in_ext, tgt))
            except UnsupportedFormatError:
                continue

    total = len(files_to_process)
    if total == 0:
        print("No supported media files found.")
        return

    print(f"Found {total} files to convert.")

    for i, (root, f, in_path, in_ext, tgt) in enumerate(files_to_process, 1):
        # Mirror the folder structure if recursive
        rel_path = os.path.relpath(root, input_dir)
        
        # Subfolder categorization based on conversion
        cat_folder = f"{in_ext.strip('.')}_to_{tgt.strip('.')}"
        
        if rel_path == ".":
            target_out_dir = os.path.join(output_dir, cat_folder)
        else:
            target_out_dir = os.path.join(output_dir, rel_path, cat_folder)
            
        if not os.path.exists(target_out_dir):
            os.makedirs(target_out_dir)
            
        out_path = os.path.join(target_out_dir, os.path.splitext(f)[0] + tgt)
        
        # Skip if identical path
        if os.path.abspath(in_path) == os.path.abspath(out_path):
            out_path = os.path.join(target_out_dir, os.path.splitext(f)[0] + "_converted" + tgt)
            
        print(f"\n[{i}/{total}] Processing {f}...")
        try:
            convert(in_path, out_path, low_resource=low_resource, quality=quality)
            print(f"Successfully converted -> {out_path}")
        except Exception as e:
            print(f"Failed to convert {in_path}: {e}")
