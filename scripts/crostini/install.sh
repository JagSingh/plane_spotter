#!/usr/bin/env bash
# (c) jag.m.singh@gmail.com
# install.sh — provision the south Chromebook (Crostini) receiver from scratch:
# packages, readsb, site settings, and the readsb-up watchdog service.
# Runs docs/receiver-setup.md §6.2–6.4 non-interactively. Safe to re-run.
#
# Only this file is needed on the Chromebook; the other three files are
# downloaded from GitHub. In the Chromebook's Linux Terminal, in any folder:
#   curl -fsSLO https://raw.githubusercontent.com/JagSingh/plane_spotter/main/scripts/crostini/install.sh
#   sudo bash install.sh --lat <lat> --lon <lon>     # first install
#   sudo bash install.sh                             # re-run: keeps existing /etc/default/readsb-up
#
# Options (--lat/--lon/--gain/--feed-host override keys in /etc/default/readsb-up):
#   --lat <deg> --lon <deg>     antenna position; required on first install
#   --gain <dB|auto>            default 36.4
#   --feed-host <ip>            north laptop; default 192.168.86.137; "" disables
#   --ref <branch|tag|sha>      GitHub ref to download from; default main
#   --local                     use the files next to this script (repo checkout) instead
#   --skip-readsb               don't run the readsb installer even if readsb is missing
#
# Not done here (ChromeOS side, see §6.1): turning on Linux, sharing the
# RTL2832U under Settings > Developers > Linux > Manage USB devices, power
# settings, and reserving the Chromebook's IP.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_RAW=https://raw.githubusercontent.com/JagSingh/plane_spotter
REPO_PATH=scripts/crostini
FILES=(readsb-up.sh readsb-up.service readsb-up.env.sample)
ENV_FILE=/etc/default/readsb-up
READSB_INSTALLER=https://github.com/wiedehopf/adsb-scripts/raw/master/readsb-install.sh
PACKAGES=(usbutils psmisc iproute2 procps jq rtl-sdr python3 wget ca-certificates)

LAT="" LON="" GAIN="" FEED_HOST_SET=0 FEED_HOST="" SKIP_READSB=0 REF=main LOCAL=0

log() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '/^# Only this file/,/^#   --skip-readsb/p' "$0" | sed 's/^# \{0,1\}//'; exit 64; }

