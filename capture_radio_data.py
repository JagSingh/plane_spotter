# (c) jag.m.singh@gmail.com
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


"""
Setup hardware drivers and software (bare metal).

Docker notes: readsb and the RTL-SDR stay on the HOST. Kernel module
blacklisting and udev rules are host-wide kernel state and cannot be set
from inside a container; the container only reads aircraft.json over a
read-only bind mount of /run/readsb.

$ sudo apt install rtl-sdr

$ sudo vi /etc/modprobe.d/rtl-sdr-blacklist.conf
Add these lines to the file above:
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
blacklist dvb_usb_v2
blacklist dvb_core

$ rtl_test -t
Found 1 device(s):
  0:  Realtek, RTL2838UHIDIR, SN: 00000001

Using device 0: Generic RTL2832U OEM
Found Rafael Micro R820T tuner
Supported gain values (29): 0.0 0.9 1.4 2.7 3.7 7.7 8.7 12.5 14.4 15.7 16.6 19.7 20.7 22.9 25.4 28.0 29.7 32.8 33.8 36.4 37.2 38.6 40.2 42.1 43.4 43.9 44.5 48.0 49.6 
[R82XX] PLL not locked!
Sampling at 2048000 S/s.
No E4000 tuner found, aborting.

$ lsusb
Bus 001 Device 013: ID 0bda:2838 Realtek Semiconductor Corp. RTL2838 DVB-T

$ sudo vi /etc/udev/rules.d/rtl-sdr.rules
Add line (see ID 0bda:2838):
SUBSYSTEMS=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE:="0666"

$ sudo udevadm control --reload-rules
Plug / unplug usb device


Install readsb (wiedehopf). Only one decoder can own the dongle; the
installer stops and removes dump1090-mutability / dump1090-fa.

$ sudo bash -c "$(wget -O - https://github.com/wiedehopf/adsb-scripts/raw/master/readsb-install.sh)"

$ sudo readsb-set-location <antenna latitude> <antenna longitude>
$ sudo readsb-gain 29.7

Keep /run/readsb across readsb restarts. The unit declares
RuntimeDirectory=readsb without preserve, so systemd deletes and recreates
the directory on every stop/start (readsb-gain and readsb-set-location
both restart it). The container's bind mount then points at the deleted
directory until the container restarts. This drop-in keeps the directory
(and its inode) for the life of the boot:

$ sudo systemctl edit readsb
    [Service]
    RuntimeDirectoryPreserve=yes
$ sudo systemctl restart readsb
$ docker compose up -d --force-recreate     # pick up the stable directory

(capture_radio_data.py also exits after 60s with aircraft.json missing, so
Docker's restart policy recovers a stale mount even without the drop-in.)

$ sudo systemctl status readsb
$ journalctl -u readsb -n 50
$ cat /etc/default/readsb
$ cat /run/readsb/aircraft.json

Live table (stop the service first; only one process can open the dongle):
$ sudo systemctl stop readsb
$ readsb --device-type rtlsdr --gain 29.7 --interactive
$ sudo systemctl start readsb

aircraft.json schema differences from mutability:
altitude -> alt_baro, speed -> gs, vert_rate -> baro_rate.


Receiver gain tuning

Fixed gain, not "auto". readsb-gain auto is now the installer default; it
adapts to the noise floor, which makes the accepted/min comparison below
meaningless and lets gain drift with traffic. Measured under mutability at
max gain: 680k Mode S attempts per minute, 59% CRC failures, 11k usable
messages. At 29.7: 45k attempts, 22% failures, 18k usable. Re-run the sweep
after the switch: same tuner, different demodulator.

Set the receiver position too. Without it the decoder must use global CPR
decoding, which needs a matched even/odd message pair before it can report
any position. With a position it decodes from a single message, so
aircraft acquire sooner which determines whether they are still in the
camera's view when the capture starts.

1. $ sudo readsb-set-location <lat> <lon>

2. For each gain in 36.4, 29.7, 25.4, 20.7:
       $ sudo readsb-gain <gain>        # restarts readsb
       $ sleep 360                      # let the 5-minute window fill
       $ python3 -c "
         import json
         s=json.load(open('/run/readsb/stats.json'))['last5min']['local']
         print(sum(s['accepted'])/5, round(100*s['bad']/s['modes'],1))"

3. Pick the highest accepted/min. Use last5min, not last1min: traffic
   arrives in banks and one-minute samples varied 40% at the same gain
   here. Within ~10%, take the lower gain - less CPU, and headroom before
   clipping on aircraft passing overhead.

4. Sanity check rssi in aircraft.json. Close aircraft should read about
   -10 to -30 dBFS. Values pinned near 0 mean clipping; values in a narrow
   band regardless of range mean saturation.

Verify what is actually running (the config file is not proof):
    $ ps aux | grep [r]eadsb | grep -oE -- "--(gain|lat|lon) [0-9.auto-]+"

"""