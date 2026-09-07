# (c) jag.m.singh@gmail.com
"""The client is created once - global - when the process starts
and is used by both capture_picture.py and create_document.py 
"""

import get_config

_bucket = None

def bucket():
    global _bucket
    if _bucket is None:
        from google.cloud import storage
        _bucket = storage.Client.from_service_account_json(
            get_config.credentials_file
        ).bucket(get_config.bucket_name)
    return _bucket
