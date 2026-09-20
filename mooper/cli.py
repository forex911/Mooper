import argparse
import os
import sys
import traceback

# Works both as `python -m mooper.cli` / installed entry point and `python cli.py`.
if __package__:
    from .core import (
        convert, convert_batch, _kind, _ext,
        IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS,
    )
    from .config import (
        get_config, set_config, reset_config, CHOICES, SAME_AS_INPUT,
    )
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from core import (
        convert, convert_batch, _kind, _ext,
        IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS,
    )
    from config import (
        get_config, set_config, reset_config, CHOICES, SAME_AS_INPUT,
    )


def _die(message, code=1):
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(code)


def _require_tty(what):
    if not sys.stdin.isatty():
        _die(f"{what} needs an interactive terminal. "
             "Pass all arguments on the command line instead.", 2)


# ---------------------------------------------------------------------------
# Shared style + prompt helper
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


def _select(message, choices, default=None):
    """questionary.select that never crashes on a `default` that isn't a choice."""
    import questionary
    return questionary.select(
        message,
        choices=choices,
        default=default if default in choices else None,
        style=_get_style(),
    ).ask()


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

    table = Table(
        title="Current Settings",
        show_header=True,
        header_style="bold magenta",
        border_style="cyan",
    )
    table.add_column("Setting", style="bold")
    table.add_column("Current Value")
    for key, val in get_config().items():
        table.add_row(key, str(val))

    console.print(table)
    console.print("\nRun [bold cyan]'mooper <input> [output]'[/bold cyan] to convert a file or folder.")
    console.print("Run [bold cyan]'mooper config'[/bold cyan] to interactively change settings.")
    console.print("Run [bold cyan]'mooper --help'[/bold cyan] for all options.")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Config commands
# ---------------------------------------------------------------------------

def interactive_config():
    _require_tty("'mooper config'")
    import questionary

    while True:
        config = get_config()
        choices = [f"{k} [{v}]" for k, v in config.items()] + ["Exit"]

        selection = _select("Select a setting to change:", choices)
        if not selection or selection == "Exit":
            break

        key = selection.split(" [")[0]
        current = config.get(key, "")

        if key in CHOICES:
            new_val = _select(f"{key}:", CHOICES[key], default=current)
        elif key in ("default_video_format", "default_image_format"):
            fmts = sorted(VIDEO_EXTENSIONS if "video" in key else IMAGE_EXTENSIONS)
            new_val = _select(f"Select {key}:", fmts, default=current)
        else:
            new_val = questionary.text(
                f"Enter new value for {key}:", default=str(current), style=_get_style()
            ).ask()

        if new_val is None:
            continue
        try:
            stored = set_config(key, new_val)
            print(f"Updated {key} -> {stored}\n")
        except (ValueError, OSError) as e:
            print(f"Error: {e}\n")


def _config_command(rest):
    if not rest:
        interactive_config()
        return 0

    action = rest[0]
    if action == "set":
        if len(rest) != 3:
            _die("usage: mooper config set <key> <value>", 2)
        try:
            stored = set_config(rest[1], rest[2])
        except ValueError as e:
            _die(str(e), 2)
        except OSError as e:
            _die(f"could not save config: {e}")
        print(f"Config '{rest[1]}' set to '{stored}'")
        return 0

    if action in ("list", "show"):
        for k, v in get_config().items():
            print(f"{k} = {v}")
        return 0

    if action == "reset":
        reset_config()
        print("Configuration reset to defaults.")
        return 0

    _die("usage: mooper config [set <key> <value> | list | reset]", 2)


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

def _get_format_choices(kind):
    """Conversion targets that core.convert() actually supports for this kind."""
    if kind == "image":
        return sorted(IMAGE_EXTENSIONS)
    if kind == "video":
        return sorted(VIDEO_EXTENSIONS) + sorted(AUDIO_EXTENSIONS) + sorted(IMAGE_EXTENSIONS)
    if kind == "audio":
        return sorted(AUDIO_EXTENSIONS)
    return []


def _kind_from_ext(ext):
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    return "unknown"


def _preferred_format(kind, config):
    if kind == "video":
        return config.get("default_video_format")
    if kind == "image":
        return config.get("default_image_format")
    return None


def _place(path, config):
    """Apply `default_output_folder` to an auto-generated output path."""
    folder = config.get("default_output_folder", SAME_AS_INPUT)
    if not folder or folder == SAME_AS_INPUT:
        return path
    folder = os.path.abspath(os.path.expanduser(folder))
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, os.path.basename(path))


