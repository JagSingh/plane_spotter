# (c) jag.m.singh@gmail.com
import datetime
import json
import logging
import time

import capture_picture
import get_config

logger = logging.getLogger(__name__)


def main():
    previous_monitored_aircraft_hex = []

    while True:
        try:
            poll_once(previous_monitored_aircraft_hex)
        except FileNotFoundError:
            logger.error("The file '%s' does not exist.", get_config.dump1090_file)
        except Exception:
            logger.exception("An error occurred")

        time.sleep(get_config.poll_interval)


def poll_once(previous_monitored_aircraft_hex):
    """Read aircraft.json once; trigger a capture for any newly-arrived
    aircraft in the monitored space. Mutates the previous-hex list in place
    so state persists across iterations."""
    with open(get_config.dump1090_file, "r") as file:
        dump1090_dict = json.load(file)

    if "now" in dump1090_dict:
        cst_time = datetime.datetime.fromtimestamp(
            dump1090_dict["now"]).replace(microsecond=0)
    else:
        logger.warning("Key 'now' not found in the aircraft.json file.")
        cst_time = datetime.datetime.now().replace(microsecond=0)

    if "aircraft" not in dump1090_dict:
        # dump1090-mutability always writes the "aircraft" key (an empty list
        # when the sky is quiet). Its absence means the ADS-B dump process is
        # not running and not writing this file - fatal. Stop the container,
        # that then goes into the docker restart loop. 
        raise SystemExit(
            f"'aircraft' key missing from {get_config.dump1090_file} - "
            "dump1090 is not running or not writing this file. Exiting."
        )

    space = get_config.monitored_space
    current_monitored_aircraft_hex = [
        aircraft["hex"] for aircraft in dump1090_dict["aircraft"]
        if "lat" in aircraft and "lon" in aircraft and "altitude" in aircraft
        and isinstance(aircraft["altitude"], (int, float))  # can be "ground"
        and space["lower_lat"] <= aircraft["lat"] <= space["upper_lat"]
        and space["lower_lon"] <= aircraft["lon"] <= space["upper_lon"]
        and space["lower_altitude"] <= aircraft["altitude"] <= space["upper_altitude"]
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
    new_aircraft = [a for a in dump1090_dict["aircraft"]
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

Docker notes: dump1090 and the RTL-SDR stay on the HOST. Kernel module
blacklisting and udev rules are host-wide kernel state and cannot be set
from inside a container; the container only reads aircraft.json over a
read-only bind mount.

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

$ apt search dump1090
$ sudo apt install dump1090-mutability

$ dump1090-mutability --interactive
Hex    Mode  Sqwk  Flight   Alt    Spd  Hdg    Lat      Long   RSSI  Msgs  Ti|
-------------------------------------------------------------------------------
 A0CBDB S           EJM108    3025  144  150   33.127  -97.040 -19.3    31  0
 A10931 S                     4800  242  030   33.142  -97.144 -24.3    14  1

$ sudo systemctl status dump1090-mutability.service

$ sudo systemctl stop dump1090-mutability.service

$ sudo systemctl start dump1090-mutability.service

$ cat /var/run/dump1090-mutability/aircraft.json

$ cat /var/log/dump1090-mutability.log
Thu May  1 22:11:17 2025 CDT  EB_SOURCE EB_VERSION starting up.
Using sample converter: UC8, integer/table path
Found 1 device(s):
0: unable to read device details
usb_open error -3
Please fix the device permissions, e.g. by installing the udev rules file rtl-sdr.rules
Error opening the RTLSDR device: Permission denied

$ lsusb
Bus 001 Device 013: ID 0bda:2838 Realtek Semiconductor Corp. RTL2838 DVB-T

$ sudo vi /etc/udev/rules.d/rtl-sdr.rules
Add line (see ID 0bda:2838):
SUBSYSTEMS=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE:="0666"

$ sudo udevadm control --reload-rules
Plug / unplug usb device

$ cat /var/run/dump1090-mutability/aircraft.json

"""