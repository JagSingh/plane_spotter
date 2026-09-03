# (c) jag.m.singh@gmail.com
import get_config


def test_config_loads_expected_values():
    assert get_config.bucket_name == "test-bucket"
    assert get_config.monitored_space["lower_lat"] == 33.0
    assert get_config.poll_interval == 0
    assert get_config.show_preview is False  # headless default
