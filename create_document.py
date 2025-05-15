import os
from datetime import datetime
import get_config
from google.cloud import storage
import requests


def update_html_file(capture_time, airplane_data, airplane_picture):

    # Generate the filename (planes_date) based on the capture time
    filename = f"planes_{capture_time.strftime("%y%m%d")}.html"
    file_path = os.path.join(get_config.log_dir, filename)

    aircraft_hex = airplane_data.get("hex", "unknown")    

    # Fetch the aircraft type from the API
    try:
        response = requests.get(f"https://hexdb.io/api/v1/aircraft/{aircraft_hex}")
        response.raise_for_status()
        aircraft_info = response.json()
        aircraft_type = aircraft_info.get("Type", "unknown")
    except requests.RequestException as e:
        print(f"Error fetching aircraft type: {e}")
        aircraft_type = "unknown"

    print_airplane_data = (
        f'Aircraft: {aircraft_hex} | '
        f'Type: {aircraft_type} | '
        f'Flight: {airplane_data.get("flight", "unknown")} | '
        f'Altitude: {airplane_data.get("altitude", "unknown")} feet | '
        f'Speed: {airplane_data.get("speed", "unknown")} knots | '
        f'Vertical Speed: {airplane_data.get("vert_rate", "unknown")} feet/min'
    )
    print(f"Airplane data: {print_airplane_data}")

    # Create one html for each day. Check if the file already exists, else create it. The airplane data on GCS is not available till the next day
    if not os.path.exists(file_path):
        previous_day_file = max([f for f in os.listdir(get_config.log_dir) if f.startswith("planes_") and f.endswith(".html")], default=None)
        # not needed anymore, update the file every time a new picture is taken and uploaded
        #if previous_day_file:
        #    print(f"Largest file by name: {previous_day_file}")
        #    bucket = storage.Client.from_service_account_json(get_config.credentials_file).bucket(get_config.bucket_name)
        #    blob = bucket.blob(previous_day_file)
        #    blob.upload_from_filename(os.path.join(get_config.log_dir, previous_day_file))

        with open(file_path, 'w') as file:
            file.write(f'''
                       <!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Plane Spotter</title>
                       <link rel="stylesheet" href="https://jagmsingh.com/style.css">
                       <header><h3>{capture_time.strftime("%B %-d, %Y")}</h3><p>&copy; <a href="mailto:jag.m.singh@gmail.com">jag.m.singh@gmail.com</a></p></header>
                       <nav><a href="https://jagmsingh.com/Plane%20Spotter/Plane%20Spotter.html">About Plane Spotter</a></nav>
                        ''')  # Create a new file for the day
    
    # append the new airplane data to the file
    with open(file_path, 'a') as file:
        content = (
            f'<h4>{capture_time.strftime("%Y-%m-%d %H:%M:%S")}</h4>'
            + print_airplane_data
            + f'<img src="{airplane_picture}" alt="Airplane Picture" /> <hr><p>\n'
        )
        file.write(content)

    # Upload the file to Google Cloud Storage
    bucket = storage.Client.from_service_account_json(get_config.credentials_file).bucket(get_config.bucket_name)
    blob = bucket.blob(filename)
    blob.upload_from_filename(file_path)


if __name__ == "__main__":
    time = datetime.now()
    data = {"hex": "ABC123", "flight": "XYZ456", "altitude": 10000, "speed": 500, "vert_rate": 1000}
    picture = "20250505214149.jpg"
    update_html_file(time, data, picture)

"""
aircraft.json
This file contains dump1090's list of recently seen aircraft. The keys are:
now: the time this file was generated, in seconds since Jan 1 1970 00:00:00 GMT (the Unix epoch).
messages: the total number of Mode S messages processed since dump1090 started.
aircraft: an array of JSON objects, one per known aircraft. Each aircraft has the following keys. Keys will be omitted if data is not available.
    hex: the 24-bit ICAO identifier of the aircraft, as 6 hex digits. The identifier may start with '~', this means that the address is a non-ICAO address (e.g. from TIS-B).
    squawk: the 4-digit squawk (octal representation)
    flight: the flight name / callsign
    lat, lon: the aircraft position in decimal degrees
    nucp: the NUCp (navigational uncertainty category) reported for the position
    seen_pos: how long ago (in seconds before "now") the position was last updated
    altitude: the aircraft altitude in feet, or "ground" if it is reporting it is on the ground
    vert_rate: vertical rate in feet/minute
    track: true track over ground in degrees (0-359)
    speed: reported speed in kt. This is usually speed over ground, but might be IAS - you can't tell the difference here, sorry!
    messages: total number of Mode S messages received from this aircraft
    seen: how long ago (in seconds before "now") a message was last received from this aircraft
    rssi: recent average RSSI (signal power), in dbFS; this will always be negative.
"""
