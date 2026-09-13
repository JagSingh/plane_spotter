# (c) jag.m.singh@gmail.com
import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import create_document
import get_config


@patch("create_document.gcs")
@patch("create_document.requests.get")
def test_update_html_file_creates_and_appends(mock_get, mock_gcs):
    mock_get.return_value = MagicMock(
        status_code=200, json=lambda: {"Type": "MD-11 F"},
        raise_for_status=lambda: None)

    capture_time = datetime(2026, 7, 12, 15, 30, 45)
    data = {"hex": "a0cbdb", "flight": "EJM108", "altitude": 3025,
            "speed": 144, "vert_rate": -1024}

    create_document.update_html_file(capture_time, data, "20260712153045.jpg")

    file_path = os.path.join(get_config.log_dir, "planes_260712.html")
    assert os.path.exists(file_path)
    content = open(file_path).read()
    assert "<!DOCTYPE html>" in content
    assert "MD-11 F" in content
    assert "20260712153045.jpg" in content

    # second sighting the same day appends without re-writing the header
    create_document.update_html_file(capture_time, data, "20260712160000.jpg")
    content = open(file_path).read()
    assert content.count("<!DOCTYPE html>") == 1
    assert "20260712160000.jpg" in content

    # hexdb call carries a timeout 
    assert mock_get.call_args.kwargs.get("timeout") is not None
    # The blob name must match the local filename 
    blob = mock_gcs.bucket.return_value.blob
    assert blob.call_count == 2          # one upload per sighting
    blob.assert_called_with("planes_260712.html")


@patch("create_document.requests.get")
def test_hexdb_network_failure_is_distinguishable(mock_get):
    import requests as real_requests
    mock_get.side_effect = real_requests.ConnectionError("down")
    assert create_document.lookup_aircraft_type("deadbe") == "lookup failed"


@patch("create_document.requests.get")
def test_hexdb_404_is_not_found(mock_get):
    mock_get.return_value = MagicMock(status_code=404)
    assert create_document.lookup_aircraft_type("deadbe") == "not found"


@patch("create_document.requests.get")
def test_hexdb_record_without_type_is_unlisted(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200, json=lambda: {"Registration": "N123AB"},
        raise_for_status=lambda: None)
    assert create_document.lookup_aircraft_type("deadbe") == "unlisted"


@patch("create_document.requests.get")
def test_hexdb_empty_type_string_is_unlisted(mock_get):
    """hexdb returns "" for some records; .get(key, default) would not
    catch that, so the code uses `or`."""
    mock_get.return_value = MagicMock(
        status_code=200, json=lambda: {"Type": ""},
        raise_for_status=lambda: None)
    assert create_document.lookup_aircraft_type("deadbe") == "unlisted"
