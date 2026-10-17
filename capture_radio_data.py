# (c) jag.m.singh@gmail.com
"""Poll readsb's aircraft.json and trigger a capture for aircraft in view.

Host setup (the north-laptop and south-Chromebook receivers, drivers,
readsb, the feed between them, gain tuning): see docs/receiver-setup.md.
"""
import datetime
import json
import logging
import time

import capture_picture
import get_config

logger = logging.getLogger(__name__)

# How long aircraft.json may be missing before the process exits so Docker
# restarts the container. readsb recreates /run/readsb on every service
# restart unless RuntimeDirectoryPreserve=yes is set on the host; a bind
# mount made before that keeps pointing at the deleted directory, and only
# a container restart re-resolves it. 60s rides out a normal readsb restart
# (RestartSec=15) without flapping.
MISSING_FILE_EXIT_SECONDS = 60


def main():
    previous_monitored_aircraft_hex = []
    missing_since = None

    while True:
        try:
            poll_once(previous_monitored_aircraft_hex)
            missing_since = None
        except FileNotFoundError:
            now = time.monotonic()
            if missing_since is None:
                missing_since = now
            logger.error("The file '%s' does not exist.", get_config.adsb_file)
            if now - missing_since >= MISSING_FILE_EXIT_SECONDS:
                raise SystemExit(
                    f"{get_config.adsb_file} missing for "
                    f"{MISSING_FILE_EXIT_SECONDS}s - readsb down or the "
                    "/run/readsb bind mount is stale. Exiting for restart."
                )
        except Exception:
            logger.exception("An error occurred")

        time.sleep(get_config.poll_interval)


def in_monitored_space(aircraft, space):
    alt = aircraft.get("alt_baro")  # int feet, "ground", or absent
    return (
        "lat" in aircraft and "lon" in aircraft
        and isinstance(alt, (int, float))  # excludes "ground" and missing
        and space["lower_lat"] <= aircraft["lat"] <= space["upper_lat"]
        and space["lower_lon"] <= aircraft["lon"] <= space["upper_lon"]
        and space["lower_altitude"] <= alt <= space["upper_altitude"]
    )


def poll_once(previous_monitored_aircraft_hex):
    """Read aircraft.json once; trigger a capture for any newly-arrived
    aircraft in the monitored space. Mutates the previous-hex list in place
    so state persists across iterations."""
    with open(get_config.adsb_file, "r") as file:
        adsb_dict = json.load(file)

    if "now" in adsb_dict:
        cst_time = datetime.datetime.fromtimestamp(
            adsb_dict["now"]).replace(microsecond=0)
    else:
        logger.warning("Key 'now' not found in the aircraft.json file.")
        cst_time = datetime.datetime.now().replace(microsecond=0)

    if "aircraft" not in adsb_dict:
        # readsb always writes the "aircraft" key (an empty list when the
        # sky is quiet). Its absence means the decoder is not running and
        # not writing this file - fatal. Stop the container, that then goes
        # into the docker restart loop.
        raise SystemExit(
            f"'aircraft' key missing from {get_config.adsb_file} - "
            "readsb is not running or not writing this file. Exiting."
        )

    space = get_config.monitored_space
    current_monitored_aircraft_hex = [
        aircraft["hex"] for aircraft in adsb_dict["aircraft"]
        if in_monitored_space(aircraft, space)
    ]

    new_monitored_aircraft_hex = list(
        set(current_monitored_aircraft_hex) - set(previous_monitored_aircraft_hex))

    if not new_monitored_aircraft_hex:
        return

    # Only update state when something new appears. 
    # (These planes don't go in circles)
    previous_monitored_aircraft_hex[:] = current_monitored_aircraft_hex

    logger.info("CST Time: %s, New aircraft in monitored space: %s",
                cst_time, new_monitored_aircraft_hex)

    # One capture session per cycle: detect_and_upload_airplane blocks for
    # monitor_duration (30s) watching the whole visible space and keeps the
    # biggest airplane crop
    new_aircraft = [a for a in adsb_dict["aircraft"]
                    if a["hex"] in new_monitored_aircraft_hex]
    monitored_aircraft_data = new_aircraft[0]
    if len(new_aircraft) > 1:
        # With a properly defined box (one approach corridor), this should
        # never fire. If it does, the lat/lon bounds likely overlap an
        # adjacent runway's corridor - tighten monitored_space in the config.
        logger.warning("Multiple new aircraft in one poll window %s — the "
                       "monitored box may overlap another approach corridor. "
                       "Attributing capture to %s.",
                       new_monitored_aircraft_hex,
                       monitored_aircraft_data["hex"])
    logger.info("Monitored aircraft details: %s", monitored_aircraft_data)
    capture_picture.detect_and_upload_airplane(cst_time, monitored_aircraft_data)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()
