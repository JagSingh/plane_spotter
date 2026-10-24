#!/usr/bin/env bash
# install-prod-primary.sh - plane_spotter log checks on the production host (where the container runs).
#
#   ./install-prod-primary.sh              install / update (idempotent)
#   ./install-prod-primary.sh --test       install, then run the checks now (sends real pings)
#
# Installs into ~/monitoring/plane-spotter/ (override with MON_DIR=...):
#   monitor-primary.sh     the check script
#   monitoring.env         Healthchecks UUIDs + settings, mode 600 (template on first run)
#   monitoring.log         one line per check per run
#   crontab entry          hourly; the script acts only at 12:00 and 16:00 America/Chicago
set -euo pipefail

MON_DIR="${MON_DIR:-$HOME/monitoring/plane-spotter}"
ENV_FILE="$MON_DIR/monitoring.env"
BIN="$MON_DIR/monitor-primary.sh"
LOG="$MON_DIR/monitoring.log"
MARK="# plane-spotter-monitor-primary (managed by install-prod-primary.sh)"

crontab_without_mark() { { crontab -l 2>/dev/null || true; } | { grep -vF "$MARK" || true; }; }

# ---- prerequisites
for c in docker curl crontab; do
  command -v "$c" >/dev/null || { echo "ERROR: '$c' not found" >&2; exit 1; }
done
docker ps >/dev/null 2>&1 || { echo "ERROR: $USER cannot run docker (add to the docker group, re-login)" >&2; exit 1; }

# ---- install folder
mkdir -p "$MON_DIR"

# ---- config
if [ ! -f "$ENV_FILE" ]; then
  umask 077
  cat > "$ENV_FILE" <<'EOF'
# plane_spotter monitoring config (prod-primary). Sourced by monitor-primary.sh in this folder.
# Healthchecks.io ping UUIDs: check -> "Ping URL" -> the part after https://hc-ping.com/
PS_CONTAINER=plane-spotter
HC_PS_ADSB=
HC_PS_PHOTO=
# Optional overrides
#RUN_HOURS="12 16"
#WINDOW=4h
EOF
  echo "Created $ENV_FILE (mode 600). Fill in the UUIDs, then rerun: $0 ${1:-}"
  exit 1
fi
# shellcheck source=/dev/null
. "$ENV_FILE"
for v in PS_CONTAINER HC_PS_ADSB HC_PS_PHOTO; do
  [ -n "${!v:-}" ] || { echo "ERROR: $v is empty in $ENV_FILE" >&2; exit 1; }
done
if ! docker inspect "$PS_CONTAINER" >/dev/null 2>&1; then
  echo "ERROR: container '$PS_CONTAINER' not found. Running containers:" >&2
  docker ps --format '  {{.Names}}' >&2; exit 1
fi

# ---- check script
cat > "$BIN" <<'EOF'
#!/usr/bin/env bash
# monitor-primary.sh - installed by install-prod-primary.sh. Rerun the installer to update.
# Runs hourly from cron; acts only at RUN_HOURS (America/Chicago). FORCE=1 runs now; FORCE_FAIL=1 reports failure (alert test).
set -u
export TZ=America/Chicago PATH="$PATH:/usr/local/bin:/usr/bin:/bin"
# shellcheck source=/dev/null
. "${ENV_FILE:-$(cd "$(dirname "$0")" && pwd)/monitoring.env}"
RUN_HOURS="${RUN_HOURS:-12 16}"
WINDOW="${WINDOW:-4h}"
if [ "${FORCE:-0}" != 1 ] && [[ " $RUN_HOURS " != *" $(date +%H) "* ]]; then exit 0; fi

# logcheck <name> <container> <literal text> <hc-uuid>
logcheck() {
  local n msg status url
  if ! docker inspect "$2" >/dev/null 2>&1; then
    n=0; msg="container '$2' not found"
  else
    n=$(docker logs --since "$WINDOW" "$2" 2>&1 | grep -cF -- "$3")
    msg="$n x '$3' in last $WINDOW"
  fi
  [ "${FORCE_FAIL:-0}" = 1 ] && { n=0; msg="forced test failure (FORCE_FAIL=1)"; }
  if [ "$n" -gt 0 ]; then status=ok; url="https://hc-ping.com/$4"
  else status=FAIL; url="https://hc-ping.com/$4/fail"; fi
  echo "$(date '+%F %T %Z') $1 $status: $msg"
  curl -fsS -m 10 --retry 3 -o /dev/null --data-raw "$msg" "$url" || echo "  ping failed: $url"
}

logcheck ps-adsb  "$PS_CONTAINER" "New aircraft in monitored space" "$HC_PS_ADSB"
logcheck ps-photo "$PS_CONTAINER" "create_document: Airplane data"  "$HC_PS_PHOTO"
EOF
chmod 755 "$BIN"
echo "Installed $BIN"

# ---- cron (hourly at :00; the script gates on Chicago hour, so system timezone doesn't matter)
{ crontab_without_mark; echo "0 * * * * $BIN >> $LOG 2>&1 $MARK"; } | crontab -
echo "Installed cron entry:"; crontab -l | grep -F "$MARK"

if [ "${1:-}" = "--test" ]; then
  echo "--- test run (real pings) ---"
  FORCE=1 "$BIN"
fi
