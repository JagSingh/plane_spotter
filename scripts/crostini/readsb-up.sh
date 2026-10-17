#!/usr/bin/env bash
# (c) jag.m.singh@gmail.com
# readsb-up.sh — bring readsb back up on the south Chromebook (Crostini) after
# the RTL-SDR dongle is unplugged/replugged, with the south-window receiver
# config and a live Beast feed pushed to the north laptop (production host:
# plane_spotter + double-scramble).
#
# Two indoor antennas (north and south windows) are used in lieu of climbing
# onto the roof to install an outdoor antenna and a gas-discharge tube; this
# script keeps the south half of that pair alive.
#
# Full setup: docs/receiver-setup.md §6
#
# Usage:
#   sudo ./readsb-up.sh                 # one-shot: wait for dongle, apply config, recover, verify
#   sudo ./readsb-up.sh --watch         # keep running; auto-recover on every replug
#   sudo ./readsb-up.sh --gain 40.2     # override gain (R820T step or "auto")
#   sudo ./readsb-up.sh --no-feed       # local only; drop the --net-connector to the north laptop
#
# Site settings come from /etc/default/readsb-up (KEY="value" lines; see
# readsb-up.env.sample). LAT and LON are required and deliberately not in
# this repo. Precedence: command-line env > env file > built-in default.
#   GAIN=36.4  MAX_RANGE=450
#   FEED_HOST=192.168.86.137 (north laptop; empty disables)  FEED_PORT=30004  FEED_PROTO=beast_out
#
# The script owns RECEIVER_OPTIONS, DECODER_OPTIONS and NET_OPTIONS in
# /etc/default/readsb (backup at /etc/default/readsb.bak on any change).
# Other lines (JSON_OPTIONS etc.) are left untouched.
#
# North laptop side: readsb must accept Beast input on 30004 (default --net-bi-port
# 30004,30104). No firewall change was needed; if the port is ever blocked,
# see docs/receiver-setup.md §4.
#
# Install as a service (watch mode starts with the container):
#   sudo install -m 0755 readsb-up.sh      /usr/local/bin/readsb-up.sh
#   sudo install -m 0644 readsb-up.service /etc/systemd/system/readsb-up.service
#   sudo systemctl daemon-reload && sudo systemctl enable readsb && sudo systemctl enable --now readsb-up
#
# Exit codes (one-shot): 0 healthy, 1 not root / config error, 2 dongle never
# appeared, 3 readsb failed to recover after all attempts, 64 bad arguments.

set -uo pipefail

# --- site settings file ------------------------------------------------------
# Parsed, not sourced: only KEY=value lines, and a variable already set in the
# environment wins over the file.
ENV_FILE="${ENV_FILE:-/etc/default/readsb-up}"
if [[ -r $ENV_FILE ]]; then
  while IFS='=' read -r k v; do
    [[ $k =~ ^[A-Z_]+$ ]] || continue
    v="${v%\"}"; v="${v#\"}"
    [[ -v $k ]] || printf -v "$k" '%s' "$v"
  done < "$ENV_FILE"
fi

SERVICE="${SERVICE:-readsb}"
RUNDIR="${RUNDIR:-/run/readsb}"
VIDPID_RE="${VIDPID_RE:-0bda:283[28]}"   # RTL2832U (Pro Stick Plus, NESDR, etc.)
WAIT_DEV_SECS="${WAIT_DEV_SECS:-120}"
HEALTH_SECS="${HEALTH_SECS:-20}"
ATTEMPTS="${ATTEMPTS:-3}"
WATCH_INTERVAL="${WATCH_INTERVAL:-10}"
CONF="${CONF:-/etc/default/readsb}"
LOCK=/run/readsb-up.lock
R820T_GAINS="0.0 0.9 1.4 2.7 3.7 7.7 8.7 12.5 14.4 15.7 16.6 19.7 20.7 22.9 25.4 28.0 29.7 32.8 33.8 36.4 37.2 38.6 40.2 42.1 43.4 43.9 44.5 48.0 49.6"

