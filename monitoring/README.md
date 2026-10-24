# plane_spotter monitoring

Three checks, alerting through Healthchecks.io. Two read the container's log on the production
host. One checks the published site from a second, independent machine. After each run the scripts
ping a Healthchecks check: a normal ping when the check passes, `/fail` when it fails. If a ping
arrives late or not at all (host down, cron stopped, home internet down), Healthchecks alerts on
that too.

## Hosts

| Role | What it is | Runs |
|---|---|---|
| **prod-primary** | The machine running the plane_spotter container | `install-prod-primary.sh` |
| **monitor-secondary** | Any other always-on Linux machine; it must not be prod-primary | `install-monitor-secondary.sh` |

monitor-secondary checks the published site from outside the production machine. If prod-primary
dies, monitor-secondary still reports that the page is missing, rather than everything just going
quiet at once.

## The checks

| Check | Host | Runs at (Chicago time) | Passes when |
|---|---|---|---|
| `ps-adsb` | prod-primary | 12:00, 16:00 | the log shows `New aircraft in monitored space` in the last 4 h |
| `ps-photo` | prod-primary | 12:00, 16:00 | the log shows `create_document: Airplane data` in the last 4 h |
| `ps-page` | monitor-secondary | 12:00 | `https://planes.jagmsingh.com/planes_YYMMDD.html` for today returns HTTP 200 |

The two log checks each look back 4 hours, so together they cover 08:00-16:00. That window is in
daylight in Dallas all year (latest sunrise is about 07:45, earliest sunset about 17:20), so the
camera check never runs against a stretch of darkness.

## What an alert means

| Alert | Likely cause | First thing to look at |
|---|---|---|
| `ps-adsb` | No ADS-B traffic is reaching plane_spotter | `systemctl status readsb`, the RTL-SDR on USB (`lsusb`, `dmesg \| tail`), any remote receiver feed, the container |
| `ps-photo` (with `ps-adsb` passing) | Aircraft are seen but nothing gets photographed | Camera on USB, `capture_picture` lines in the log, detection step |
| `ps-page` (with `ps-photo` passing) | Photos are made locally but not published | GCS upload or credentials, errors after `create_document` |
| `ps-adsb` and `ps-photo` both **"no ping"** (late) | prod-primary or its cron didn't run | Is the host up, is cron running |
| Every check **"no ping"** | Home internet or power is down | Router, power |

## Setup

### 1. Healthchecks.io

Create three checks, all with:

- **Type:** Cron
- **Timezone:** America/Chicago
- **Grace:** 1 hour

| Check | Schedule |
|---|---|
| `ps-adsb` | `0 12,16 * * *` |
| `ps-photo` | `0 12,16 * * *` |
| `ps-page` | `0 12 * * *` |

A schedule like `0 12,16 * * *` means minute 0, hours 12 and 16, every day.

Add a notification channel under Integrations (email, Pushover, ntfy, Slack and so on). Copy each
check's ping URL; the UUID is the part after `https://hc-ping.com/`.

### 2. prod-primary

```bash
cd monitoring
./install-prod-primary.sh            # first run creates ~/monitoring/plane-spotter/monitoring.env and stops
nano ~/monitoring/plane-spotter/monitoring.env # set PS_CONTAINER (see `docker ps`), HC_PS_ADSB, HC_PS_PHOTO
./install-prod-primary.sh --test     # installs and runs the checks once right away
```

The installer checks that your user can run `docker` and that the container exists. It writes
`~/monitoring/plane-spotter/monitor-primary.sh` and adds one cron line. Any other cron jobs are left as
they are, and it is safe to rerun.

### 3. monitor-secondary

```bash
cd monitoring
./install-monitor-secondary.sh            # installs cron + curl if missing, creates ~/monitoring/plane-spotter/monitoring.env, stops
nano ~/monitoring/plane-spotter/monitoring.env      # set HC_PS_PAGE
./install-monitor-secondary.sh --test
```

### Installed files

Each project gets one visible folder on each host, outside the git checkout:

```
~/monitoring/plane-spotter/
  monitor-primary.sh     (prod-primary) or monitor-secondary.sh (monitor-secondary)
  monitoring.env         UUIDs and settings (mode 600; not in git)
  monitoring.log         one line per check per run
```

