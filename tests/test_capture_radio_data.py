# (c) jag.m.singh@gmail.com
import json
from unittest.mock import patch

import capture_radio_data
import get_config


def _write_adsb(aircraft, now=1750000000):
    with open(get_config.adsb_file, "w") as f:
        json.dump({"now": now, "aircraft": aircraft}, f)


# readsb schema: alt_baro, gs, baro_rate
IN_SPACE = {"hex": "a0cbdb", "lat": 33.1, "lon": -97.1, "alt_baro": 3000,
            "gs": 142.3, "baro_rate": -704, "flight": "EJM108  ",
            "type": "adsb_icao"}
OUT_OF_SPACE = {"hex": "ffffff", "lat": 40.0, "lon": -97.1, "alt_baro": 3000}
ON_GROUND = {"hex": "eeeeee", "lat": 33.1, "lon": -97.1, "alt_baro": "ground"}


@patch("capture_radio_data.capture_picture")
def test_new_aircraft_in_space_triggers_capture(mock_capture):
    _write_adsb([IN_SPACE, OUT_OF_SPACE, ON_GROUND])
    previous = []
    capture_radio_data.poll_once(previous)
    mock_capture.detect_and_upload_airplane.assert_called_once()
    args = mock_capture.detect_and_upload_airplane.call_args[0]
    assert args[1]["hex"] == "a0cbdb"
    assert previous == ["a0cbdb"]


@patch("capture_radio_data.capture_picture")
def test_same_aircraft_not_captured_twice(mock_capture):
    _write_adsb([IN_SPACE])
    previous = ["a0cbdb"]
    capture_radio_data.poll_once(previous)
    mock_capture.detect_and_upload_airplane.assert_not_called()


@patch("capture_radio_data.capture_picture")
def test_position_dropout_does_not_recapture_same_plane(mock_capture):
    """ADS-B position can drop out for a poll (weak signal) and return.
    State is retained across the gap so the same plane isn't captured twice."""
    _write_adsb([IN_SPACE])
    previous = []
    capture_radio_data.poll_once(previous)
    assert mock_capture.detect_and_upload_airplane.call_count == 1

    no_pos = {"hex": "a0cbdb", "flight": "EJM108"}
    _write_adsb([no_pos])
    capture_radio_data.poll_once(previous)

    _write_adsb([IN_SPACE])
    capture_radio_data.poll_once(previous)
    assert mock_capture.detect_and_upload_airplane.call_count == 1


@patch("capture_radio_data.capture_picture")
def test_two_new_aircraft_single_capture_first_attributed(mock_capture):
    """Two new hexes in one window (box misconfiguration case): exactly one
    capture, attributed to the first aircraft in the aircraft list."""
    second = dict(IN_SPACE, hex="b1b1b1", alt_baro=1500)
    _write_adsb([IN_SPACE, second])
    capture_radio_data.poll_once([])
    assert mock_capture.detect_and_upload_airplane.call_count == 1
    args = mock_capture.detect_and_upload_airplane.call_args[0]
    assert args[1]["hex"] == "a0cbdb"


@patch("capture_radio_data.capture_picture")
def test_missing_aircraft_key_is_fatal(mock_capture):
    """readsb always writes 'aircraft'; its absence means the ADS-B dump
    process is down — exit so Docker's restart policy makes it visible."""
    with open(get_config.adsb_file, "w") as f:
        json.dump({"now": 1750000000}, f)
    exited = False
    try:
        capture_radio_data.poll_once([])
    except SystemExit:
        exited = True
    assert exited, "expected SystemExit when 'aircraft' key is missing"
    mock_capture.detect_and_upload_airplane.assert_not_called()


@patch("capture_radio_data.capture_picture")
def test_geometric_altitude_alone_does_not_trigger(mock_capture):
    """alt_geom (GNSS height) is not the barometric altitude the box is
    defined in; an aircraft with only alt_geom must not match."""
    geom_only = {"hex": "c2c2c2", "lat": 33.1, "lon": -97.1, "alt_geom": 3000}
    _write_adsb([geom_only])
    capture_radio_data.poll_once([])
    mock_capture.detect_and_upload_airplane.assert_not_called()



@patch("capture_radio_data.time.sleep")
@patch("capture_radio_data.time.monotonic")
@patch("capture_radio_data.poll_once", side_effect=FileNotFoundError)
def test_missing_file_exits_after_timeout(_poll, mock_clock, _sleep):
    """A stale /run/readsb bind mount never recovers on its own; after
    MISSING_FILE_EXIT_SECONDS the loop exits so Docker remounts it."""
    limit = capture_radio_data.MISSING_FILE_EXIT_SECONDS
    mock_clock.side_effect = [0, limit / 2, limit]
    exited = False
    try:
        capture_radio_data.main()
    except SystemExit:
        exited = True
    assert exited
    assert mock_clock.call_count == 3


@patch("capture_radio_data.time.sleep")
@patch("capture_radio_data.time.monotonic")
def test_missing_file_timer_resets_on_success(mock_clock, _sleep):
    """A brief gap (normal readsb restart) must not accumulate toward exit."""
    limit = capture_radio_data.MISSING_FILE_EXIT_SECONDS
    outcomes = iter([FileNotFoundError, None, FileNotFoundError,
                     KeyboardInterrupt])

    def fake_poll(_prev):
        exc = next(outcomes)
        if exc:
            raise exc
    mock_clock.side_effect = [0, limit + 1]
    with patch("capture_radio_data.poll_once", side_effect=fake_poll):
        try:
            capture_radio_data.main()
        except KeyboardInterrupt:
            pass  # loop survived the second miss: timer had reset
