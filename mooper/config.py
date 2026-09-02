import json
import os

CONFIG_PATH = os.path.expanduser("~/.mooper_config.json")

def get_config():
    config = {
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
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                user_config = json.load(f)
                config.update(user_config)
        except Exception:
            pass
    return config

def set_config(key, value):
    config = get_config()
    config[key] = value
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f)
    except Exception as e:
        print(f"Warning: Failed to save config: {e}")
