import os
import wave
import pytest
from PIL import Image
import av

from mooper.core import convert, convert_batch, ConversionError


@pytest.fixture
def tmp_image(tmp_path):
    p = tmp_path / "dummy.png"
    Image.new("RGB", (32, 32), "red").save(str(p))
    return str(p)


@pytest.fixture
def tmp_audio(tmp_path):
    p = tmp_path / "dummy.wav"
    with wave.open(str(p), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(44100)
        f.writeframes(b'\x00\x00' * 44100)  # 1 sec of silence
    return str(p)


@pytest.fixture
def tmp_video(tmp_path):
    """Create a minimal valid MP4 with video stream only."""
    p = tmp_path / "dummy.mp4"
    container = av.open(str(p), mode='w')
    v_stream = container.add_stream('libx264', rate=24)
    v_stream.width = 32
    v_stream.height = 32
    v_stream.pix_fmt = 'yuv420p'

    img = Image.new("RGB", (32, 32), "green")
    for i in range(5):
        v_frame = av.VideoFrame.from_image(img)
        v_frame.pts = i
        for packet in v_stream.encode(v_frame):
            container.mux(packet)

    for packet in v_stream.encode():
        container.mux(packet)

    container.close()
    return str(p)


@pytest.fixture
def tmp_video_with_audio(tmp_path):
    """Create a valid MP4 with both video and audio using a WAV intermediate."""
    import subprocess
    import wave as wave_mod

    # Create a simple WAV file
    wav_path = tmp_path / "audio.wav"
    with wave_mod.open(str(wav_path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(b'\x00\x00' * 44100)

    # Create video-only MP4
    vid_path = tmp_path / "video_only.mp4"
    container = av.open(str(vid_path), mode='w')
    v_stream = container.add_stream('libx264', rate=24)
    v_stream.width = 32
    v_stream.height = 32
    v_stream.pix_fmt = 'yuv420p'

    img = Image.new("RGB", (32, 32), "green")
    for i in range(5):
        v_frame = av.VideoFrame.from_image(img)
        v_frame.pts = i
        for packet in v_stream.encode(v_frame):
            container.mux(packet)
    for packet in v_stream.encode():
        container.mux(packet)
    container.close()

    # Mux video + audio together using PyAV (two-pass like mooper does)
    p = tmp_path / "dummy_av.mp4"
    oc = av.open(str(p), mode='w')

    # Pass 1: video
    ic = av.open(str(vid_path))
    ov = oc.add_stream('libx264', rate=24)
    ov.width = 32
    ov.height = 32
    ov.pix_fmt = 'yuv420p'
    oa = oc.add_stream('aac', rate=44100)

    frame_count = 0
    for frame in ic.decode(ic.streams.video[0]):
        frame.pts = frame_count
        frame_count += 1
        for pkt in ov.encode(frame):
            oc.mux(pkt)
    for pkt in ov.encode():
        try:
            oc.mux(pkt)
        except Exception:
            pass
    ic.close()

    # Pass 2: audio
    ic2 = av.open(str(wav_path))
    resampler = av.AudioResampler(format='fltp', layout='stereo', rate=44100)
    for frame in ic2.decode(ic2.streams.audio[0]):
        frame.pts = None
        r_frames = resampler.resample(frame)
        if r_frames is not None:
            if not isinstance(r_frames, list):
                r_frames = [r_frames]
            for rf in r_frames:
                for pkt in oa.encode(rf):
                    try:
                        oc.mux(pkt)
                    except Exception:
                        pass
    try:
        for pkt in oa.encode():
            oc.mux(pkt)
    except Exception:
        pass
    ic2.close()
    oc.close()

    return str(p)


def test_image_to_image(tmp_image, tmp_path):
    out = tmp_path / "out.jpg"
    convert(tmp_image, str(out))
    assert out.exists()
    with Image.open(str(out)) as img:
        assert img.format == "JPEG"


def test_audio_to_audio(tmp_audio, tmp_path):
    out = tmp_path / "out.mp3"
    convert(tmp_audio, str(out))
    assert out.exists()


def test_video_to_video(tmp_video, tmp_path):
    out = tmp_path / "out.mkv"
    convert(tmp_video, str(out))
    assert out.exists()


def test_video_extract_frame(tmp_video, tmp_path):
    out = tmp_path / "out.jpg"
    convert(tmp_video, str(out), frame_number=0)
    assert out.exists()


def test_video_extract_audio(tmp_video_with_audio, tmp_path):
    out = tmp_path / "out.wav"
    convert(tmp_video_with_audio, str(out))
    assert out.exists()


def test_images_to_video(tmp_image, tmp_path):
    out = tmp_path / "out.mp4"
    # Create another image
    p2 = tmp_path / "dummy2.png"
    Image.new("RGB", (32, 32), "blue").save(str(p2))

    convert(str(tmp_path), str(out), fps=2)
    assert out.exists()


def test_convert_batch(tmp_image, tmp_path):
    out_dir = tmp_path / "batch_out"
    convert_batch(str(tmp_path), str(out_dir), target_ext=".jpg")
    # Files are now placed in a categorized subfolder: png_to_jpg/
    assert (out_dir / "png_to_jpg" / "dummy.jpg").exists()


def test_convert_batch_mapping(tmp_path):
    """Test intelligent batch conversion with an extension mapping dict."""
    # Create mixed media files
    Image.new("RGB", (32, 32), "red").save(str(tmp_path / "photo.png"))
    Image.new("RGB", (32, 32), "blue").save(str(tmp_path / "icon.bmp"))

    out_dir = tmp_path / "batch_mapped"
    mapping = {".png": ".jpg", ".bmp": ".webp"}
    convert_batch(str(tmp_path), str(out_dir), target_ext=mapping)

    assert (out_dir / "png_to_jpg" / "photo.jpg").exists()
    assert (out_dir / "bmp_to_webp" / "icon.webp").exists()


def test_identical_path_protection(tmp_image):
    """Ensure converting a file to the same path raises an error."""
    with pytest.raises(ConversionError, match="identical"):
        convert(tmp_image, tmp_image)
