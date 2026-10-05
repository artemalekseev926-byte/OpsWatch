# OpsWatch

[![Windows build](https://github.com/artemalekseev926-byte/OpsWatch/actions/workflows/build-windows.yml/badge.svg)](https://github.com/artemalekseev926-byte/OpsWatch/actions/workflows/build-windows.yml)
[![Tests](https://github.com/artemalekseev926-byte/OpsWatch/actions/workflows/tests.yml/badge.svg)](https://github.com/artemalekseev926-byte/OpsWatch/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[Русский](README.md) · **English**

**OpsWatch** is an open-source tool for system administrators and 1C:Enterprise administrators. It watches databases and 1C infobases, runs scheduled backups, receives Zabbix and Prometheus alerts, collects bug reports and routes everything to the right people in Telegram and as desktop notifications.

![Overview](docs/screenshots/en/overview.png)

## Features

- **Databases** — MySQL/MariaDB, PostgreSQL, MS SQL: availability, database size and custom SQL checks (new rows, threshold, rows exist). Read-only `SELECT` queries in read-only transactions.
- **1C:Enterprise** — file infobases (size and lock state of `1Cv8.1CD`, event log `.lgd`/`.lgp`, integrity check via `1cv8 DESIGNER /IBCheckAndRepair` or `chdbfl.exe` only when no users are connected) and server infobases (through the DBMS, the event log and HTTP/OData services).
- **1C server cluster** — through the RAS administration server (`rac` utility): session count, long server calls, DBMS and managed lock waits with the blocking session, worker processes (memory, performance, stopped processes).
- **Metric charts** — history of database size, response time, 1C sessions and other values for 24 hours, 7 and 30 days; sparklines on source cards.
- **Notification templates** — Telegram message text for new events, repeats, escalations and resolutions, editable in the panel with a live preview.
- **Resource monitoring** — Zabbix webhook media type, Prometheus Alertmanager, Zabbix API polling, HTTP(S) checks and a generic webhook. Problems are closed automatically on recovery.
- **Backups** — `mysqldump`, `pg_dump`, MS SQL `BACKUP DATABASE`, 1C file infobase copy (lock check or Windows VSS shadow copy). Cron schedules, AES-256 encrypted zip, integrity verification, rotation, delivery to Telegram (split into parts, local Bot API server up to 2 GB, S3 pre-signed link or network share).
- **Team chat** — direct messages and groups; add members by role at once (the group then follows role changes), `@login` mentions, discuss events right in the chat, instant delivery, desktop notifications, and Telegram forwarding for people who are offline with replies straight from the bot.
- **Bug reports** — web form with screenshots, Telegram `/bug` command with a photo, HTTP API.
- **Routing** — rules "events of type X from source Y with severity ≥ Z → roles/users N", personal subscriptions, quiet hours, deduplication and escalation of unacknowledged critical events.
- **Telegram** — direct messages with "Acknowledge", "Resolved" and "Details" buttons; subscriptions via the bot; optional personal bot per user.
- **Desktop notifications** — the Windows app shows native notifications even when minimized to the tray.
- **Users and permissions** — sign-up from the main window, approval by an administrator, roles and per-source visibility.
- **Storage** — SQLite by default or PostgreSQL; the schema is upgraded automatically with Alembic migrations, data is moved with one command.
- **English and Russian interface** — the language is chosen on the sign-in screen or in the profile; the bot and notifications use each user's language.
- **Plugins** — every source is a connector with a common interface ([how to write one](docs/connectors.md)).

## Quick start (Windows)

1. Download `OpsWatch-<version>-windows-x64.zip` from [Releases](https://github.com/artemalekseev926-byte/OpsWatch/releases) or from the latest [build artifacts](https://github.com/artemalekseev926-byte/OpsWatch/actions/workflows/build-windows.yml).
2. Unzip and run **`OpsWatch.exe`**.
3. Choose **"This computer is the server"** or **"Connect to a server"**.
4. Sign in with **`admin1` / `admin1`** and change the password in the profile.

No Python installation is needed; all data is kept in the `data` folder next to the program. Run as a Windows service (elevated command prompt):

```bat
OpsWatchServer.exe install
OpsWatchServer.exe start
```

## Install from source

```bash
pip install "git+https://github.com/artemalekseev926-byte/OpsWatch.git"
opswatch run
```

Open http://127.0.0.1:8765 (login `admin1`, password `admin1`).

### Docker

```bash
git clone https://github.com/artemalekseev926-byte/OpsWatch.git opswatch && cd opswatch
docker compose up -d
```

With PostgreSQL storage:

```bash
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d
```

## Language

The web panel, desktop app, Windows service, bot and notifications are available in English and Russian. Switch the language on the sign-in screen, in the user menu or in the profile; the choice is also used for your Telegram notifications. The language of texts generated by sources and backups is set in **Settings → System event language**. On first start the language follows the operating system; set it explicitly with `OPSWATCH_LANGUAGE=en` or `ru`.

| | |
| --- | --- |
| ![Sign in](docs/screenshots/en/login.png) | ![Profile](docs/screenshots/en/profile.png) |

## Team chat

The **Chat** tab lets employees reach each other quickly without a third-party messenger.

- **Direct messages**: «Message an employee» or search by name, login or role. You see who is online and, in direct chats, whether your message was read (✓✓).
- **Groups**: «New group» → name → roles (for example, «System administrator» and «1C administrator») — everyone with these roles joins at once. With «Follow roles» on, new employees with these roles join automatically and leave when their role changes. Individual people can be picked manually as well.
- **Management**: group administrators rename the group, change roles, add and remove members and appoint other administrators; any member can mute or leave the group.
- **Mentions**: `@login` is highlighted and suggested after typing `@`.
- **Events in chat**: the «Discuss in chat» button in an event card posts it to the chosen chat; members open the event with one click.
- **Telegram**: when someone is offline, direct messages and mentions are delivered to their Telegram (profile setting «Chat messages in Telegram»). Replying to such a message in the bot posts the reply to the OpsWatch chat.
- **Desktop notifications**: new messages pop up in the Windows app and in the browser; the tab shows the unread counter.
- Messages can be edited (↑ in an empty field edits the last one) and deleted. The chat can be turned off in **Settings**.

![Chat](docs/screenshots/en/chat.png)

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

### 1C server cluster (RAS)

1. Run the 1C administration server on the 1C server, for example as a service:

   ```bat
   sc create "1C:Enterprise RAS" binPath= "\"C:\Program Files\1cv8\8.3.24.1691\bin\ras.exe\" cluster --service --port=1545 localhost:1540" start= auto
   sc start "1C:Enterprise RAS"
   ```

2. **Sources → Add source → "1C: server cluster (RAS)"**: RAS address (`srv1c:1545`), path to `rac.exe` (found automatically when the 1C platform is installed on the OpsWatch computer) and the cluster administrator if one is set.
3. Configure thresholds:

| Event | When |
| --- | --- |
| Long server call | a call in a session runs longer than the threshold (60 s by default); the text names the user, computer and infobase |
| Lock wait | a session waits for a DBMS lock or a managed lock; the text names the blocking session |
| Too many sessions | the session count exceeds the threshold (for example, the number of licenses) |
| Worker process | a process is stopped, uses more memory than the threshold or its performance drops below the threshold |

Events close automatically when the problem disappears. Sessions, the longest call, lock waits and process memory are recorded for charts.

![1C cluster](docs/screenshots/en/onec-cluster.png)

### Metric charts

Database, 1C and HTTP check cards show a 24-hour sparkline. The chart button opens the 24-hour, 7-day or 30-day history of any source value with a hover tooltip and a value table. Values are recorded during polling at most once every 5 minutes and kept for 30 days (**Settings → Keep chart history**).

![Chart](docs/screenshots/en/chart.png)

### Notification templates

**Settings → Notification templates** holds separate templates for new events, repeats, escalations and resolutions in English and Russian. Use `<b>`, `<i>`, `<code>`, `<a href>` tags and placeholders such as `{title}`, `{message}`, `{source}`, `{severity}`, `{time}`, `{count}`, `{link}`. A line whose placeholders are all empty is hidden. Templates are validated on save and can be sent to yourself; if Telegram still rejects a message, the default text is sent instead.

![Templates](docs/screenshots/en/templates.png)

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
OPSWATCH_LANGUAGE=
```

SQLite is used by default (`data/opswatch.db`). Secrets are encrypted with the key in `data/secret.key` (or `OPSWATCH_SECRET_KEY`) — keep it safe.

## PostgreSQL storage and upgrades

To move from SQLite to PostgreSQL, create an empty database, stop OpsWatch and run:

```bat
OpsWatchServer.exe migrate-db postgresql://opswatch:password@db-server/opswatch --write-env
```

On Linux/Docker use `opswatch migrate-db ...`. All data is copied (users, sources, events, backups, metrics); `--write-env` stores the new address in `.env`, `--force` overwrites a non-empty target database. Start OpsWatch again — **Settings** shows the database in use.

**Upgrading**: unzip the new version over the old one (the `data` folder and `.env` are kept) or update the package/image. The schema is upgraded automatically on start with Alembic migrations for SQLite and PostgreSQL, including databases created by version 0.1.0. To upgrade without starting the server: `OpsWatchServer.exe upgrade-db` (`opswatch upgrade-db`). Back up the `data` folder before upgrading.

## Security

- scrypt password hashes, Fernet encryption for database passwords, bot tokens and archive passwords.
- Secrets are never sent back to the browser.
- Brute-force protection, user blocking, per-source webhook tokens.
- Use read-only database accounts; checks accept only `SELECT`/`WITH`.

## Documentation

- [Architecture, data model and event flow](docs/architecture.md) (Russian)
- [Writing a connector](docs/connectors.md) (Russian)
- [Changelog](CHANGELOG.md) (Russian)

## Development

```bash
pip install -e ".[dev,desktop]"
pytest -q
```

Run the whole suite on PostgreSQL with `OPSWATCH_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@127.0.0.1/db_test pytest -q`. Translation completeness is checked by `tests/test_i18n.py`; `python tests/i18n_keys.py` lists strings without an English translation.

## License

[MIT](LICENSE) © NICE_STUD