# ---------------------------------------------------------------------------
# Interactive batch format prompter
# ---------------------------------------------------------------------------

def _prompt_batch_format(input_dir, config):
    _require_tty("Choosing batch formats")

    print("\nScanning directory for formats...")
    recursive = config.get("recursive_batch", "yes") == "yes"
    found = {}

    for root, dirs, files in os.walk(input_dir):
        if not recursive:
            dirs.clear()
        for f in files:
            try:
                _kind(os.path.join(root, f))
            except Exception:
                continue
            ext = _ext(f)
            if ext:
                found[ext] = found.get(ext, 0) + 1

    if not found:
        print("No supported media files found.")
        sys.exit(0)

    print(f"Found {len(found)} format(s):")
    for ext, count in sorted(found.items()):
        print(f"  {ext}: {count} file(s)")
    print()

    mapping = {}
    for ext in sorted(found):
        kind = _kind_from_ext(ext)
        options = [c for c in _get_format_choices(kind) if c != ext]
        target = _select(
            f"Select target format for {ext} ({found[ext]} files):",
            ["(Skip)"] + options,
            default=_preferred_format(kind, config),
        )
        if target is None:
            print("Aborted.")
            sys.exit(0)
        if target != "(Skip)":
            mapping[ext] = target

    if not mapping:
        print("No formats selected to convert. Aborting.")
        sys.exit(0)
    return mapping


# ---------------------------------------------------------------------------
# Overwrite handling
# ---------------------------------------------------------------------------

def _make_conflict_resolver():
    """Returns f(path) -> 'overwrite' | 'skip' for batch runs with policy 'ask'."""
    state = {"all": None}

    def resolve(path):
        if state["all"]:
            return state["all"]
        choice = _select(
            f"'{path}' already exists:",
            ["Overwrite", "Skip", "Overwrite all", "Skip all"],
            default="Skip",
        )
        if choice is None:
            raise KeyboardInterrupt
        if choice.endswith("all"):
            state["all"] = choice.split()[0].lower()
            return state["all"]
        return choice.lower()

    return resolve


def _should_write(path, policy):
    """Decide whether a single-file output may be written."""
    if not os.path.exists(path):
        return True
    if policy == "overwrite":
        return True
    if policy == "skip":
        print(f"Skipped: '{path}' already exists.")
        return False
    # policy == "ask"
    if not sys.stdin.isatty():
        _die(f"'{path}' already exists. Use --overwrite or --skip-existing.")
    import questionary
    answer = questionary.confirm(
        f"'{path}' already exists. Overwrite?", default=False, style=_get_style()
    ).ask()
    return bool(answer)


# ---------------------------------------------------------------------------
# Main CLI entry point
# ---------------------------------------------------------------------------

def _build_parser():
    parser = argparse.ArgumentParser(
        prog="mooper",
        description="Convert media files (images, video, audio) between formats.",
        epilog="Settings: 'mooper config' (interactive), 'mooper config set <key> <value>', "
               "'mooper config list', 'mooper config reset'.",
    )
    parser.add_argument("input", nargs="?", default=None, help="Path to input file or directory")
    parser.add_argument("output", nargs="?", help="Path to output file or directory (omit to choose interactively)")
    parser.add_argument("--low-resource", action="store_true",
                        help="Use lighter encoding settings for low-end systems")
    parser.add_argument("--quality", choices=["low", "mid", "high"], default=None,
                        help="Quality level. With no input, saves it as the global default.")
    parser.add_argument("--frame", type=int, default=None,
                        help="Frame number to extract (video -> image only, starts at 0)")
    parser.add_argument("--fps", type=int, default=None,
                        help="Framerate for image-sequence -> video (default: 'default_fps' setting)")
    parser.add_argument("--format", type=str, default=None,
                        help="Target extension for batch conversion of a directory (e.g. .jpg, .mp4)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--overwrite", action="store_true",
                       help="Overwrite existing output files without asking")
    group.add_argument("--skip-existing", action="store_true",
                       help="Never overwrite; skip files whose output already exists")
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv:
        show_landing()

    if argv[0] == "config":
        sys.exit(_config_command(argv[1:]))

    parser = _build_parser()
    args = parser.parse_args(argv)   # unknown/typo'd flags are now an error
    config = get_config()
    verbose = config.get("verbose") == "on"

    try:
        _run(args, parser, config)
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        if verbose:
            traceback.print_exc()
        _die(str(e))


