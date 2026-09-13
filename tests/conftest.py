# (c) jag.m.singh@gmail.com
"""Stub out hardware/cloud dependencies so unit tests run anywhere
(no camera, no SDR, no GCS credentials, no YOLO download)."""

import os
import sys
import tempfile
from unittest.mock import MagicMock

import yaml

# --- stub heavy third-party modules before any project import ---
for mod_name in ["cv2", "ultralytics", "google", "google.cloud",
                 "google.cloud.storage"]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# --- point get_config at a temp config file ---
_tmpdir = tempfile.mkdtemp(prefix="plane_spotter_test_")
print(f"Using temp dir for test config/logs: {_tmpdir}")
_log_dir = os.path.join(_tmpdir, "logs")
print(f"Using temp dir for test logs: {_log_dir}")
os.makedirs(_log_dir, exist_ok=True)

_config = {
    "dump1090_file": os.path.join(_tmpdir, "aircraft.json"),
    "monitored_space": {
        "lower_lat": 33.0, "upper_lat": 33.2,
        "lower_lon": -97.2, "upper_lon": -97.0,
        "lower_altitude": 1000, "upper_altitude": 5000,
    },
    "log_dir": _log_dir,
    "credentials_file": os.path.join(_tmpdir, "creds.json"),
    "bucket_name": "test-bucket",
    "poll_interval": 0,
}
_config_path = os.path.join(_tmpdir, "plane_spotter.yaml")
with open(_config_path, "w") as f:
    yaml.safe_dump(_config, f)

# get_config now checks that credentials_file exists; the GCS client itself
# is mocked, so the contents are irrelevant — only the path must resolve.
with open(_config["credentials_file"], "w") as f:
    f.write("{}")

os.environ["PLANE_SPOTTER_CONFIG"] = _config_path

# make the project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
