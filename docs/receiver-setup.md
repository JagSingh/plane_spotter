# Receiver setup: north laptop and south Chromebook

plane_spotter does not talk to the radio. It only reads
`/run/readsb/aircraft.json`, which readsb writes on the **host**. This document
covers how that file gets produced: the two ADS-B receivers, readsb on each,
the feed between them, and gain tuning.

> **Why two antennas.** The setup uses two indoor antennas, one at a north
> window and one at a south window, in lieu of climbing onto the roof to install
> an outdoor antenna and a gas-discharge tube (GDT) lightning arrestor. readsb
> on the north laptop merges the two into a single feed. The cost is a second
> receiver and the Chromebook's uptime caveats (§6.6).

| Name used here | Machine | LAN IP |
|---|---|---|
| **North laptop** | Production laptop, antenna at the north window | 192.168.86.137 |
| **South Chromebook** | Chromebook (Crostini Linux), antenna at the south window | 192.168.86.218 |


```
 South Chromebook (south window)        North laptop (north window, production)
 ┌─────────────────────────────┐         ┌──────────────────────────────────────────┐
 │ RTL2832U + window antenna   │  Beast  │ Pro Stick Plus + window antenna (local)  │
 │ readsb  --net-connector     │ ──────▶ │ readsb  :30004 beast-in                  │
 │ readsb-up.sh --watch        │   TCP   │   └─ merges local + remote               │
 │                             │  30004  │ /run/readsb/aircraft.json                │
 └─────────────────────────────┘         │   ├─ plane_spotter (Docker, ro mount)    │
  192.168.86.218                         │   └─ double-scramble-live                │
                                         └──────────────────────────────────────────┘
                                          192.168.86.137
```

| | North laptop | South Chromebook |
|---|---|---|
| Role | Production. Merges both feeds; consumers read here | Second antenna. Pushes to the north laptop |
| Receiver | FlightAware Pro Stick Plus, `0bda:2832` | RTL2832U dongle (`0bda:2832` or `0bda:2838`) |
| Gain | readsb autogain | Fixed 36.4 (set by `readsb-up.sh`) |
| readsb runs as | Packaged systemd service | Packaged service, supervised by `readsb-up.service` |
| Recovery | systemd restart policy + container restart | `readsb-up.sh --watch` (replug, stall, USB reset) |

Contents

