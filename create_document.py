# (c) jag.m.singh@gmail.com
import logging
import os

import requests

import gcs
import get_config

logger = logging.getLogger(__name__)

HEXDB_TIMEOUT_SECONDS = 10


def lookup_aircraft_type(aircraft_hex):
    """Fetch the aircraft type from hexdb.io.

      "unlisted"  - hexdb has the record but no Type field
      "not found" - hexdb has no record for this hex (common for military
                    and some private aircraft)
      "lookup failed" - timeout, connection error, or a server-side error
    """
    try:
        response = requests.get(
            f"https://hexdb.io/api/v1/aircraft/{aircraft_hex}",
            timeout=HEXDB_TIMEOUT_SECONDS,  # avoid hanging the whole process on a slow hexdb.io response
        )
        if response.status_code == 404:
            logger.info("hexdb has no record for %s", aircraft_hex)
            return "not found"
        response.raise_for_status()
        return response.json().get("Type") or "unlisted"
    except (requests.RequestException, ValueError) as e:
        logger.warning("Error fetching aircraft type for %s: %s", aircraft_hex, e)
        return "lookup failed"


def update_html_file(capture_time, airplane_data, airplane_picture):
    filename = f"planes_{capture_time.strftime('%y%m%d')}.html"
    file_path = os.path.join(get_config.log_dir, filename)

    aircraft_hex = airplane_data.get("hex", "unknown")
    aircraft_type = lookup_aircraft_type(aircraft_hex)

    print_airplane_data = (
        f'Aircraft: {aircraft_hex} | '
        f'Type: {aircraft_type} | '
        f'Flight: {airplane_data.get("flight", "unknown")} | '
        f'Altitude: {airplane_data.get("altitude", "unknown")} feet | '
        f'Speed: {airplane_data.get("speed", "unknown")} knots | '
        f'Vertical Speed: {airplane_data.get("vert_rate", "unknown")} feet/min'
    )
    logger.info("Airplane data: %s", print_airplane_data)

    # One HTML file per day; create it with the page header on first sighting.
    if not os.path.exists(file_path):
        with open(file_path, "w") as file:
            file.write(
                '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
                '<title>Plane Spotter</title>'
                '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
                '<link rel="stylesheet" href="https://jagmsingh.com/style.css">'
                '</head><body>'
                f'<header><h3>{capture_time.strftime("%B %-d, %Y")}</h3>'
                '<p>&copy; <a href="mailto:jag.m.singh@gmail.com">'
                'jag.m.singh@gmail.com</a></p></header>'
                '<nav><a href="https://jagmsingh.com/Plane%20Spotter/'
                'Plane%20Spotter.html">About Plane Spotter</a></nav>\n'
            )

    # Append the new airplane data to the file
    with open(file_path, "a") as file:
        file.write(
            f'<h4>{capture_time.strftime("%Y-%m-%d %H:%M:%S")}</h4>'
            + print_airplane_data
            + f' <img src="{airplane_picture}" alt="Airplane Picture" /><hr>\n'
        )

    # Upload the file to Google Cloud Storage
    blob = gcs.bucket().blob(filename)
    blob.upload_from_filename(file_path)


"""
aircraft.json
This file contains dump1090's list of recently seen aircraft. The keys are:

now: the time this file was generated, in seconds since the Unix epoch.
messages: total Mode S messages processed since dump1090 started.
aircraft: an array of JSON objects, one per known aircraft. Keys are omitted
if data is not available:

    hex: the 24-bit ICAO identifier of the aircraft, as 6 hex digits. The
        identifier may start with '~', this means that the address is a
        non-ICAO address (e.g. from TIS-B).
    squawk: the 4-digit squawk (octal representation)
    flight: the flight name / callsign
    lat, lon: the aircraft position in decimal degrees
    nucp: the NUCp (navigational uncertainty category) reported for the position
    seen_pos: how long ago (in seconds before "now") the position was last updated
    altitude: the aircraft altitude in feet, or "ground" if it is reporting
        it is on the ground
    vert_rate: vertical rate in feet/minute
    track: true track over ground in degrees (0-359)
    speed: reported speed in kt. This is usually speed over ground, but
        might be IAS - you can't tell the difference here, sorry!
    messages: total number of Mode S messages received from this aircraft
    seen: how long ago (in seconds before "now") a message was last received
        from this aircraft
    rssi: recent average RSSI (signal power), in dbFS; this will always be negative.
"""
