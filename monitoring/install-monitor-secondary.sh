#!/usr/bin/env bash
# install-monitor-secondary.sh - plane_spotter published-page check on an independent always-on host.
#
#   ./install-monitor-secondary.sh              install / update (idempotent)
#   ./install-monitor-secondary.sh --test       install, then run the check now (sends a real ping)
#
# Installs into ~/monitoring/plane-spotter/ (override with MON_DIR=...):
#   monitor-secondary.sh   the check script
#   monitoring.env         Healthchecks UUIDs + settings, mode 600 (template on first run)
#   monitoring.log         one line per check per run
#   (also installs cron + curl via apt if missing; minimal Debian images such as Crostini lack cron)
#   crontab entry          hourly; the script acts only at 12:00 America/Chicago
set -euo pipefail

MON_DIR="${MON_DIR:-$HOME/monitoring/plane-spotter}"
ENV_FILE="$MON_DIR/monitoring.env"
BIN="$MON_DIR/monitor-secondary.sh"
LOG="$MON_DIR/monitoring.log"
MARK="# plane-spotter-monitor-secondary (managed by install-monitor-secondary.sh)"

crontab_without_mark() { { crontab -l 2>/dev/null || true; } | { grep -vF "$MARK" || true; }; }

# ---- prerequisites
missing=()
command -v crontab >/dev/null || missing+=(cron)
command -v curl    >/dev/null || missing+=(curl)
if [ ${#missing[@]} -gt 0 ]; then
  echo "Installing: ${missing[*]}"
  sudo apt-get update -qq && sudo apt-get install -y -qq "${missing[@]}"
fi
sudo systemctl enable --now cron >/dev/null 2>&1 || sudo service cron start
systemctl is-active --quiet cron 2>/dev/null || pgrep -x cron >/dev/null || { echo "ERROR: cron is not running" >&2; exit 1; }

# ---- install folder
mkdir -p "$MON_DIR"

# ---- config
if [ ! -f "$ENV_FILE" ]; then
  umask 077
  cat > "$ENV_FILE" <<'EOF'
# plane_spotter monitoring config (monitor-secondary). Sourced by monitor-secondary.sh in this folder.
# Healthchecks.io ping UUID: check -> "Ping URL" -> the part after https://hc-ping.com/
HC_PS_PAGE=
# Optional overrides
#RUN_HOURS="12"
#PLANES_BASE_URL=https://planes.jagmsingh.com
EOF
  echo "Created $ENV_FILE (mode 600). Fill in the UUID, then rerun: $0 ${1:-}"
  exit 1
fi
# shellcheck source=/dev/null
. "$ENV_FILE"
[ -n "${HC_PS_PAGE:-}" ] || { echo "ERROR: HC_PS_PAGE is empty in $ENV_FILE" >&2; exit 1; }

# ---- check script
cat > "$BIN" <<'EOF'
#!/usr/bin/env bash
# monitor-secondary.sh - installed by install-monitor-secondary.sh. Rerun the installer to update.
# Runs hourly from cron; acts only at RUN_HOURS (America/Chicago). FORCE=1 runs now; FORCE_FAIL=1 reports failure (alert test).
set -u
export TZ=America/Chicago PATH="$PATH:/usr/local/bin:/usr/bin:/bin"
# shellcheck source=/dev/null
. "${ENV_FILE:-$(cd "$(dirname "$0")" && pwd)/monitoring.env}"
RUN_HOURS="${RUN_HOURS:-12}"
BASE="${PLANES_BASE_URL:-https://planes.jagmsingh.com}"
if [ "${FORCE:-0}" != 1 ] && [[ " $RUN_HOURS " != *" $(date +%H) "* ]]; then exit 0; fi

# Today's daily page exists
f="planes_$(date +%y%m%d).html"
code=$(curl -sS -m 30 -o /dev/null -w '%{http_code}' "$BASE/$f?nocache=$(date +%s)")
code="${code:-000}"   # curl prints 000 itself on network errors
[ "${FORCE_FAIL:-0}" = 1 ] && code="000 (forced test failure, FORCE_FAIL=1)"
if [ "$code" = 200 ]; then status=ok; url="https://hc-ping.com/$HC_PS_PAGE"
else status=FAIL; url="https://hc-ping.com/$HC_PS_PAGE/fail"; fi
msg="$f HTTP $code"
echo "$(date '+%F %T %Z') ps-page $status: $msg"
curl -fsS -m 10 --retry 3 -o /dev/null --data-raw "$msg" "$url" || echo "  ping failed: $url"
EOF
chmod 755 "$BIN"
echo "Installed $BIN"

# ---- cron (hourly at :00; the script gates on Chicago hour, so a UTC system clock doesn't matter)
{ crontab_without_mark; echo "0 * * * * $BIN >> $LOG 2>&1 $MARK"; } | crontab -
echo "Installed cron entry:"; crontab -l | grep -F "$MARK"

if [ "${1:-}" = "--test" ]; then
  echo "--- test run (real ping) ---"
  FORCE=1 "$BIN"
fi
