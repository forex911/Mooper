import argparse
import os
import sys

from .core import convert, convert_batch, _kind, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS, _ext
from .config import get_config, set_config


# ---------------------------------------------------------------------------
# Shared style (single definition, reused everywhere)
# ---------------------------------------------------------------------------

def _get_style():
    from questionary import Style
    return Style([
        ('qmark', 'fg:#00e5ff bold'),
        ('question', 'bold'),
        ('answer', 'fg:#ff007f bold'),
        ('pointer', 'fg:#00e5ff bold'),
        ('highlighted', 'fg:#00e5ff bold'),
        ('instruction', 'fg:#aaaaaa italic'),
    ])


# ---------------------------------------------------------------------------
# Landing screen
# ---------------------------------------------------------------------------

def show_landing():
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text
    
    console = Console()
    
    logo = """   __  __                            
  |  \\/  | ___   ___  _ __   ___ _ __ 
  | |\\/| |/ _ \\ / _ \\| '_ \\ / _ \\ '__|
  | |  | | (_) | (_) | |_) |  __/ |   
  |_|  |_|\\___/ \\___/| .__/ \\___|_|   
                     |_|              """
    
    console.print(Text(logo, style="bold green"))
    console.print()
    
    config = get_config()
    table = Table(
        title="Current Settings",
        show_header=True,
        header_style="bold magenta",
        border_style="cyan",
    )
    table.add_column("Setting", style="bold")
    table.add_column("Current Value")
    
    for key, val in config.items():
        table.add_row(key, str(val))
        
    console.print(table)
    console.print("\nRun [bold cyan]'mooper <input> <output>'[/bold cyan] to convert a file.")
    console.print("Run [bold cyan]'mooper config'[/bold cyan] to interactively change settings.")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Interactive config editor
# ---------------------------------------------------------------------------

def interactive_config():
    import questionary

    custom_style = _get_style()

    while True:
        config = get_config()
        
        choices = []
        for k, v in config.items():
            choices.append(f"{k} [{v}]")
        choices.append("Exit")

        selection = questionary.select(
            "Select a setting to change:",
            choices=choices,
            style=custom_style
        ).ask()

        if not selection or selection == "Exit":
            break

        key = selection.split(" [")[0]
        current_val = config.get(key, "")

        # Provide nice predefined options for known keys, else text input
        if key == "quality":
            new_val = questionary.select("Select quality:", choices=["low", "mid", "high"], default=current_val, style=custom_style).ask()
        elif key in ("low_resource", "verbose"):
            new_val = questionary.select(f"Enable {key}?", choices=["on", "off"], default=current_val, style=custom_style).ask()
        elif key == "overwrite_policy":
            new_val = questionary.select("Overwrite policy:", choices=["ask", "overwrite", "skip"], default=current_val, style=custom_style).ask()
        elif key == "recursive_batch":
            new_val = questionary.select("Recursive batch?", choices=["yes", "no"], default=current_val, style=custom_style).ask()
        elif key in ("default_video_format", "default_image_format"):
            fmt_choices = sorted(VIDEO_EXTENSIONS) if "video" in key else sorted(IMAGE_EXTENSIONS)
            new_val = questionary.select(f"Select {key}:", choices=fmt_choices, style=custom_style).ask()
        else:
            new_val = questionary.text(f"Enter new value for {key}:", default=str(current_val), style=custom_style).ask()

        if new_val is not None:
            set_config(key, new_val)
            print(f"Updated {key} -> {new_val}\n")


# ---------------------------------------------------------------------------
# Smart format choices based on media kind
# ---------------------------------------------------------------------------

def _get_format_choices(kind: str):
    """Return appropriate conversion target choices for a given media kind."""
    if kind == "image":
        return sorted(IMAGE_EXTENSIONS)
    elif kind == "video":
        return sorted(VIDEO_EXTENSIONS) + sorted(AUDIO_EXTENSIONS) + sorted(IMAGE_EXTENSIONS)
    elif kind == "audio":
        return sorted(AUDIO_EXTENSIONS)
    return []


# ---------------------------------------------------------------------------
# Helper: classify an extension without needing a file path
# ---------------------------------------------------------------------------

def _kind_from_ext(ext: str) -> str:
    """Return 'image', 'video', or 'audio' for a given extension."""
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    return "unknown"


# ---------------------------------------------------------------------------
# Main CLI entry point
# ---------------------------------------------------------------------------

