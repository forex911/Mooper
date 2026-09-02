# Mooper

A fast, interactive command-line media conversion tool built entirely in Python.  
No FFmpeg subprocess calls. No bloat. Just pure native bindings.

---

## Why Mooper?

Most media converters are thin wrappers around `subprocess.run(["ffmpeg", ...])`.  
Mooper is different — it interfaces directly with **libavcodec** and **libavformat** through [PyAV](https://pyav.org), and with **Pillow** for image processing. Every frame is handled in Python memory, giving you full programmatic control without shelling out to external processes.

---

## Features

| Feature | Description |
|---------|-------------|
| **Interactive CLI** | Point mooper at any file — it detects the format and presents a styled menu of valid targets |
| **Intelligent Batch Processing** | Point it at a folder — it scans all file types, asks what to convert each group to, and organizes output into categorized subfolders |
| **Two-Pass Video Engine** | Handles Variable Frame Rate (VFR) iPhone/Android footage without green frames or timestamp errors |
| **Real-Time Progress** | Live `tqdm` progress bars for every conversion — frame-by-frame for video, packet-by-packet for audio |
| **Global Config** | Persistent settings (`~/.mooper_config.json`) for quality, fps, overwrite policy, and more |
| **Interactive Settings Editor** | Run `mooper config` to visually browse and edit all settings with arrow-key navigation |
| **File Safety** | Automatically detects when input and output paths collide, preventing accidental data loss |
| **Low Resource Mode** | `--low-resource` flag for constrained environments (single-threaded, ultrafast preset) |
| **Remux-First Strategy** | When formats are container-compatible (e.g. H.264 in `.mov` → `.mp4`), mooper remuxes instantly without re-encoding |

---

## Supported Formats

### Images
`.png` `.jpg` `.jpeg` `.bmp` `.gif` `.tiff` `.tif` `.webp` `.ico` `.ppm` `.pgm` `.pbm` `.pcx` `.tga`

### Video
`.mp4` `.mov` `.mkv` `.avi` `.webm` `.flv` `.wmv` `.ts` `.ogv`

### Audio
`.mp3` `.aac` `.wav` `.flac` `.ogg` `.m4a`

### Cross-Format Conversions
| From | To | Method |
|------|----|--------|
| Image → Image | Any supported image format | Pillow with quality control |
| Video → Video | Any supported video format | Remux or two-pass H.264 transcode |
| Audio → Audio | Any supported audio format | PyAV with resampling |
| Video → Image | Extract a single frame as an image | Frame-accurate seeking |
| Video → Audio | Extract the audio track | Stream extraction + transcode |
| Image folder → Video | Compile an image sequence into a video | H.264 encoding at configurable FPS |

---

## Installation

**Requirements:** Python 3.8+

```bash
git clone https://github.com/your-username/mooper.git
cd mooper
pip install -e .
```

This installs mooper as a global CLI command. You can now run `mooper` from anywhere.

---

## Usage

### Quick Start — Interactive Mode

Just point mooper at a file. It figures out the rest:

```bash
mooper photo.png
```
```
Detected image file (.png).
? Select target format to convert to:
> .jpg
  .webp
  .bmp
  .gif
  ...
```

```bash
mooper video.MOV
```
```
Detected video file (.mov).
? Select target format to convert to:
> .mp4
  .mkv
  .avi
  ...

Target set to: video.mp4
Transcoding Video:  100%|██████████| 143/143 [00:04<00:00, 33.15frame/s]
Converted video.MOV -> video.mp4
```

### Explicit Mode

Skip the interactive menu by specifying both input and output:

```bash
mooper input.png output.webp
mooper recording.mov clip.mp4
mooper song.wav song.mp3
```

### Intelligent Batch Processing

Point mooper at a **folder** and select "Batch convert files":

```bash
mooper ./media_folder
```
```
Detected directory: ./media_folder
? What would you like to do with this directory?
> Batch convert files
  Create video from image sequence

Scanning directory for formats...
Found 2 format(s):
  .mov: 10 file(s)
  .jpg: 5 file(s)

? Select target format for .mov (10 files): .mp4
? Select target format for .jpg (5 files): (Skip)

Target set to: ./media_folder_converted

Found 10 files to convert.

[1/10] Processing IMG_2472.MOV...
Transcoding Video:  100%|██████████| 143/143 [00:04<00:00]
Successfully converted -> ./media_folder_converted/mov_to_mp4/IMG_2472.mp4

[2/10] Processing IMG_2473.MOV...
...
```

Output is automatically organized into subfolders by conversion type:
```
media_folder_converted/
  mov_to_mp4/
    IMG_2472.mp4
    IMG_2473.mp4
    ...
```

### Image Sequence → Video

```bash
mooper ./frames_folder
```
Select "Create video from image sequence", pick a format, and mooper compiles all images (sorted alphabetically) into a video at your configured FPS.

### Extract a Single Frame

```bash
mooper video.mp4 thumbnail.jpg --frame 120
```

### Extract Audio from Video

```bash
mooper video.mp4 audio.mp3
```

---

## Configuration

### Interactive Settings Editor

```bash
mooper config
```
```
? Select a setting to change:
> quality [high]
  low_resource [off]
  default_output_folder [(same as input)]
  overwrite_policy [ask]
  default_video_format [mp4]
  default_image_format [png]
  default_fps [30]
  verbose [off]
  recursive_batch [yes]
  Exit
```

Use arrow keys to select a setting, then pick a new value from a dropdown.  
Changes are saved instantly to `~/.mooper_config.json`.

### Direct Config Set

```bash
mooper config set quality high
mooper config set default_fps 60
mooper config set recursive_batch no
```

### Quality Levels

| Level | Video CRF | Video Preset | Image Quality |
|-------|-----------|-------------|---------------|
| `high` | 10 | slow | 100 |
| `mid` | 23 | medium | 80 |
| `low` | 32 | medium | 60 |

### All Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `quality` | `mid` | Global quality level for all conversions |
| `low_resource` | `off` | Use ultrafast preset + single thread |
| `default_output_folder` | `(same as input)` | Where to place converted files |
| `overwrite_policy` | `ask` | What to do when output file exists |
| `default_video_format` | `mp4` | Default target for video conversions |
| `default_image_format` | `png` | Default target for image conversions |
| `default_fps` | `30` | FPS for image-sequence-to-video |
| `verbose` | `off` | Show detailed conversion logs |
| `recursive_batch` | `yes` | Process subfolders in batch mode |

---

## CLI Reference

```
mooper [input] [output] [options]
```

| Argument / Flag | Description |
|----------------|-------------|
| `input` | Path to input file or directory |
| `output` | Path to output file or directory (optional — triggers interactive mode if omitted) |
| `--quality [low\|mid\|high]` | Override quality for this conversion |
| `--low-resource` | Use lightweight encoding settings |
| `--frame N` | Extract frame number N (video → image only) |
| `--fps N` | Set framerate for image sequence encoding (default: 24) |
| `--format .ext` | Target extension for CLI-driven batch conversion |
| `config` | Open interactive settings editor |
| `config set <key> <value>` | Set a config value directly |

---

## Architecture

```
mooper/
  __init__.py       # Package exports
  cli.py            # CLI entry point, interactive prompts, landing screen
  config.py         # Persistent JSON config (~/.mooper_config.json)
  core.py           # All conversion logic (Pillow + PyAV)
tests/
  test_core.py      # 9 automated tests covering all conversion paths
pyproject.toml      # Package metadata & dependencies
```

### How Video Transcoding Works

Mooper uses a **two-pass architecture** specifically designed to handle Variable Frame Rate (VFR) content from mobile devices:

1. **Pass 1 — Video**: Decode all video frames, reformat to `yuv420p` with even dimensions, assign monotonically increasing PTS with the correct time base, encode with `libx264`, and mux into the output container.

2. **Pass 2 — Audio**: Re-open the input file, decode all audio frames, resample to `fltp/stereo`, encode with `aac`, and mux into the same output container.

This separation prevents the timestamp interleaving conflicts that cause `EINVAL (Error 22)` crashes with VFR footage when video and audio packets are muxed together in a single pass.

### Conversion Strategy

```
Input file → Is format container-compatible?
  ├── YES → Remux (instant, no quality loss)
  └── NO  → Full transcode (two-pass for video)
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| [PyAV](https://pyav.org) | Native Python bindings for FFmpeg's libav* libraries |
| [Pillow](https://python-pillow.org) | Image format conversion and manipulation |
| [questionary](https://questionary.readthedocs.io) | Interactive terminal prompts with arrow-key navigation |
| [tqdm](https://tqdm.github.io) | Real-time progress bars |
| [rich](https://rich.readthedocs.io) | Colored terminal output and table rendering |

---

## Running Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

```
tests/test_core.py::test_image_to_image           PASSED
tests/test_core.py::test_audio_to_audio           PASSED
tests/test_core.py::test_video_to_video           PASSED
tests/test_core.py::test_video_extract_frame      PASSED
tests/test_core.py::test_video_extract_audio      PASSED
tests/test_core.py::test_images_to_video          PASSED
tests/test_core.py::test_convert_batch            PASSED
tests/test_core.py::test_convert_batch_mapping    PASSED
tests/test_core.py::test_identical_path_protection PASSED

9 passed
```

---

## License

MIT

---

_Built with native Python bindings. No subprocess calls. No bloat._
