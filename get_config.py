# (c) jag.m.singh@gmail.com
"""Configuration for the Plane Spotter application.

Reads a YAML config file. The path can be overridden with the
PLANE_SPOTTER_CONFIG environment variable (needed for Docker, where the
config path may differ, and for tests, which use a throwaway config).

Default location: /etc/plane-spotter/config.yaml
See config.sample.yaml in the repo for a documented example.
"""

import os

import yaml

config_file = os.environ.get(
    "PLANE_SPOTTER_CONFIG",
    "/etc/plane-spotter/config.yaml",
)

try:
    with open(config_file, "r") as file:
        config_dict = yaml.safe_load(file) or {}
except FileNotFoundError:
    raise SystemExit(
        f"Config file not found: {config_file}\n"
        "Set PLANE_SPOTTER_CONFIG or create /etc/plane-spotter/config.yaml "
        "(see config.sample.yaml for a documented example)."
    )
except yaml.YAMLError as e:
    raise SystemExit(f"Config file {config_file} is not valid YAML: {e}")

if not isinstance(config_dict, dict):
    raise SystemExit(f"Config file {config_file} must contain a YAML mapping.")

monitored_space = config_dict.get("monitored_space", {})
dump1090_file = config_dict.get("dump1090_file", "")
log_dir = os.path.expanduser(config_dict.get("log_dir", ""))
credentials_file = os.path.expanduser(config_dict.get("credentials_file", ""))
bucket_name = config_dict.get("bucket_name", "")

# New, optional keys (previously hardcoded in the capture scripts)
video_source = config_dict.get("video_source", "/dev/video0")
monitor_duration = config_dict.get("monitor_duration", 30)
poll_interval = config_dict.get("poll_interval", 5)
# GUI preview is off by default so the app runs headless inside Docker.
show_preview = bool(config_dict.get("show_preview", False))

_required_space_keys = {
    "lower_lat", "upper_lat", "lower_lon", "upper_lon",
    "lower_altitude", "upper_altitude",
}
_missing = _required_space_keys - set(monitored_space)
if _missing:
    raise SystemExit(f"Config 'monitored_space' is missing keys: {sorted(_missing)}")
if not dump1090_file:
    raise SystemExit("Config is missing 'dump1090_file'.")
if not log_dir:
    raise SystemExit("Config is missing 'log_dir'.")
# These two are only used at upload time — i.e. AFTER a 30s capture has
# already run. Validate them at startup so a typo fails immediately instead
# of losing the first aircraft that flies over.
if not credentials_file:
    raise SystemExit("Config is missing 'credentials_file'.")
if not bucket_name:
    raise SystemExit("Config is missing 'bucket_name'.")
if not os.path.exists(credentials_file):
    raise SystemExit(f"Credentials file not found: {credentials_file}")