# --- receiver / feed parameters ---------------------------------------------
GAIN="${GAIN:-36.4}"
LAT="${LAT:-}"                             # required: env file or environment
LON="${LON:-}"
MAX_RANGE="${MAX_RANGE:-450}"
FEED_HOST="${FEED_HOST-192.168.86.137}"    # north laptop; empty disables the feed
FEED_PORT="${FEED_PORT:-30004}"            # north laptop readsb beast-in
FEED_PROTO="${FEED_PROTO:-beast_out}"
MODE="once"

usage() { echo "usage: sudo $0 [--once|--watch] [--gain <dB>|auto] [--no-feed]"; exit 64; }
while (( $# )); do
  case "$1" in
    --once)    MODE=once ;;
    --watch)   MODE=watch ;;
    --gain)    [[ $# -ge 2 ]] || usage; GAIN="$2"; shift ;;
    --gain=*)  GAIN="${1#--gain=}" ;;
    --no-feed) FEED_HOST="" ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
  shift
done

log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
die() { log "ERROR: $1"; exit "${2:-1}"; }

# --- validate parameters (before touching anything) ------------------------

[[ -n $LAT && -n $LON ]] || die "LAT/LON not set; put them in $ENV_FILE (see readsb-up.env.sample)" 64
if [[ $GAIN != auto ]]; then
  [[ $GAIN =~ ^[0-9]+(\.[0-9])?$ ]] || die "invalid gain '$GAIN' (use e.g. 36.4 or auto)" 64
  [[ $GAIN == *.* ]] || GAIN="$GAIN.0"
  [[ " $R820T_GAINS " == *" $GAIN "* ]] ||
    die "gain $GAIN is not an R820T step; valid: $R820T_GAINS" 64
fi
[[ $LAT =~ ^-?[0-9]{1,2}(\.[0-9]+)?$ ]] && awk -v v="$LAT" 'BEGIN{exit !(v>=-90 && v<=90)}' ||
  die "invalid LAT '$LAT'" 64
[[ $LON =~ ^-?[0-9]{1,3}(\.[0-9]+)?$ ]] && awk -v v="$LON" 'BEGIN{exit !(v>=-180 && v<=180)}' ||
  die "invalid LON '$LON'" 64
[[ $MAX_RANGE =~ ^[0-9]+$ ]] || die "invalid MAX_RANGE '$MAX_RANGE'" 64
if [[ -n $FEED_HOST ]]; then
  [[ $FEED_HOST =~ ^[A-Za-z0-9.-]+$ ]] || die "invalid FEED_HOST '$FEED_HOST'" 64
  [[ $FEED_PORT =~ ^[0-9]+$ ]] && (( FEED_PORT > 0 && FEED_PORT < 65536 )) ||
    die "invalid FEED_PORT '$FEED_PORT'" 64
  [[ $FEED_PROTO =~ ^(beast_out|beast_reduce_out|beast_reduce_plus_out|raw_out|sbs_out)$ ]] ||
    die "invalid FEED_PROTO '$FEED_PROTO'" 64
fi

[[ $EUID -eq 0 ]] || die "run with sudo" 1
[[ -f $CONF ]] || die "$CONF not found; needs the packaged readsb service config" 1

exec 9>"$LOCK"
flock -n 9 || die "another readsb-up is already running" 1

# --- helpers ---------------------------------------------------------------

dev_node() {   # print /dev/bus/usb/BBB/DDD for the first matching dongle
  lsusb 2>/dev/null | grep -m1 -E "ID ${VIDPID_RE}" |
    awk '{gsub(":","",$4); printf "/dev/bus/usb/%s/%s\n", $2, $4}'
}

msg_count() {  # total messages from aircraft.json, or -1
  python3 -I - "$RUNDIR/aircraft.json" <<'EOF' 2>/dev/null || echo -1
import json, sys
try:
    print(int(json.load(open(sys.argv[1])).get("messages", -1)))
except Exception:
    print(-1)
EOF
}