1. [North laptop: receiver hardware](#1-north-laptop-receiver-hardware)
2. [North laptop: drivers and udev](#2-north-laptop-drivers-and-udev)
3. [North laptop: readsb](#3-north-laptop-readsb)
4. [North laptop: accept the south Chromebook feed](#4-north-laptop-accept-the-south-chromebook-feed)
5. [Gain tuning](#5-gain-tuning)
6. [South Chromebook (Crostini)](#6-south-chromebook-crostini)
7. [Verification and monitoring](#7-verification-and-monitoring)
8. [Troubleshooting](#8-troubleshooting)
9. [History](#9-history)

---

## 1. North laptop: receiver hardware

**FlightAware Pro Stick Plus.** It has an RTL2832U and an R820T2 tuner, plus a
built-in 1090 MHz SAW filter and LNA. Its USB ID is `0bda:2832`. It replaced the
Nooelec RTL-SDR (`0bda:2838`) on 2026-10-17.

- The LNA takes its power from USB. Do not use a bias-tee, and do not pass
  `--enable-biastee` to readsb.
- Plug it into a laptop root port, not into the USB-C dock. The stick is a USB2 device,
  so it always enumerates on **bus 3** (the
  high-speed companion root hub) and never on bus 4 (SuperSpeed). Check the
  **port path**, not the bus number. A path with no dot has no hub in between:

  ```bash
  for d in /sys/bus/usb/devices/*; do
    [ "$(cat $d/idProduct 2>/dev/null)" = 2832 ] && echo "${d##*/}  $(cat $d/speed) Mb/s"
  done
  # 3-4  480 Mb/s        good: root port, high speed
  # 3-2.1  480 Mb/s      bad:  behind the dock hub
  ```

The HD USB camera has its own setup doc: [camera-setup.md](camera-setup.md).

## 2. North laptop: drivers and udev

readsb and the receiver stay on the **host**. Kernel module blacklisting and
udev rules are host-wide kernel state, so they cannot be set from inside a
container. The container reads `aircraft.json` through a read-only bind mount of
`/run/readsb` (see `docker-compose.yml`).

```bash
sudo apt install rtl-sdr
```

Blacklist the DVB-T TV drivers so they don't claim the stick:

```bash
sudo tee /etc/modprobe.d/rtl-sdr-blacklist.conf >/dev/null <<'EOF'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
blacklist dvb_usb_v2
blacklist dvb_core
EOF
```

Check the stick:

```bash
lsusb | grep -i rtl
# Bus 003 Device 073: ID 0bda:2832 Realtek Semiconductor Corp. RTL2832U DVB-T

rtl_test -t
```

`rtl_test` should find 1 device and report `Found Rafael Micro R820T tuner` (the
R820T2 reports itself as R820T). It should list 29 gain values:

```
0.0 0.9 1.4 2.7 3.7 7.7 8.7 12.5 14.4 15.7 16.6 19.7 20.7 22.9 25.4 28.0 29.7
32.8 33.8 36.4 37.2 38.6 40.2 42.1 43.4 43.9 44.5 48.0 49.6
```

If it prints `usb_claim_interface error`, a DVB module still owns the stick.
Check `lsmod | grep dvb_usb_rtl28xxu` and the blacklist above.

The `rtl-sdr` package's own udev rules already cover both IDs. Add this file only
if those rules are missing. It keeps `2838` so the Nooelec still works as a
spare:

```bash
sudo tee /etc/udev/rules.d/rtl-sdr.rules >/dev/null <<'EOF'
SUBSYSTEMS=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2832", MODE:="0666"
SUBSYSTEMS=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE:="0666"
EOF
sudo udevadm control --reload-rules      # then unplug / replug the stick
```

## 3. North laptop: readsb

Install readsb from wiedehopf. Only one decoder can own the stick:

```bash
sudo bash -c "$(wget -O - https://github.com/wiedehopf/adsb-scripts/raw/master/readsb-install.sh)"
sudo readsb-set-location <antenna latitude> <antenna longitude>
sudo readsb-gain auto                    # see §5
```

Set the receiver location. Without it, readsb has to use global CPR decoding,
which needs a matched pair of even and odd messages before it can report a
position. With a location set, readsb can decode a position from a single
message. Aircraft are acquired sooner, which decides whether they are still in
the camera's view when the capture starts.

Running config (`/etc/default/readsb`):

```
RECEIVER_OPTIONS="--device 0 --device-type rtlsdr --gain auto-verbose --ppm 0"
DECODER_OPTIONS="--lat <lat> --lon <lon> --max-range 450 --write-json-every 1"
NET_OPTIONS="--net --net-ri-port 30001 --net-ro-port 30002 --net-sbs-port 30003 --net-bi-port 30004,30104 --net-bo-port 30005"
JSON_OPTIONS="--json-location-accuracy 2 --range-outline-hours 24"
```

`--device 0` selects the first stick by index, which is fine with only one
stick. If you add a second one, give the stick a serial and select it by
serial, so a change in index order can't swap the two:

```bash
sudo systemctl stop readsb
sudo rtl_eeprom -s 00001090              # then replug
# RECEIVER_OPTIONS="--device 00001090 ..."
```

### systemd drop-in

The packaged unit declares `RuntimeDirectory=readsb` without the preserve
option. systemd therefore deletes and recreates `/run/readsb` on every stop and
start, and both `readsb-gain` and `readsb-set-location` restart the service.
After that, the container's bind mount points at the deleted directory until the
container restarts. This drop-in keeps the directory, and its inode, for the
life of the boot:

```bash
sudo systemctl edit readsb
```
```ini
[Service]
RuntimeDirectoryPreserve=yes
```
```bash
sudo systemctl restart readsb            # readsb: systemd service on the host
docker compose up -d --force-recreate    # plane_spotter container: re-attach its
                                         # /run/readsb bind mount to the stable directory
```

Make sure readsb restarts by itself after a USB drop or re-enumeration:

```bash
systemctl show readsb -p Restart -p RestartUSec
```

The packaged unit ships with `Restart=always` and `RestartSec=15`. If the output
shows `Restart=no`, add `Restart=always` to the same drop-in. Leave `RestartSec`
at 15, because `MISSING_FILE_EXIT_SECONDS` (60 s) in `capture_radio_data.py` is
sized to ride out that delay.

On the container side, `docker-compose.yml` sets `restart: unless-stopped`.
`capture_radio_data.py` exits after 60 s if `aircraft.json` is missing, so Docker
also recovers a stale mount even without the drop-in.

### Live table

Stop the service first, because only one process can open the stick:

```bash
sudo systemctl stop readsb
readsb --device-type rtlsdr --gain auto --interactive
sudo systemctl start readsb
```

## 4. North laptop: accept the south Chromebook feed

The packaged readsb listens for Beast input on `--net-bi-port 30004,30104`.
The south Chromebook connects outbound to the north laptop rather than the north
laptop pulling from it, because Crostini sits behind ChromeOS's NAT.

```bash
sudo ss -ltnp | grep -E ':30004\b'       # LISTEN 0.0.0.0:30004 ... readsb
```

**Firewall: no change was needed.** The packaged readsb listens on all
interfaces, and the south Chromebook connected on the first attempt
(2026-10-10) with no firewall rule added. If the connection is ever refused,
test it from the Chromebook first:

```bash
timeout 3 bash -c '</dev/tcp/192.168.86.137/30004' && echo open || echo blocked
```

Only if it prints `blocked`, check the north laptop's firewall. Add a rule only
when ufw reports `active`:

```bash
sudo ufw status
sudo ufw allow from 192.168.86.218 to any port 30004 proto tcp
```

- `192.168.86.218` is the Chromebook's LAN address, not the Crostini container's
  internal `100.115.92.x` address, because ChromeOS translates the container's
  traffic. Reserve `.218` in the Google Home app so the feed target and any
  future firewall rule stay valid.
- The feed goes to port **30004** (Beast in), not 30005 (Beast out).
- plane_spotter and double-scramble-live need no changes. readsb merges both
  feeds per aircraft into one `aircraft.json`, without duplicates.

## 5. Gain tuning

### Production: readsb autogain

Use `auto` or `auto-verbose`, which is the installer default. The Pro Stick
Plus's LNA adds roughly 15–19 dB in front of the tuner, so the Nooelec's fixed
29.7 does not carry over. Autogain finds the operating point and tracks traffic
through the day.

This is readsb's own software loop. It is not the R820T2's hardware AGC (gain
`-10` on old builds), which is tuned for broadcast signals and hurts bursty
ADS-B. Never use `58`, the special maximum-gain value: it overloads a stick that
has an LNA.

### Comparisons: pin the gain

Autogain changes the gain in the middle of a measurement window. For any A/B
test (receiver, antenna, feed on/off), pin the value autogain settled on, run the
test, then switch back to auto:

```bash
jq .gain_db /run/readsb/stats.json       # top-level field, not under .local
sudo readsb-gain <that value>
# ... measure ...
sudo readsb-gain auto
```

### Health target

`strong_signals` should be **1–5 %** of accepted messages. Above 5 % the gain is
too high, and autogain should step it down. Below 1 % there is headroom.

```bash
jq '{gain: .gain_db} + (.last15min | {secs: (.end - .start),
      local: (.local.accepted|add), remote: (.remote.accepted|add),
      strong_pct: (.local.strong_signals / (.local.accepted|add) * 100),
      ratio: ((.remote.accepted|add) / (.local.accepted|add))})' \
   /run/readsb/stats.json
```

- `accepted` is an array of `[0-bit, 1-bit-corrected]` counts; sum both.
- `remote` is the south Chromebook feed. It works as the reference when you change
  anything on the north laptop, because it is unaffected. Compare the **ratio**, not raw
  counts, since traffic varies by hour.
- Judge on a full window (`secs` ≈ 900). The window right after a readsb
  restart is short and still includes autogain converging.

### Optional manual sweep

Use this to cross-check autogain's choice:

1. Run `sudo readsb-set-location <lat> <lon>` if the location is not set yet.
2. For each gain in 40.2, 36.4, 29.7, 25.4, 22.9:
   ```bash
   sudo readsb-gain <gain>               # restarts readsb
   sleep 360                             # let the 5-minute window fill
   python3 -c "
   import json
   s=json.load(open('/run/readsb/stats.json'))['last5min']['local']
   print(sum(s['accepted'])/5, round(100*s['bad']/s['modes'],1))"
   ```
3. Pick the highest accepted/min. Use `last5min`, not `last1min`: traffic
   arrives in bursts, and one-minute samples here varied by 40 % at the same
   gain. If two gains are within about 10 %, take the lower one. It uses less
   CPU and leaves headroom before clipping on aircraft passing overhead.
4. Sanity-check `rssi` in `aircraft.json`. Close aircraft should read about −10
   to −30 dBFS. Values pinned near 0 mean clipping. Values in a narrow band
   regardless of range mean saturation.

## 6. South Chromebook (Crostini)

The Chromebook runs readsb inside Crostini, ChromeOS's Debian Linux container. Its antenna sits at the south window. readsb runs there with fixed
gain 36.4 and pushes Beast data to the north laptop using `--net-connector`.
[`scripts/crostini/readsb-up.sh`](../scripts/crostini/readsb-up.sh) supervises
readsb.

Why a supervisor script: ChromeOS forwards USB devices into the container
explicitly, and udev rules do not fire reliably there. After a replug, the device
node returns with root-only permissions, and readsb either fails or keeps a dead
handle. `readsb-up.sh --watch` detects this and repairs it.

### 6.1 ChromeOS side

1. **Turn on Linux:** go to Settings → About ChromeOS → Developers → Linux
   development environment → Turn on.
2. **Share the dongle with Linux:** go to Settings → Developers → Linux →
   **Manage USB devices**, and turn on the RTL2832U. On older ChromeOS the path
   is Settings → About ChromeOS → Linux development environment → Manage USB
   devices. Re-share it if ChromeOS asks after a replug.
3. **Keep the Chromebook awake:** go to Settings → System preferences → Power
   (on older ChromeOS: Settings → Device → Power):
   - **Sleep when cover is closed: Off**
   - **While charging → When idle: Turn off display** (not Sleep)
   - Leave it **plugged in**. The battery idle setting can still put it to
     sleep.
4. **Reserve the Chromebook's IP** (`192.168.86.218`) in the Google Home app.
   The north laptop's firewall rule in §4 depends on it.

**Shortcut:** in the Chromebook's Linux Terminal, from any folder:
`curl -fsSLO https://raw.githubusercontent.com/JagSingh/plane_spotter/main/scripts/crostini/install.sh && sudo bash install.sh --lat <lat> --lon <lon>`.
It downloads the other three files from GitHub and runs §6.2–6.4. It is safe to
re-run, and on a re-run it keeps the existing `/etc/default/readsb-up`. The manual
steps follow.

### 6.2 Packages and readsb (in the Chromebook's Linux Terminal)

```bash
sudo apt update
sudo apt install -y usbutils psmisc iproute2 procps jq rtl-sdr
#   usbutils: lsusb   psmisc: fuser   procps: pidof   iproute2: ss
#   rtl-sdr: rtl_test (optional; readsb-up.sh skips the probe without it)

lsusb | grep -i rtl                      # dongle visible inside Crostini?

sudo bash -c "$(wget -O - https://github.com/wiedehopf/adsb-scripts/raw/master/readsb-install.sh)"
```

You don't need to blacklist modules here. The container has no kernel of its own, and
the USB device arrives already forwarded. If the stick wedges, `readsb-up.sh`
handles it with an `rtl_test` probe and a `USBDEVFS_RESET`.

Do not hand-edit `RECEIVER_OPTIONS`, `DECODER_OPTIONS` or `NET_OPTIONS` in
the Chromebook's `/etc/default/readsb`. `readsb-up.sh` owns those three lines and
rewrites them on every recovery. Other lines are left as they are.

### 6.3 Site settings

The receiver location stays out of the repo. Put it in an env file that
`readsb-up.sh` reads:

```bash
sudo install -m 0644 scripts/crostini/readsb-up.env.sample /etc/default/readsb-up
sudo nano /etc/default/readsb-up         # set LAT and LON; check FEED_HOST
```

Variables passed on the command line override the file, for example
`sudo GAIN=40.2 ./readsb-up.sh`.

### 6.4 Install readsb-up as a service

From a checkout of this repo in the Chromebook's Linux (or copy the three files from
`scripts/crostini/` into Linux files):

```bash
sudo pkill -f readsb-up.sh               # stop any manual instance
sudo install -m 0755 scripts/crostini/readsb-up.sh      /usr/local/bin/readsb-up.sh
sudo install -m 0644 scripts/crostini/readsb-up.service /etc/systemd/system/readsb-up.service
sudo systemctl daemon-reload
sudo systemctl enable readsb
sudo systemctl enable --now readsb-up
```

Verify:

```bash
systemctl is-active readsb-up readsb     # both: active
journalctl -u readsb-up -f
```

Within about 30 seconds the log should show:

```
dongle detected at /dev/bus/usb/...
updated /etc/default/readsb ...          (or "already current")
running with gain 36.4 at <lat>,<lon>
feed connected -> 192.168.86.137:30004 (beast_out)
readsb healthy — messages advancing
```

**Replug test:** with the log open, unplug the dongle and plug it back in, and
re-share it with Linux if ChromeOS asks. The log should show
`dongle unplugged`, then `dongle detected — recovering`, then `healthy`.

### 6.5 What readsb-up.sh does

| Mode | Behaviour |
|---|---|
| `sudo ./readsb-up.sh` | One-shot. Waits up to 120 s for the dongle, then recovers and verifies. Exits 0 when healthy |
| `--watch` | Checks every 10 s. Recovers on replug, if readsb stops, or if the message count stops advancing |
| `--gain <dB>\|auto` | Overrides gain. It must be an R820T step |
| `--no-feed` | Runs locally only. Drops the `--net-connector` to the north laptop |

Each recovery attempt runs these steps:

1. Wait for the dongle to appear.
2. Stop readsb and clear any start limit.
3. Kill other processes holding the device.
4. Set the device node to 0666.
5. Probe with `rtl_test`. If the probe fails, issue a USB reset and probe again.
6. Rewrite the three option lines. `/etc/default/readsb.bak` is saved first, but
   only when something changes.
7. Start readsb.
8. Verify from `/proc/<pid>/cmdline` that the running process has the gain,
   location and connector.
9. Check that the feed to the north laptop is established. A missing link only produces a
   warning, so the north laptop being down can't fail local recovery, and readsb reconnects on
   its own.
10. Require the message counter to advance over 20 s.

It makes 3 attempts and issues a USB reset before the last one.

Exit codes (one-shot): `0` healthy · `1` not root or config error · `2` dongle
never appeared · `3` failed after all attempts · `64` bad arguments.

### 6.6 After a Chromebook reboot

ChromeOS doesn't start Linux until something opens it, and it has no setting to
start Linux automatically. After any reboot, including one for an OS update:

1. Log in and open **Terminal**. Pinning it to the shelf makes this quicker.
   Opening it starts the Crostini container, and systemd then starts `readsb` and `readsb-up`.
2. Re-share the dongle if ChromeOS asks.
3. Confirm the feed from the north laptop:
   `sudo ss -tn state established '( sport = :30004 )'`.

If the feed dropped overnight, run `journalctl -u readsb-up --since "8 hours ago"`
on the south Chromebook. The log shows whether the dongle went away (because of USB or sleep)
or readsb stalled.

### 6.7 Feed protocol

The default is `beast_out`, which gives the highest update rate on a LAN. That
matters for photo triggering. If the link is unreliable,
`FEED_PROTO=beast_reduce_plus_out` cuts bandwidth.

## 7. Verification and monitoring

Check what is actually running. The config file alone is not proof:

```bash
tr '\0' ' ' < /proc/$(pidof readsb)/cmdline | grep -oE -- "--(device|gain|lat|lon|net-connector) [^ ]+"
```

Read `/proc/<pid>/cmdline` rather than `ps`, because `ps` truncates long
argument lists when piped.

On the north laptop:

```bash
systemctl status readsb
journalctl -u readsb -n 50
sudo ss -tn state established '( sport = :30004 )'     # 192.168.86.218 listed
jq '[.aircraft[]|select(.lat)]|length' /run/readsb/aircraft.json
```

On the feed connection, a small, transient `Recv-Q` is normal. If it keeps
climbing, readsb is not keeping up.

Message ratios do not measure unique-aircraft gain. To measure what the south Chromebook
*adds*, run `antcmp.py` on the north laptop for 10 minutes with the feed on and 10 minutes
with it off. On the south Chromebook, `sudo systemctl stop readsb-up readsb` turns the feed
off. Then compare `ac_pos` and `ac_near`.

## 8. Troubleshooting

| Symptom | Likely cause | Check / fix |
|---|---|---|
| `dmesg`: `error -71`, `Cannot enable` | Stick or camera behind the dock hub | §1 port path (camera: [camera-setup.md §2](camera-setup.md#2-connect-the-camera)). Move to a root port |
| `usb_claim_interface error` | DVB driver owns the stick | §2 blacklist, `lsmod \| grep dvb` |
| plane_spotter logs aircraft.json missing | readsb down, or a stale bind mount | `systemctl status readsb`. Check the `RuntimeDirectoryPreserve` drop-in |
| strong % > 5 | Gain too high | Let autogain settle. If pinned, step down |
| `remote` = 0 on the north laptop | Chromebook asleep, Linux not started, dongle not shared | §6.6, then `journalctl -u readsb-up` on the south Chromebook |
| readsb-up: `waiting for dongle` | Not shared with Linux | ChromeOS → Manage USB devices |
| readsb-up: `LAT/LON not set` | Missing env file | §6.3 |

## 9. History

**2026-10-17, Nooelec → Pro Stick Plus on the north laptop.** The south/north message ratio
measures how far behind the north laptop is; lower is better for the north laptop:

| Receiver | Gain | Window | Local | Strong % | Ratio |
|---|---|---|---|---|---|
| Nooelec | 29.7 fixed | 15 min, 09:06 | 277k | 0.24 | 2.80× |
| Pro Stick Plus | auto | 15 min, 16:21 | 445k | 7.6 | 1.45× |

Relative to the unchanged south feed, the north laptop now receives about 1.9×
the messages it did with the Nooelec, so the Nooelec was the bottleneck. Raw
local counts are not comparable across the two windows because traffic varies by
hour; use the ratio.

Open: strong signals settled at 7.6 %, above the 5 % target. Pin one gain step
below autogain's value for a full window and compare the ratio (§5).

**2026-10-10, south Chromebook feed added.** Over 15 minutes, the south Chromebook
delivered 2.6–2.9× the north laptop's local message count with the Nooelec.
