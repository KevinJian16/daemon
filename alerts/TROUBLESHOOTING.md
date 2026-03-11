# Daemon Troubleshooting Guide

## Watchdog Alerts

### API process not running
- Check: `pgrep -f "uvicorn.*services.api"`
- Fix: `cd $DAEMON_HOME && python -m uvicorn services.api:create_app --factory --host 0.0.0.0 --port 8000`

### Temporal worker not running
- Check: `pgrep -f "python.*temporal.*worker"`
- Fix: `cd $DAEMON_HOME && python temporal/worker.py`

### API not responding
- Check logs: `tail -50 $DAEMON_HOME/state/api.log`
- Common cause: port conflict, missing .env vars

### Pulse routine stale
- Check cadence: `curl -s http://127.0.0.1:8000/console/schedules | python3 -m json.tool`
- Check spine status: `cat $DAEMON_HOME/state/spine_status.json`

## Manual Recovery
1. Stop all: `pkill -f "uvicorn.*services.api"; pkill -f "python.*temporal.*worker"`
2. Re-bootstrap: `cd $DAEMON_HOME && python bootstrap.py --force`
3. Restart: start API + Worker processes

## Log Locations
- API: stdout / systemd journal
- Worker: stdout / systemd journal
- Watchdog: `$DAEMON_HOME/alerts/watchdog.log`
- Spine: `$DAEMON_HOME/state/spine_log.jsonl`