healthy() {    # service active AND message counter advancing over HEALTH_SECS
  systemctl is-active --quiet "$SERVICE" || return 1
  local a b
  a=$(msg_count); sleep "$HEALTH_SECS"; b=$(msg_count)
  [[ $a -ge 0 && $b -gt $a ]]
}

wait_for_dongle() {
  local t=0 node
  while (( t < WAIT_DEV_SECS )); do
    node=$(dev_node)
    if [[ -n $node && -e $node ]]; then echo "$node"; return 0; fi
    (( t % 30 == 0 )) && log "waiting for dongle — if it doesn't appear, share it with Linux: ChromeOS Settings > Developers > Linux > Manage USB devices" >&2
    sleep 2; (( t += 2 ))
  done
  return 1
}

fix_perms() {  # udev rules don't fire reliably in the container
  chmod 0666 "$1" && log "permissions set on $1"
}

kill_holders() {  # anything other than our service still holding the device
  local node=$1 pids
  pids=$(fuser "$node" 2>/dev/null | tr -s ' ')
  [[ -z $pids ]] && return 0
  log "device held by PID(s):$pids — terminating"
  kill $pids 2>/dev/null; sleep 2
  fuser -k "$node" 2>/dev/null; sleep 1
}

usb_reset() {
  python3 -I - "$1" <<'EOF' && log "USB reset issued on $1" || log "USB reset failed on $1"
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_WRONLY)
fcntl.ioctl(fd, 0x5514, 0)   # USBDEVFS_RESET
os.close(fd)
EOF
  sleep 3
}

probe() {      # optional sanity check with rtl_test; skipped if not installed
  command -v rtl_test >/dev/null || return 0
  local out
  out=$(timeout 8 rtl_test -t 2>&1)
  if grep -qE 'usb_open error|usb_claim_interface error|No supported devices' <<<"$out"; then
    log "rtl_test probe failed:"; grep -E 'error|devices' <<<"$out" | sed 's/^/    /'
    return 1
  fi
  return 0
}

# --- config ----------------------------------------------------------------

set_gain() {   # render RECEIVER/DECODER/NET_OPTIONS in $CONF; no-op if unchanged
  local rcv dec net tmp
  rcv="--device 0 --device-type rtlsdr --gain $GAIN --ppm 0"
  dec="--lat $LAT --lon $LON --max-range $MAX_RANGE --write-json-every 1"
  net="--net --net-ri-port 30001 --net-ro-port 30002 --net-sbs-port 30003"
  net+=" --net-bi-port 30004,30104 --net-bo-port 30005"
  [[ -n $FEED_HOST ]] && net+=" --net-connector $FEED_HOST,$FEED_PORT,$FEED_PROTO"

  tmp=$(mktemp) || die "mktemp failed" 1
  awk -v r="$rcv" -v d="$dec" -v n="$net" '
    BEGIN { want["RECEIVER_OPTIONS"]=r; want["DECODER_OPTIONS"]=d; want["NET_OPTIONS"]=n }
    { k=$0; sub(/=.*/, "", k)
      if (k in want) { if (!(k in seen)) print k "=\"" want[k] "\""; seen[k]=1; next }
      print }
    END { for (k in want) if (!(k in seen)) print k "=\"" want[k] "\"" }
  ' "$CONF" > "$tmp" || { rm -f "$tmp"; die "failed to render $CONF" 1; }

  if cmp -s "$tmp" "$CONF"; then
    rm -f "$tmp"; log "$CONF already current (gain $GAIN, feed ${FEED_HOST:-off})"; return 0
  fi
  cp -p "$CONF" "$CONF.bak"
  cat "$tmp" > "$CONF"; rm -f "$tmp"          # keeps owner/mode
  log "updated $CONF (backup $CONF.bak):"
  grep -E '^(RECEIVER|DECODER|NET)_OPTIONS=' "$CONF" | while read -r l; do log "  $l"; done
}

