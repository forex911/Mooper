<p align="center">
  <img src="https://raw.githubusercontent.com/forex911/Mooper/main/logo.png" alt="Mooper Logo" width="450">
</p>

<p align="center">
  <strong>A lightning-fast, interactive command-line media conversion tool built in pure Python.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/mooper/"><img alt="PyPI Version" src="https://img.shields.io/pypi/v/mooper.svg"></a>
  <a href="https://pypi.org/project/mooper/"><img alt="Python Versions" src="https://img.shields.io/pypi/pyversions/mooper.svg"></a>
  <a href="https://github.com/forex911/Mooper/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-yellow.svg"></a>
</p>

<br>

**Mooper** is a modern, dependency-light CLI tool for converting media files between formats. 

Unlike most converters that simply act as wrappers around `subprocess.run(["ffmpeg"])`, Mooper interfaces directly with `libavcodec` and `libavformat` natively in Python memory via [PyAV](https://pyav.org). This guarantees blazing fast performance, cross-platform compatibility, and an incredibly low resource footprint.

## Features

- **Interactive UI**: Just point it at a file or folder. Mooper detects the media type and provides a beautiful interactive menu for conversion targets.
- **Intelligent Batch Processing**: Point it at a folder to automatically categorize, group, and convert mixed media files into organized subfolders.
- **Mobile VFR Support**: Advanced two-pass video engine specifically handles Variable Frame Rate (VFR) iPhone and Android footage without green frames or audio desync.
- **Remux-First**: Instantly remuxes container-compatible files (e.g. H.264 in `.mov` → `.mp4`) without re-encoding to preserve 100% original quality.
- **Persistent Config**: Use `mooper config` to open a visual editor for default qualities, frame rates, and overwrite policies.
- **Live Progress**: Granular, real-time `tqdm` progress bars for every frame and audio packet.

## Installation

Mooper requires Python 3.8 or newer. Install it globally via `pip`:

```bash
pip install mooper
```

## Quick Start

### 1. Interactive Conversion
The easiest way to use Mooper is to simply point it at a file. It will detect the format and ask you what to do.
```bash
mooper my_video.MOV
```
```text
Detected video file (.mov).
? Select target format to convert to:
> .mp4
  .mkv
  .webm
```

### 2. Intelligent Batch Folders
Point Mooper at an entire directory of mixed media. It will scan the folder and let you map out conversions for each filetype.
```bash
mooper ./vacation_media
```
```text
Scanning directory for formats...
Found 2 format(s):
  .mov: 10 file(s)
  .jpg: 5 file(s)

? Select target format for .mov (10 files): .mp4
? Select target format for .jpg (5 files): .webp
```
Mooper will automatically create `vacation_media_converted/mov_to_mp4/` and process your files!

### 3. Explicit / Scripting Mode
You can bypass the interactive menus by specifying the input and output directly:
```bash
mooper input.png output.webp
mooper recording.mov clip.mp4
```

### 4. Advanced Extractions
**Extract Audio from Video:**
```bash
mooper video.mp4 audio.mp3
```
**Extract a Single Frame as an Image:**
```bash
mooper video.mp4 thumbnail.jpg --frame 150
```
**Compile an Image Sequence into a Video:**
```bash
mooper ./folder_of_frames output_video.mp4 --fps 30
```

## CLI Commands Reference

Mooper can be run without any arguments to see the interactive landing screen, or run with arguments for precise control.

```bash
mooper [input] [output] [options]
```

### Arguments

| Argument / Flag | Description |
|----------------|-------------|
| `input` | Path to input file or directory |
| `output` | Path to output file or directory (optional — triggers interactive mode if omitted) |
| `--quality [low\|mid\|high]` | Override quality for this specific conversion |
| `--low-resource` | Use lightweight encoding settings (single-threaded, ultrafast preset) |
| `--frame N` | Extract frame number N (only applies when converting video → image) |
| `--fps N` | Set framerate for image sequence encoding (default: 24) |
| `--format .ext` | Target extension for explicit CLI-driven batch conversion |

### Configuration Commands

Mooper saves your preferences persistently to `~/.mooper_config.json`.

| Command | Description |
|---------|-------------|
| `mooper` | Show the landing screen containing your current global settings. |
| `mooper config` | Open the full **Interactive Settings Editor** to visually change defaults. |
| `mooper config set <key> <value>` | Scriptable command to update a setting directly (e.g. `mooper config set quality high`). |

**Available Config Keys:**
- `quality` (`low`, `mid`, `high`)
- `low_resource` (`on`, `off`)
- `default_video_format` (e.g., `mp4`)
- `default_image_format` (e.g., `png`)
- `default_fps` (e.g., `30`)
- `recursive_batch` (`yes`, `no`) — determines if batch processing looks inside subfolders.
- `overwrite_policy` (`ask`, `overwrite`, `skip`)

## Supported Formats

- **Video:** `.mp4`, `.mov`, `.mkv`, `.avi`, `.webm`, `.flv`, `.wmv`, `.ts`, `.ogv`
- **Audio:** `.mp3`, `.aac`, `.wav`, `.flac`, `.ogg`, `.m4a`
- **Images:** `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.gif`, `.tiff`, `.ico`

## License

MIT License. See [LICENSE](LICENSE) for details.
