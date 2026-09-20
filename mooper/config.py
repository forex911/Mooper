import json
import os
import sys

CONFIG_PATH = os.path.expanduser("~/.mooper_config.json")

DEFAULTS = {
    "quality": "mid",
    "low_resource": "off",
    "default_output_folder": "(same as input)",
    "overwrite_policy": "ask",
    "default_video_format": "mp4",
    "default_image_format": "png",
    "default_fps": "30",
    "verbose": "off",
    "recursive_batch": "yes",
}

SAME_AS_INPUT = "(same as input)"

CHOICES = {
    "quality": ["low", "mid", "high"],
    "low_resource": ["on", "off"],
    "overwrite_policy": ["ask", "overwrite", "skip"],
    "verbose": ["on", "off"],
    "recursive_batch": ["yes", "no"],
}

_warned = set()


def _warn_once(message):
    if message not in _warned:
        _warned.add(message)
        print(f"Warning: {message}", file=sys.stderr)


def _core():
    if __package__:
        from . import core
    else:
        import core
    return core


def validate(key, value):
    """Return the normalised value for `key` or raise ValueError."""
    if key not in DEFAULTS:
        raise ValueError(f"Unknown setting '{key}'. Valid settings: {', '.join(DEFAULTS)}")

    value = str(value).strip()

    if key in CHOICES:
        v = value.lower()
        if v not in CHOICES[key]:
            raise ValueError(f"'{key}' must be one of: {', '.join(CHOICES[key])} (got '{value}')")
        return v

    if key == "default_fps":
        try:
            fps = int(value)
        except ValueError:
            raise ValueError(f"'default_fps' must be a whole number (got '{value}')") from None
        if not 1 <= fps <= 240:
            raise ValueError("'default_fps' must be between 1 and 240")
        return str(fps)

    if key in ("default_video_format", "default_image_format"):
        core = _core()
        allowed = core.VIDEO_EXTENSIONS if key == "default_video_format" else core.IMAGE_EXTENSIONS
        v = "." + value.lower().lstrip(".")
        if v not in allowed:
            raise ValueError(f"'{key}' must be one of: {', '.join(sorted(allowed))} (got '{value}')")
        return v

    if key == "default_output_folder":
        if not value:
            raise ValueError("'default_output_folder' cannot be empty; use '(same as input)'")
        return value

    return value


def _read_user_config():
    """Raw user overrides from disk ({} if missing or unreadable)."""
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("top-level JSON value must be an object")
        return data
    except Exception as e:
        _warn_once(f"Failed to load config from {CONFIG_PATH}: {e}. Using defaults.")
        return {}


def get_config():
    config = dict(DEFAULTS)
    for key, value in _read_user_config().items():
        if key not in DEFAULTS:
            continue
        try:
            config[key] = validate(key, value)
        except ValueError as e:
            _warn_once(f"Ignoring invalid saved setting ({e}); using default '{DEFAULTS[key]}'.")
    return config


def _write_user_config(data):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, CONFIG_PATH)  # atomic: never leaves a half-written file


def set_config(key, value):
    """Validate and save one setting. Returns the stored value.

    Raises ValueError for bad keys/values and OSError if the file can't be written.
    Only user-changed keys are stored, so future default changes still apply.
    """
    value = validate(key, value)
    user = {k: v for k, v in _read_user_config().items() if k in DEFAULTS}
    user[key] = value
    _write_user_config(user)
    return value


def reset_config():
    if os.path.exists(CONFIG_PATH):
        os.remove(CONFIG_PATH)