def _run(args, parser, config):
    # --- Quality-only mode: mooper --quality high ---
    if args.quality and not args.input:
        stored = set_config("quality", args.quality)
        print(f"Global default quality set to: {stored}")
        return

    if not args.input:
        show_landing()

    if not os.path.exists(args.input):
        _die(f"'{args.input}' does not exist.")

    # --- Resolve active settings ---
    active_quality = args.quality or config["quality"]
    low_resource = args.low_resource or config["low_resource"] == "on"
    fps = args.fps if args.fps is not None else int(config["default_fps"])
    if fps <= 0:
        parser.error("--fps must be greater than 0")
    if args.frame is not None and args.frame < 0:
        parser.error("--frame must be 0 or greater")
    policy = ("overwrite" if args.overwrite
              else "skip" if args.skip_existing
              else config["overwrite_policy"])
    recursive = config["recursive_batch"] == "yes"
    input_is_dir = os.path.isdir(args.input)

    output = args.output
    batch_format = args.format  # str, or {ext: ext} mapping from the prompt

    # --- Interactive output selection (no output given) ---
    if not output:
        kind = _kind(args.input)   # raises a clear error for unsupported input

        if kind == "directory":
            clean = os.path.abspath(args.input).rstrip(os.sep)
            if batch_format:
                # --format given: no need to ask anything
                output = _place(f"{clean}_converted", config)
            else:
                _require_tty("Choosing what to do with a directory")
                print(f"Detected directory: {args.input}")
                action = _select(
                    "What would you like to do with this directory?",
                    ["Batch convert files", "Create video from image sequence"],
                )
                if not action:
                    print("Aborted.")
                    return
                if action == "Batch convert files":
                    batch_format = _prompt_batch_format(args.input, config)
                    output = _place(f"{clean}_converted", config)
                else:
                    target_ext = _select(
                        "Select target video format for sequence:",
                        sorted(VIDEO_EXTENSIONS),
                        default=config.get("default_video_format"),
                    )
                    if not target_ext:
                        print("Aborted.")
                        return
                    output = _place(os.path.join(args.input, f"output{target_ext}"), config)
            print(f"\nTarget set to: {output}")
        else:
            _require_tty("Choosing an output format")
            print(f"Detected {kind} file ({_ext(args.input)}).")
            target_ext = _select(
                "Select target format to convert to:",
                _get_format_choices(kind),
                default=_preferred_format(kind, config),
            )
            if not target_ext:
                print("Aborted.")
                return
            output = os.path.splitext(args.input)[0] + target_ext
            if os.path.realpath(args.input) == os.path.realpath(output):
                output = os.path.splitext(args.input)[0] + "_converted" + target_ext
            output = _place(output, config)
            print(f"\nTarget set to: {output}")

    # --- Dispatch ---
    is_batch = input_is_dir and (
        bool(batch_format)
        or os.path.isdir(output)
        or _ext(output) not in VIDEO_EXTENSIONS   # case-insensitive
    )

    if is_batch:
        if not batch_format:
            batch_format = _prompt_batch_format(args.input, config)

        resolver = _make_conflict_resolver() if (policy == "ask" and sys.stdin.isatty()) else None
        result = convert_batch(
            args.input,
            output,
            target_ext=batch_format,
            low_resource=low_resource,
            quality=active_quality,
            recursive=recursive,
            fps=fps,
            frame_number=args.frame,
            overwrite=policy,
            on_conflict=resolver,
        )

        print(f"\nBatch finished: {result.converted} converted, "
              f"{len(result.skipped)} skipped, {len(result.failed)} failed.")
        if result.skipped and config.get("verbose") == "on":
            for path, reason in result.skipped:
                print(f"  skipped {path}: {reason}")
        if result.failed:
            print("\nFailures:", file=sys.stderr)
            for path, err in result.failed:
                print(f"  {path}: {err}", file=sys.stderr)
            sys.exit(1)
        return

    if not _should_write(output, policy):
        return

    convert(
        args.input,
        output,
        low_resource=low_resource,
        frame_number=args.frame,
        fps=fps,
        quality=active_quality,
        overwrite="overwrite",   # policy already resolved above
    )
    print(f"Converted {args.input} -> {output}")


if __name__ == "__main__":
    main()
