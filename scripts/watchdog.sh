#!/usr/bin/env bash
# Daemon watchdog — independent health check (§4.5)
# Runs via cron every 5 minutes. Does NOT depend on daemon Python modules.
# Checks: process alive, API responsive, pulse routine freshness.
# Notifies: Telegram → macOS notification → alert log.
set -euo pipefail

DAEMON_HOME="${DAEMON_HOME:-$(cd "$(dirname "$0")/.." && pwd)}"
STATE="$DAEMON_HOME/state"
ALERTS="$DAEMON_HOME/alerts"
ALERT_LOG="$ALERTS/watchdog.log"
ENV_FILE="$DAEMON_HOME/.env"
API_PORT="${DAEMON_API_PORT:-8000}"
PULSE_MAX_AGE_MIN=30

mkdir -p "$ALERTS"

# Load .env for Telegram credentials
if [ -f "$ENV_FILE" ]; then
  set -a; source "$ENV_FILE"; set +a
fi

_ts() { date -u "+%Y-%m-%dT%H:%M:%SZ"; }

_notify() {
  local msg="[daemon-watchdog] $1"
  echo "$(_ts) $msg" >> "$ALERT_LOG"
  # Telegram
  if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
    curl -sf -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d chat_id="$TELEGRAM_CHAT_ID" -d text="$msg" -d parse_mode=Markdown >/dev/null 2>&1 || true
  fi
  # macOS notification
  if command -v osascript >/dev/null 2>&1; then
    osascript -e "display notification \"$1\" with title \"Daemon Watchdog\"" 2>/dev/null || true
  fi
}

errors=()

# 1. Process alive (uvicorn serving api.py)
if ! pgrep -f "uvicorn.*services.api" >/dev/null 2>&1; then
  errors+=("API process not running")
fi

# 2. Temporal worker alive
if ! pgrep -f "python.*temporal.*worker" >/dev/null 2>&1; then
  errors+=("Temporal worker not running")
fi

# 3. API responds
if ! curl -sf --max-time 5 "http://127.0.0.1:${API_PORT}/system/status" >/dev/null 2>&1; then
  errors+=("API not responding on port $API_PORT")
fi

# 4. Pulse routine freshness (check schedule_history.json)
HIST="$STATE/schedule_history.json"
if [ -f "$HIST" ]; then
  # Find last pulse entry timestamp using lightweight jq/python
  last_pulse=$(python3 -c "
import json, sys, time
rows = json.loads(open('$HIST').read()) if True else []
    pulse = [r for r in rows if r.get('routine') == 'spine.pulse' and r.get('status') == 'ok']
    if not pulse: sys.exit(0)
    ts = pulse[-1].get('run_utc', '')
if not ts: sys.exit(0)
from datetime import datetime, timezone
dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
age_min = (datetime.now(timezone.utc) - dt).total_seconds() / 60
print(f'{age_min:.0f}')
" 2>/dev/null || echo "")
  if [ -n "$last_pulse" ] && [ "$last_pulse" -gt "$PULSE_MAX_AGE_MIN" ] 2>/dev/null; then
    errors+=("Pulse routine stale (${last_pulse}min ago, max ${PULSE_MAX_AGE_MIN}min)")
  fi
fi

if [ ${#errors[@]} -gt 0 ]; then
  _notify "ALERT: ${errors[*]}"
  exit 1
fi
exit 0
