# (c) jag.m.singh@gmail.com
"""Shared, lazily-created Google Cloud Storage bucket handle.

Previously both capture_picture.py and create_document.py constructed a new
storage.Client from the service-account JSON on every single upload. This
creates the client once and reuses it.
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
