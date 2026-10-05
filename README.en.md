# OpsWatch

[![Windows build](https://github.com/artemalekseev926-byte/win/actions/workflows/build-windows.yml/badge.svg)](https://github.com/artemalekseev926-byte/win/actions/workflows/build-windows.yml)
[![Tests](https://github.com/artemalekseev926-byte/win/actions/workflows/tests.yml/badge.svg)](https://github.com/artemalekseev926-byte/win/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[Русский](README.md) · **English**

**OpsWatch** is an open-source tool for system administrators and 1C:Enterprise administrators. It watches databases and 1C infobases, runs scheduled backups, receives Zabbix and Prometheus alerts, collects bug reports and routes everything to the right people in Telegram and as desktop notifications.

![Overview](docs/screenshots/overview.png)

## Features

- **Databases** — MySQL/MariaDB, PostgreSQL, MS SQL: availability, database size and custom SQL checks (new rows, threshold, rows exist). Read-only `SELECT` queries in read-only transactions.
- **1C:Enterprise** — file infobases (size and lock state of `1Cv8.1CD`, event log `.lgd`/`.lgp`, integrity check via `1cv8 DESIGNER /IBCheckAndRepair` or `chdbfl.exe` only when no users are connected) and server infobases (through the DBMS, the event log and HTTP/OData services).
- **Resource monitoring** — Zabbix webhook media type, Prometheus Alertmanager, Zabbix API polling, HTTP(S) checks and a generic webhook. Problems are closed automatically on recovery.
- **Backups** — `mysqldump`, `pg_dump`, MS SQL `BACKUP DATABASE`, 1C file infobase copy (lock check or Windows VSS shadow copy). Cron schedules, AES-256 encrypted zip, integrity verification, rotation, delivery to Telegram (split into parts, local Bot API server up to 2 GB, S3 pre-signed link or network share).
- **Bug reports** — web form with screenshots, Telegram `/bug` command with a photo, HTTP API.
- **Routing** — rules "events of type X from source Y with severity ≥ Z → roles/users N", personal subscriptions, quiet hours, deduplication and escalation of unacknowledged critical events.
- **Telegram** — direct messages with "Acknowledge", "Resolved" and "Details" buttons; subscriptions via the bot; optional personal bot per user.
- **Desktop notifications** — the Windows app shows native notifications even when minimized to the tray.
- **Users and permissions** — sign-up from the main window, approval by an administrator, roles and per-source visibility.
- **Plugins** — every source is a connector with a common interface ([how to write one](docs/connectors.md)).

The user interface is currently in Russian.

## Quick start (Windows)

1. Download `OpsWatch-<version>-windows-x64.zip` from [Releases](https://github.com/artemalekseev926-byte/win/releases) or from the latest [build artifacts](https://github.com/artemalekseev926-byte/win/actions/workflows/build-windows.yml).
2. Unzip and run **`OpsWatch.exe`**.
3. Choose **"This computer is the server"** or **"Connect to a server"**.
4. Sign in with **`admin1` / `admin1`** and change the password in the profile.

Run as a Windows service (elevated command prompt):

```bat
OpsWatchServer.exe install
OpsWatchServer.exe start
```

## Install from source

```bash
pip install "git+https://github.com/artemalekseev926-byte/win.git"
opswatch run
```

Open http://127.0.0.1:8765 (login `admin1`, password `admin1`).

### Docker

```bash
git clone https://github.com/artemalekseev926-byte/win.git opswatch && cd opswatch
docker compose up -d
```

## Integrations

**Zabbix**: create a source "Zabbix (webhook)", copy its URL, create a Webhook media type with [`examples/zabbix_webhook.js`](examples/zabbix_webhook.js) and parameters `URL`, `event_id={EVENT.ID}`, `event_value={EVENT.VALUE}`, `severity={EVENT.SEVERITY}`, `host={HOST.NAME}`, `trigger_name={EVENT.NAME}`, `message={ALERT.MESSAGE}`.

**Alertmanager**:

```yaml
receivers:
  - name: opswatch
    webhook_configs:
      - url: "http://opswatch.local:8765/api/ingest/<TOKEN>"
        send_resolved: true
```

**Anything else**:

```bash
curl -X POST "http://opswatch.local:8765/api/ingest/<TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"title":"Disk D: 95%","severity":"critical","category":"monitoring","external_id":"disk-d"}'
```

## Configuration (`.env`)

```ini
OPSWATCH_HOST=0.0.0.0
OPSWATCH_PORT=8765
OPSWATCH_ADMIN_USERNAME=admin1
OPSWATCH_ADMIN_PASSWORD=admin1
OPSWATCH_TELEGRAM_TOKEN=
OPSWATCH_TELEGRAM_API_URL=
OPSWATCH_PUBLIC_URL=
OPSWATCH_DATABASE_URL=
OPSWATCH_SECRET_KEY=
```

SQLite is used by default (`data/opswatch.db`); PostgreSQL is supported via `postgresql+asyncpg://...`. Secrets are encrypted with the key in `data/secret.key` (or `OPSWATCH_SECRET_KEY`) — keep it safe.

## Security

- scrypt password hashes, Fernet encryption for database passwords, bot tokens and archive passwords.
- Secrets are never sent back to the browser.
- Brute-force protection, user blocking, per-source webhook tokens.
- Use read-only database accounts; checks accept only `SELECT`/`WITH`.

## Documentation

- [Architecture, data model and event flow](docs/architecture.md)
- [Writing a connector](docs/connectors.md)

## Development

```bash
pip install -e ".[dev,desktop]"
pytest -q
```

## License

[MIT](LICENSE) © NICE_STUD