verify_gain() {  # running readsb must carry gain, location and feed
  local pid args want ok=1 i
  pid=$(pidof -s readsb 2>/dev/null) || { log "readsb not running"; return 1; }
  # read /proc directly: ps truncates args to 80 columns when piped
  args=" $(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null) "

  for want in "--gain $GAIN" "--lat $LAT" "--lon $LON" \
              ${FEED_HOST:+"--net-connector $FEED_HOST,$FEED_PORT,$FEED_PROTO"}; do
    [[ $args == *" $want "* ]] || { log "running readsb missing: $want"; ok=0; }
  done
  (( ok )) || { log "running args:$args"; return 1; }
  log "running with gain $GAIN at $LAT,$LON"

  # feed link: warn only — north laptop being down must not fail local recovery
  [[ -z $FEED_HOST ]] && { log "feed disabled (--no-feed)"; return 0; }
  for i in $(seq 1 10); do
    if [[ -n $(ss -Htn state established dst "$FEED_HOST:$FEED_PORT" 2>/dev/null) ]]; then
      log "feed connected -> $FEED_HOST:$FEED_PORT ($FEED_PROTO)"; return 0
    fi
    sleep 1
  done
  log "WARNING: no connection to $FEED_HOST:$FEED_PORT after 10 s — check north laptop readsb/port $FEED_PORT/firewall (readsb retries on its own)"
  return 0
}

# --- recovery --------------------------------------------------------------

recover() {    # one full recovery attempt; returns 0 if healthy afterwards
  local node
  node=$(wait_for_dongle) || return 2
  log "dongle at $node"
  systemctl stop "$SERVICE" 2>/dev/null
  systemctl reset-failed "$SERVICE" 2>/dev/null   # clear start-limit after rapid crash loops
  kill_holders "$node"
  fix_perms "$node"
  if ! probe; then
    usb_reset "$node"
    node=$(dev_node); [[ -n $node ]] || return 1   # device number can change after reset
    fix_perms "$node"
    probe || return 1
  fi
  set_gain || return 1
  systemctl start "$SERVICE" || return 1
  sleep 3
  verify_gain || return 1
  if healthy; then
    log "readsb healthy — messages advancing"
    return 0
  fi
  log "readsb not receiving; recent log:"
  journalctl -u "$SERVICE" -n 15 --no-pager 2>/dev/null | sed 's/^/    /'
  return 1
}

one_shot() {
  local i rc node
  for (( i = 1; i <= ATTEMPTS; i++ )); do
    log "recovery attempt $i/$ATTEMPTS"
    recover; rc=$?
    [[ $rc -eq 0 ]] && return 0
    [[ $rc -eq 2 ]] && die "dongle not visible to Linux after ${WAIT_DEV_SECS}s" 2
    # escalate on the last attempt: reset the device before trying again
    if (( i == ATTEMPTS - 1 )); then node=$(dev_node); [[ -n $node ]] && usb_reset "$node"; fi
  done
  die "readsb did not recover after $ATTEMPTS attempts" 3
}

watch_loop() {
  log "watch mode: checking every ${WATCH_INTERVAL}s (gain $GAIN, feed ${FEED_HOST:-off})"
  local last=-1 now node present=0
  while true; do
    node=$(dev_node)
    if [[ -z $node ]]; then
      (( present )) && log "dongle unplugged — waiting for it to return"
      present=0; last=-1; sleep "$WATCH_INTERVAL"; continue
    fi
    if (( ! present )); then
      log "dongle detected at $node — recovering"
      present=1
      one_shot_safe; last=$(msg_count); sleep "$WATCH_INTERVAL"; continue
    fi
    now=$(msg_count)
    if ! systemctl is-active --quiet "$SERVICE" || [[ $now -le $last ]]; then
      log "readsb stalled (active=$(systemctl is-active "$SERVICE"), msgs $last -> $now) — recovering"
      one_shot_safe; now=$(msg_count)
    fi
    last=$now
    sleep "$WATCH_INTERVAL"
  done
}

one_shot_safe() { ( one_shot ) || log "recovery failed; will retry on next check"; }

if [[ $MODE == watch ]]; then watch_loop; else one_shot; fi
