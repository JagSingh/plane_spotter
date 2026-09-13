# (c) jag.m.singh@gmail.com
import json
from unittest.mock import patch

import capture_radio_data
import get_config


def _write_dump1090(aircraft, now=1750000000):
    with open(get_config.dump1090_file, "w") as f:
        json.dump({"now": now, "aircraft": aircraft}, f)


IN_SPACE = {"hex": "a0cbdb", "lat": 33.1, "lon": -97.1, "altitude": 3000,
            "flight": "EJM108"}
OUT_OF_SPACE = {"hex": "ffffff", "lat": 40.0, "lon": -97.1, "altitude": 3000}
ON_GROUND = {"hex": "eeeeee", "lat": 33.1, "lon": -97.1, "altitude": "ground"}


@patch("capture_radio_data.capture_picture")
def test_new_aircraft_in_space_triggers_capture(mock_capture):
    _write_dump1090([IN_SPACE, OUT_OF_SPACE, ON_GROUND])
    previous = []
    capture_radio_data.poll_once(previous)
    mock_capture.detect_and_upload_airplane.assert_called_once()
    args = mock_capture.detect_and_upload_airplane.call_args[0]
    assert args[1]["hex"] == "a0cbdb"
    assert previous == ["a0cbdb"]


@patch("capture_radio_data.capture_picture")
def test_same_aircraft_not_captured_twice(mock_capture):
    _write_dump1090([IN_SPACE])
    previous = ["a0cbdb"]
    capture_radio_data.poll_once(previous)
    mock_capture.detect_and_upload_airplane.assert_not_called()


@patch("capture_radio_data.capture_picture")
def test_position_dropout_does_not_recapture_same_plane(mock_capture):
    """ADS-B position can drop out for a poll (weak signal) and return.
    State is retained across the gap so the same plane isn't captured twice."""
    _write_dump1090([IN_SPACE])
    previous = []
    capture_radio_data.poll_once(previous)
    assert mock_capture.detect_and_upload_airplane.call_count == 1

    no_pos = {"hex": "a0cbdb", "flight": "EJM108"}
    _write_dump1090([no_pos])
    capture_radio_data.poll_once(previous)

    _write_dump1090([IN_SPACE])
    capture_radio_data.poll_once(previous)
    assert mock_capture.detect_and_upload_airplane.call_count == 1


@patch("capture_radio_data.capture_picture")
def test_two_new_aircraft_single_capture_first_attributed(mock_capture):
    """Two new hexes in one window (box misconfiguration case): exactly one
    capture, attributed to the first aircraft in the dump1090 list."""
    second = dict(IN_SPACE, hex="b1b1b1", altitude=1500)
    _write_dump1090([IN_SPACE, second])
    capture_radio_data.poll_once([])
    assert mock_capture.detect_and_upload_airplane.call_count == 1
    args = mock_capture.detect_and_upload_airplane.call_args[0]
    assert args[1]["hex"] == "a0cbdb"


@patch("capture_radio_data.capture_picture")
def test_missing_aircraft_key_is_fatal(mock_capture):
    """dump1090 always writes 'aircraft'; its absence means the ADS-B dump
    process is down — exit so Docker's restart policy makes it visible."""
    with open(get_config.dump1090_file, "w") as f:
        json.dump({"now": 1750000000}, f)
    exited = False
    try:
        capture_radio_data.poll_once([])
    except SystemExit:
        exited = True
    assert exited, "expected SystemExit when 'aircraft' key is missing"
    mock_capture.detect_and_upload_airplane.assert_not_called()
