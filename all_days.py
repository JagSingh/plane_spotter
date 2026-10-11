# (c) jag.m.singh@gmail.com
"""Build the static All Days index page (all_days.html).

Replaces the client-side JavaScript that listed the bucket in the browser.
Called once a day by create_document.update_html_file() when the day's
planes_YYMMDD.html is first created; can also be run manually to rebuild:

    python all_days.py
"""

import logging
import os
import re
from datetime import datetime

import gcs
import get_config

logger = logging.getLogger(__name__)

ALL_DAYS_FILENAME = "all_days.html"
DAILY_PREFIX = "planes_"
DAILY_NAME_RE = re.compile(r"^planes_(\d{6})\.html$")
DAILY_BASE_URL = "http://planes.jagmsingh.com/"

_PAGE_HEAD = """<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <title>Jag Singh</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://jagmsingh.com/style.css">
    <style>
        ul {
            columns: 3;
            list-style-type: none;
        }
    </style>
</head>

<body>
    <header>
        <h3>Plane Spotter: All Days</h3>
        <p>by Jag Singh</p>
    </header>
    <nav>
        <a href="https://jagmsingh.com">Home</a> : <a
            href="https://jagmsingh.com/Plane Spotter/Plane Spotter.html">About Plane Spotter</a> : All Days
    </nav>
    <main>
        <ul id="planes-list">
"""

_PAGE_TAIL = """        </ul>
    </main>
    <footer>
        <p>&copy; <a href="mailto:jag.m.singh@gmail.com">jag.m.singh@gmail.com</a></p>
    </footer>
</body>

</html>
"""


def list_daily_files(extra=()):
    """Names of daily pages in the bucket, newest first.

    `extra` lets the caller include a file it has just uploaded, so the
    listing never depends on read-after-write timing.
    """
    names = {blob.name for blob in gcs.bucket().list_blobs(prefix=DAILY_PREFIX)}
    names.update(extra)
    daily = []
    for name in names:
        if DAILY_NAME_RE.match(name):
            daily.append(name)
        else:
            logger.debug("Skipping non-daily object %s", name)
    # YYMMDD sorts chronologically as a string (valid through 2099).
    return sorted(daily, reverse=True)


def display_date(name):
    """planes_261011.html -> 'Oct 11, 2026' (same format as the old JS)."""
    yymmdd = DAILY_NAME_RE.match(name).group(1)
    return datetime.strptime(yymmdd, "%y%m%d").strftime("%b %d, %Y")


def render(daily_names):
    items = []
    for name in daily_names:
        try:
            label = display_date(name)
        except ValueError:  # e.g. planes_261399.html, not a real date
            logger.warning("Skipping daily file with invalid date: %s", name)
            continue
        items.append(
            f'            <li><a href="{DAILY_BASE_URL}{name}">{label}</a></li>\n'
        )
    return _PAGE_HEAD + "".join(items) + _PAGE_TAIL


def rebuild(extra=()):
    """Regenerate all_days.html locally and upload it to the bucket."""
    daily_names = list_daily_files(extra)
    file_path = os.path.join(get_config.log_dir, ALL_DAYS_FILENAME)
    with open(file_path, "w") as file:
        file.write(render(daily_names))
    gcs.bucket().blob(ALL_DAYS_FILENAME).upload_from_filename(
        file_path, content_type="text/html"
    )
    logger.info("Rebuilt %s with %d days", ALL_DAYS_FILENAME, len(daily_names))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    rebuild()
