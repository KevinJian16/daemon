# Daemon Troubleshooting Guide

## Service Management (launchd)

### Check all services
```bash
launchctl list | grep daemon
```

### Restart a service
```bash
launchctl kickstart -k gui/$(id -u)/ai.kevinjian.daemon.api
launchctl kickstart -k gui/$(id -u)/ai.kevinjian.daemon.worker
launchctl kickstart -k gui/$(id -u)/ai.kevinjian.daemon.openclaw.gateway
launchctl kickstart -k gui/$(id -u)/ai.kevinjian.daemon.telegram.adapter
```

### API not responding (port 8100)
- Check: `curl -s http://127.0.0.1:8100/health`
- Logs: `tail -50 $DAEMON_HOME/state/service_logs/api.err.log`
- Common cause: PG not running, .env missing

### Worker not processing Jobs
- Check: Temporal UI at http://127.0.0.1:8080
- Logs: `tail -50 $DAEMON_HOME/state/service_logs/worker.err.log`
- Common cause: OC Gateway down, Temporal not running

### OC Gateway not responding (port 18790)
- Check: `curl -s http://127.0.0.1:18790/`
- Logs: `tail -50 $DAEMON_HOME/state/service_logs/openclaw_gateway.err.log`
- Common cause: openclaw.json syntax error, port conflict

## Docker Services

### Check all containers
```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | grep daemon
```

### Restart all Docker services
```bash
cd $DAEMON_HOME && docker compose restart
```

### PG not accessible
- Check: `docker exec daemon-postgres-1 pg_isready`
- Fix: `docker compose restart postgres`

## Manual Recovery
1. Restart Docker: `cd $DAEMON_HOME && docker compose restart`
2. Restart launchd services (all 4)
3. Check: `curl -s http://127.0.0.1:8100/status | python3 -m json.tool`

## Log Locations
- API: `$DAEMON_HOME/state/service_logs/api.{out,err}.log`
- Worker: `$DAEMON_HOME/state/service_logs/worker.{out,err}.log`
- OC Gateway: `$DAEMON_HOME/state/service_logs/openclaw_gateway.{out,err}.log`
- Telegram: `$DAEMON_HOME/state/service_logs/telegram_adapter.{out,err}.log`