while (( $# )); do
  case "$1" in
    --lat)         [[ $# -ge 2 ]] || usage; LAT="$2"; shift ;;
    --lon)         [[ $# -ge 2 ]] || usage; LON="$2"; shift ;;
    --gain)        [[ $# -ge 2 ]] || usage; GAIN="$2"; shift ;;
    --feed-host)   [[ $# -ge 2 ]] || usage; FEED_HOST="$2"; FEED_HOST_SET=1; shift ;;
    --ref)         [[ $# -ge 2 ]] || usage; REF="$2"; shift ;;
    --local)       LOCAL=1 ;;
    --skip-readsb) SKIP_READSB=1 ;;
    -h|--help)     usage ;;
    *)             usage ;;
  esac
  shift
done

[[ $EUID -eq 0 ]] || die "run with sudo"
[[ $REF =~ ^[A-Za-z0-9._/-]+$ ]] || die "invalid --ref '$REF'"
if (( LOCAL )); then
  for f in "${FILES[@]}"; do
    [[ -f $HERE/$f ]] || die "--local: missing $HERE/$f"
  done
fi

# Validate early; readsb-up.sh re-validates at runtime.
[[ -z $LAT || $LAT =~ ^-?[0-9]{1,2}(\.[0-9]+)?$ ]] || die "invalid --lat '$LAT'"
[[ -z $LON || $LON =~ ^-?[0-9]{1,3}(\.[0-9]+)?$ ]] || die "invalid --lon '$LON'"
[[ -z $GAIN || $GAIN == auto || $GAIN =~ ^[0-9]+(\.[0-9])?$ ]] || die "invalid --gain '$GAIN'"
[[ $FEED_HOST_SET -eq 0 || -z $FEED_HOST || $FEED_HOST =~ ^[A-Za-z0-9.-]+$ ]] ||
  die "invalid --feed-host '$FEED_HOST'"
if [[ ! -f $ENV_FILE && ( -z $LAT || -z $LON ) ]]; then
  die "first install needs --lat and --lon ($ENV_FILE does not exist yet)"
fi

# --- 1. packages -------------------------------------------------------------
log "Installing packages: ${PACKAGES[*]}"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq "${PACKAGES[@]}"

# --- 1b. fetch the other files ------------------------------------------------
if (( LOCAL )); then
  SRC=$HERE
  log "Using local files in $SRC"
else
  SRC=$(mktemp -d)
  trap 'rm -rf "$SRC"' EXIT
  log "Downloading ${FILES[*]} from GitHub ($REF)"
  for f in "${FILES[@]}"; do
    wget -q -O "$SRC/$f" "$REPO_RAW/$REF/$REPO_PATH/$f" ||
      die "download failed: $REPO_RAW/$REF/$REPO_PATH/$f (check --ref and network)"
    [[ -s $SRC/$f ]] || die "downloaded $f is empty"
  done
  head -1 "$SRC/readsb-up.sh" | grep -q '^#!' || die "readsb-up.sh does not look like a script"
  bash -n "$SRC/readsb-up.sh" || die "readsb-up.sh failed a syntax check"
fi

# --- 2. dongle visible? (warn only; readsb-up waits for it) ------------------
if lsusb | grep -qE 'ID 0bda:283[28]'; then
  log "Dongle visible: $(lsusb | grep -E 'ID 0bda:283[28]' | head -1)"
else
  log "WARNING: no RTL2832U visible to Linux. Share it in ChromeOS:"
  echo "    Settings > Developers > Linux > Manage USB devices > RTL2832U on"
  echo "    Continuing; readsb-up will pick it up once it is shared."
fi

# --- 3. readsb ----------------------------------------------------------------
if systemctl cat readsb >/dev/null 2>&1 && [[ -f /etc/default/readsb ]]; then
  log "readsb already installed — skipping installer"
elif (( SKIP_READSB )); then
  die "readsb is not installed and --skip-readsb was given"
else
  log "Installing readsb (wiedehopf installer; builds from source, takes a few minutes)"
  tmp=$(mktemp)
  wget -qO "$tmp" "$READSB_INSTALLER" || { rm -f "$tmp"; die "download failed: $READSB_INSTALLER"; }
  bash "$tmp"; rm -f "$tmp"
  [[ -f /etc/default/readsb ]] || die "readsb installer finished but /etc/default/readsb is missing"
fi

# --- 4. site settings -----------------------------------------------------------
set_kv() {  # set KEY="value" in $ENV_FILE, replacing an existing line or appending
  local k=$1 v=$2 tmp
  tmp=$(mktemp)
  awk -v k="$k" -v v="$v" '
    $0 ~ "^"k"=" { if (!done) print k "=\"" v "\""; done=1; next }
    { print }
    END { if (!done) print k "=\"" v "\"" }' "$ENV_FILE" > "$tmp"
  cat "$tmp" > "$ENV_FILE"; rm -f "$tmp"
}

if [[ ! -f $ENV_FILE ]]; then
  log "Creating $ENV_FILE from readsb-up.env.sample"
  install -m 0644 "$SRC/readsb-up.env.sample" "$ENV_FILE"
else
  log "Keeping existing $ENV_FILE (backup: $ENV_FILE.bak)"
  cp -p "$ENV_FILE" "$ENV_FILE.bak"
fi
[[ -n $LAT ]]  && set_kv LAT "$LAT"
[[ -n $LON ]]  && set_kv LON "$LON"
[[ -n $GAIN ]] && set_kv GAIN "$GAIN"
(( FEED_HOST_SET )) && set_kv FEED_HOST "$FEED_HOST"
grep -E '^(LAT|LON|GAIN|FEED_HOST)=' "$ENV_FILE" | sed 's/^/    /'

# --- 5. watchdog service ----------------------------------------------------------
log "Installing readsb-up.sh and readsb-up.service"
systemctl stop readsb-up 2>/dev/null || true
pkill -f '/readsb-up.sh' 2>/dev/null || true      # any manual instance
install -m 0755 "$SRC/readsb-up.sh"      /usr/local/bin/readsb-up.sh
install -m 0644 "$SRC/readsb-up.service" /etc/systemd/system/readsb-up.service
systemctl daemon-reload
systemctl enable readsb >/dev/null
systemctl enable --now readsb-up >/dev/null

# --- 6. verify ----------------------------------------------------------------------
log "Waiting up to 90 s for readsb-up to report healthy"
since=$(date '+%F %T')
for _ in $(seq 1 45); do
  if journalctl -u readsb-up --since "$since" --no-pager 2>/dev/null | grep -q 'readsb healthy'; then
    journalctl -u readsb-up --since "$since" --no-pager -o cat | grep -E 'running with|feed connected|WARNING|healthy' | sed 's/^/    /'
    log "Done. readsb and readsb-up are running."
    echo "    Confirm on the north laptop: sudo ss -tn state established '( sport = :30004 )'"
    exit 0
  fi
  sleep 2
done

log "Not healthy yet. Recent readsb-up log:"
journalctl -u readsb-up --since "$since" --no-pager -o cat | tail -20 | sed 's/^/    /'
echo "    Follow it with: journalctl -u readsb-up -f"
echo "    'waiting for dongle' means the RTL2832U is not shared with Linux yet."
exit 2
