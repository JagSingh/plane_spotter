import datetime
import get_config
import json
import time
import capture_picture

previous_monitored_aircraft_hex = []
new_monitored_aircraft_hex = []
cst_time = datetime.datetime.now()

while True:
    try:
        with open(get_config.dump1090_file, "r") as file:
            dump1090_json = file.read()
        # Convert the JSON content to a dictionary
        dump1090_dict = json.loads(dump1090_json)
        # Get the value of the first key "now"
        if "now" in dump1090_dict:
            unix_epoch_seconds = dump1090_dict["now"]
            # Convert to CST (Central Standard Time)
            cst_time = datetime.datetime.fromtimestamp(unix_epoch_seconds).replace(microsecond=0)
        else:
            print("Key 'now' not found in the aircraft.json file.")
        if "aircraft" in dump1090_dict:
            current_monitored_aircraft_hex = [
                aircraft["hex"] for aircraft in dump1090_dict["aircraft"]
                if "lat" in aircraft and "lon" in aircraft and "altitude" in aircraft and
                   get_config.monitored_space["lower_lat"] <= aircraft["lat"] <= get_config.monitored_space["upper_lat"] and
                   get_config.monitored_space["lower_lon"] <= aircraft["lon"] <= get_config.monitored_space["upper_lon"] and
                   get_config.monitored_space["lower_altitude"] <= aircraft["altitude"] <= get_config.monitored_space["upper_altitude"]
            ]
        else:
            print("Key 'aircraft' not found in dump_1090.")
        # hopefully the plane is not going in circles
        new_monitored_aircraft_hex = list(set(current_monitored_aircraft_hex) - set(previous_monitored_aircraft_hex))
        if new_monitored_aircraft_hex:
            previous_monitored_aircraft_hex = current_monitored_aircraft_hex
            print(f"CST Time: {cst_time}, New aircraft in monitored space: {new_monitored_aircraft_hex}")
            # the list should contain only one dictionary for the new_monitored_aircraft_hex, get the first one [0]
            # maybe, the current_monitored_aircraft_hex should not even be a list, but a scalar. oh well..
            monitored_aircraft_data = [
                aircraft for aircraft in dump1090_dict["aircraft"]
                if aircraft["hex"] in new_monitored_aircraft_hex
            ][0] 
            print(f"Monitored aircraft details: {monitored_aircraft_data}")
            capture_picture.detect_and_upload_airplane(cst_time, monitored_aircraft_data)

    except FileNotFoundError:
        print(f"The file '{get_config.dump1090_file}' does not exist.")
    except Exception as e:
        print(f"An error occurred: {e}")
    
    # Wait for 5 seconds before the next iteration
    time.sleep(5)

"""
Setup hardware drivers and software 

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