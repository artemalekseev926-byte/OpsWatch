from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from opswatch import APP_NAME, __version__
from opswatch.config import AppConfig, app_dir
from opswatch.logs import ensure_streams, setup_logging

ENV_TEMPLATE = """OPSWATCH_HOST=0.0.0.0
OPSWATCH_PORT=8765
OPSWATCH_ADMIN_USERNAME=admin1
OPSWATCH_ADMIN_PASSWORD=admin1
OPSWATCH_TELEGRAM_TOKEN=
OPSWATCH_TELEGRAM_API_URL=
OPSWATCH_PUBLIC_URL=
OPSWATCH_DATABASE_URL=
OPSWATCH_SECRET_KEY=
OPSWATCH_LOG_LEVEL=INFO
"""


def _config(args) -> AppConfig:
    overrides = {}
    if getattr(args, "data_dir", None):
        overrides["data_dir"] = Path(args.data_dir)
    env = Path(args.env) if getattr(args, "env", None) else None
    return AppConfig.load(env, **overrides)


def cmd_run(args) -> int:
    from opswatch.server import run_server

    config = _config(args)
    setup_logging(config.logs_dir, config.log_level)
    run_server(config, args.host, args.port)
    return 0


def cmd_init(args) -> int:
    target = Path(args.env) if args.env else app_dir() / ".env"
    if target.exists() and not args.force:
        print(f"{target} уже существует (используйте --force)")
        return 1
    target.write_text(ENV_TEMPLATE, encoding="utf-8")
    print(f"Создан {target}")
    return 0


def cmd_reset_password(args) -> int:
    from sqlalchemy import func, select

    from opswatch.db import Database
    from opswatch.models import User
    from opswatch.security import hash_password

    config = _config(args)

    async def run() -> bool:
        db = Database(config.database_url)
        await db.create_all()
        async with db.session() as session:
            user = await session.scalar(select(User).where(func.lower(User.username) == args.username.lower()))
            if user is None:
                await db.dispose()
                return False
            user.password_hash = hash_password(args.password)
            if user.status == "blocked":
                user.status = "active"
            await session.commit()
        await db.dispose()
        return True

    if asyncio.run(run()):
        print("Пароль изменён")
        return 0
    print("Пользователь не найден")
    return 1


def cmd_desktop(args) -> int:
    from opswatch.desktop.launcher import main as desktop_main

    return desktop_main(args.rest)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opswatch", description=f"{APP_NAME} {__version__}")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Запустить сервер (веб-панель, бот, планировщик)")
    run.add_argument("--host")
    run.add_argument("--port", type=int)
    run.add_argument("--env")
    run.add_argument("--data-dir")
    run.set_defaults(func=cmd_run)

    init = sub.add_parser("init", help="Создать .env с настройками по умолчанию")
    init.add_argument("--env")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    reset = sub.add_parser("reset-password", help="Сбросить пароль пользователя")
    reset.add_argument("username")
    reset.add_argument("password")
    reset.add_argument("--env")
    reset.add_argument("--data-dir")
    reset.set_defaults(func=cmd_reset_password)

    desktop = sub.add_parser("desktop", help="Запустить настольное приложение")
    desktop.add_argument("rest", nargs=argparse.REMAINDER)
    desktop.set_defaults(func=cmd_desktop)
    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args(["run"] + (argv or sys.argv[1:]))
    return args.func(args) or 0
