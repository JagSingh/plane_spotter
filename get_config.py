# read values from the config file
# This is a sample configuration file for the Plane Spotter application.
# config = {
#     "dump1090_file": "/var/run/dump1090-mutability/aircraft.json",
#     "monitored_space": {
#         "lower_lat": NN.NN,
#         "upper_lat": NN.NN,
#         "lower_lon": NN.NN,
#         "upper_lon": NN.NN,
#         "lower_altitude": N000,
#         "upper_altitude": N000,
#     },
#     "log_dir": "/path/to/logs",
#     "credentials_file": "/path/to/service-account-key.json",
#     "bucket_name": "bucket-name",
#     }
# }

# print("Reading configuration file...")

import json
import os
config_file = os.path.expanduser("~/.config/plane_spotter.json")

with open(config_file, "r") as file:
    config_json = file.read()

global monitored_space, dump1090_file, log_dir, credentials_file, bucket_name
config_dict = json.loads(config_json) # Convert the JSON content to a dictionary
monitored_space = config_dict.get("monitored_space", {})
dump1090_file = config_dict.get("dump1090_file", "")
log_dir = os.path.expanduser(config_dict.get("log_dir", ""))
credentials_file = os.path.expanduser(config_dict.get("credentials_file", ""))
bucket_name = config_dict.get("bucket_name", "")