The cron line is tagged `# plane-spotter-monitor-…`. Cron runs the script from this folder, so you can
delete, re-clone or switch branches in the repo without affecting monitoring. Other projects use
their own folders under `~/monitoring/`, so they don't conflict.

To install somewhere else, set `MON_DIR` when running the installer, e.g.
`MON_DIR=~/ops/plane-spotter ./install-prod-primary.sh`. Use the same `MON_DIR` each time you rerun it.

### How scheduling works

Cron runs the check script every hour on the hour. The script checks the time in Chicago and exits
unless the hour is a scheduled one. This means the machine's own timezone setting doesn't matter;
a host left on UTC works fine.

## Testing

### Test 1: everything passes and the pings arrive

Run during daylight:

```bash
# prod-primary
./install-prod-primary.sh --test
#   ... ps-adsb ok: N x 'New aircraft in monitored space' in last 4h
#   ... ps-photo ok: N x 'create_document: Airplane data' in last 4h

# monitor-secondary
./install-monitor-secondary.sh --test
#   ... ps-page ok: planes_YYMMDD.html HTTP 200
```

**Pass if:** all three checks show green in Healthchecks, and the ping body shows the same message.

### Test 2: alerts actually reach you

This sends real alerts.

```bash
# prod-primary: report both checks as failed
FORCE=1 FORCE_FAIL=1 ~/monitoring/plane-spotter/monitor-primary.sh
```

**Pass if:** you receive the `ps-adsb` and `ps-photo` alerts within about a minute.

Then restore with `FORCE=1 ~/monitoring/plane-spotter/monitor-primary.sh`. You should receive a recovery
notice.

### Test 3: the time gate

```bash
~/monitoring/plane-spotter/monitor-primary.sh; echo "exit=$?"   # outside 12:00/16:00: no output, exit=0, no ping
```

### Test 4: cron is firing

After the next scheduled run:

```bash
tail ~/monitoring/plane-spotter/monitoring.log
```

## Running it

| Task | Command |
|---|---|
| Recent results | `tail -20 ~/monitoring/plane-spotter/monitoring.log` |
| Run checks now | `FORCE=1 ~/monitoring/plane-spotter/monitor-primary.sh` (or `monitor-secondary.sh`) |
| Change UUIDs or container | Edit `~/monitoring/plane-spotter/monitoring.env`. The next run uses it; no reinstall needed. |
| Change run hours or window | Set `RUN_HOURS="10 14"` or `WINDOW=2h` in the env file, then update the Healthchecks schedule to match |

If one machine is both prod-primary and monitor-secondary, both installers share
`~/monitoring/plane-spotter/monitoring.env`. The second installer will report which variable is missing; add
it to the file and rerun.

## Known limits

- **The log checks depend on log text.** If the log messages are reworded, update the strings in
  `install-prod-primary.sh` and rerun it.
- **The logs go to stderr.** plane_spotter logs with Python `logging`, which writes to stderr. The
  script reads both stdout and stderr (`2>&1`); without that, every log check would count 0.
- **`ps-page` only checks that today's page exists,** not whether it has new entries. `ps-photo`
  covers freshness.

## Test results before delivery

The scripts were run in a sandbox using stand-in versions of `docker`, `curl` and `crontab`, with
real plane_spotter log lines as input:

- **Bash syntax:** both installers pass.
- **First run:** creates `~/monitoring/plane-spotter/monitoring.env` with mode 600 and stops. An empty UUID, an unknown container
  name, or no Docker permission each stops the install with a clear error.
- **Passing run:** the sample log gives `ps-adsb` 2 matches and `ps-photo` 1 match. Today's page
  returns 200, so `ps-page` passes. Success pings are sent for all three.
- **Failure runs:** each of these sent the matching `/fail` ping:
  - no `create_document` line in the log
  - a missing container
  - today's page returning 404
- **Time gate:** outside the run hours, no pings are sent.
- **Alongside double-scramble-live's monitoring on the same host:** the env files, scripts, logs
  and cron lines are all separate. An unrelated existing cron job survives every install.
- **Install folder:** cron runs the script from another working directory and it still finds
  `monitoring.env` next to itself. `MON_DIR` moves the folder.

- **Alert test switch:** `FORCE_FAIL=1` sends `/fail` for every check on both hosts, even when the
  real checks would pass. The env file can't override it.
- **Not tested here:** the real Docker, the planes site and Healthchecks. Tests 1-2 above cover
  that on the actual machines.
