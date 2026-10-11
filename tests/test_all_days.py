# (c) jag.m.singh@gmail.com
import os
from unittest.mock import MagicMock, patch

import all_days
import get_config


def _blobs(*names):
    blobs = []
    for n in names:
        b = MagicMock()
        b.name = n
        blobs.append(b)
    return blobs


def test_display_date_matches_old_js_format():
    assert all_days.display_date("planes_261011.html") == "Oct 11, 2026"
    assert all_days.display_date("planes_260105.html") == "Jan 05, 2026"


@patch("all_days.gcs")
def test_list_filters_sorts_and_merges_extra(mock_gcs):
    mock_gcs.bucket.return_value.list_blobs.return_value = _blobs(
        "planes_260712.html",
        "planes_261010.html",
        "planes_notes.txt",        # wrong extension
        "planes_2610.html",        # wrong length
    )
    names = all_days.list_daily_files(extra=["planes_261011.html"])
    assert names == ["planes_261011.html", "planes_261010.html",
                     "planes_260712.html"]
    mock_gcs.bucket.return_value.list_blobs.assert_called_with(prefix="planes_")


def test_render_is_static_and_skips_invalid_dates():
    html = all_days.render(["planes_261011.html", "planes_261399.html"])
    assert "<script" not in html
    assert ('<li><a href="planes_261011.html">'
            "Oct 11, 2026</a></li>") in html
    assert "http://" not in html
    assert "planes_261399" not in html


@patch("all_days.gcs")
def test_rebuild_writes_and_uploads(mock_gcs):
    mock_gcs.bucket.return_value.list_blobs.return_value = _blobs(
        "planes_261010.html")
    all_days.rebuild(extra=["planes_261011.html"])

    path = os.path.join(get_config.log_dir, "all_days.html")
    content = open(path).read()
    assert content.index("Oct 11, 2026") < content.index("Oct 10, 2026")

    mock_gcs.bucket.return_value.blob.assert_called_with("all_days.html")
    upload = mock_gcs.bucket.return_value.blob.return_value.upload_from_filename
    upload.assert_called_once_with(path, content_type="text/html")
    assert mock_gcs.bucket.return_value.blob.return_value.cache_control == "no-cache"