def main():
    import questionary

    # --- No-arg landing screen ---
    if len(sys.argv) == 1:
        show_landing()

    # --- Direct config set: mooper config set <key> <value> ---
    if len(sys.argv) >= 4 and sys.argv[1] == "config" and sys.argv[2] == "set":
        key = sys.argv[3]
        val = sys.argv[4] if len(sys.argv) > 4 else ""
        set_config(key, val)
        print(f"Config '{key}' set to '{val}'")
        sys.exit(0)

    # --- Interactive config: mooper config ---
    if len(sys.argv) == 2 and sys.argv[1] == "config":
        interactive_config()
        sys.exit(0)

    # --- Argument parsing ---
    parser = argparse.ArgumentParser(
        prog="mooper",
        description="Convert media files between formats.",
    )
    parser.add_argument("input", nargs="?", default=None, help="Path to input file or directory")
    parser.add_argument("output", nargs='?', help="Path to output file or directory (omit to see suggestions)")
    parser.add_argument(
        "--low-resource", action="store_true",
        help="Use lighter encoding settings for low-end systems",
    )
    parser.add_argument(
        "--quality", nargs="?", const="PROMPT", default=None,
        choices=["low", "mid", "high", "PROMPT"],
        help="Set the quality level (low/mid/high). If used without input, configures the global default.",
    )
    parser.add_argument(
        "--frame", type=int, default=None,
        help="Frame number to extract (video -> image only)",
    )
    parser.add_argument(
        "--fps", type=int, default=24,
        help="Framerate for image-sequence to video encoding (default: 24)",
    )
    parser.add_argument(
        "--format", type=str, default=None,
        help="Target extension for batch conversion (e.g. .jpg, .mp4). Required if input and output are directories.",
    )

    args, _unknown = parser.parse_known_args()
    custom_style = _get_style()

    # --- Quality-only mode: mooper --quality ---
    if args.quality == "PROMPT" or (args.quality and not args.input):
        quality = args.quality if args.quality != "PROMPT" else None
        if not quality:
            quality = questionary.select(
                "Select default quality setting:",
                choices=["low", "mid", "high"],
                style=custom_style
            ).ask()
            if not quality:
                sys.exit(0)
        set_config("quality", quality)
        print(f"Global default quality set to: {quality}")
        sys.exit(0)

    # --- No input provided: show landing ---
    if not args.input:
        show_landing()

    # --- Validate input exists ---
    if not os.path.exists(args.input):
        print(f"Error: '{args.input}' does not exist.", file=sys.stderr)
        sys.exit(1)

    # --- Resolve active quality ---
    active_quality = args.quality or get_config().get("quality", "mid")
    input_is_dir = os.path.isdir(args.input)

    # --- Interactive output selection (when no output is specified) ---
    if not args.output:
        try:
            kind = _kind(args.input)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        ext = _ext(args.input) if not input_is_dir else ""

        if kind == "directory":
            print(f"Detected directory: {args.input}")
            action = questionary.select(
                "What would you like to do with this directory?",
                choices=["Batch convert files", "Create video from image sequence"],
                style=custom_style,
            ).ask()

            if not action:
                print("Aborted.")
                sys.exit(0)

            if action == "Batch convert files":
                # --- Intelligent batch: scan extensions, ask per-group ---
                print("\nScanning directory for formats...")
                recursive_batch = get_config().get("recursive_batch", "yes") == "yes"
                found_exts = {}

                for root, dirs, files in os.walk(args.input):
                    if not recursive_batch:
                        dirs.clear()  # Prevent os.walk from descending
                    for f in files:
                        fpath = os.path.join(root, f)
                        try:
                            _kind(fpath)  # Validate it's a supported format
                            ext_val = _ext(f)
                            found_exts[ext_val] = found_exts.get(ext_val, 0) + 1
                        except Exception:
                            pass

                if not found_exts:
                    print("No supported media files found.")
                    sys.exit(0)

                print(f"Found {len(found_exts)} format(s):")
                for ext_val, count in sorted(found_exts.items()):
                    print(f"  {ext_val}: {count} file(s)")

                print()
                mapping = {}
                for ext_val in sorted(found_exts.keys()):
                    count = found_exts[ext_val]
                    target = questionary.select(
                        f"Select target format for {ext_val} ({count} files):",
                        choices=["(Skip)"] + _get_format_choices(_kind_from_ext(ext_val)),
                        style=custom_style,
                    ).ask()

                    if target is None:
                        print("Aborted.")
                        sys.exit(0)

                    if target != "(Skip)":
                        mapping[ext_val] = target

                if not mapping:
                    print("No formats selected to convert. Aborting.")
                    sys.exit(0)

                clean_input = args.input.rstrip(os.sep)
                args.output = f"{clean_input}_converted"
                args.format = mapping
                print(f"\nTarget set to: {args.output}")

            else:
                # --- Image sequence -> video ---
                choices = sorted(VIDEO_EXTENSIONS)
                target_ext = questionary.select(
                    "Select target video format for sequence:",
                    choices=choices,
                    style=custom_style,
                ).ask()

                if not target_ext:
                    print("Aborted.")
                    sys.exit(0)

                args.output = os.path.join(args.input, f"output{target_ext}")
                print(f"\nTarget set to: {args.output}")

        else:
            # --- Single file conversion ---
            print(f"Detected {kind} file ({ext}).")
            choices = _get_format_choices(kind)
            question = "Select target format to convert to:"

            target_ext = questionary.select(
                question,
                choices=choices,
                style=custom_style,
            ).ask()

            if not target_ext:
                print("Aborted.")
                sys.exit(0)

            args.output = os.path.splitext(args.input)[0] + target_ext

            # Prevent identical input/output paths which would delete the original
            if os.path.abspath(args.input) == os.path.abspath(args.output):
                args.output = os.path.splitext(args.input)[0] + "_converted" + target_ext

            print(f"\nTarget set to: {args.output}")

    # --- Dispatch conversion ---
    try:
        if input_is_dir and (os.path.isdir(args.output) or not os.path.splitext(args.output)[1]):
            fmt = args.format
            if not fmt:
                print("Error: --format is required for batch directory conversion.", file=sys.stderr)
                sys.exit(1)

            recursive_batch = get_config().get("recursive_batch", "yes") == "yes"
            convert_batch(
                args.input,
                args.output,
                target_ext=fmt,
                low_resource=args.low_resource,
                quality=active_quality,
                recursive=recursive_batch,
            )
            print(f"\nBatch conversion completed: {args.input} -> {args.output}")
        else:
            convert(
                args.input,
                args.output,
                low_resource=args.low_resource,
                frame_number=args.frame,
                fps=args.fps,
                quality=active_quality,
            )
            print(f"Converted {args.input} -> {args.output}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
