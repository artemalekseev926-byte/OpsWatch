from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any

from opswatch.backup.archive import split_file
from opswatch.core.render import esc
from opswatch.i18n import ts
from opswatch.sizes import human_size

log = logging.getLogger(__name__)

MB = 1024 * 1024
LOCAL_API_LIMIT_MB = 1990


def copy_to_folder(archive: Path, folder: str) -> str:
    target_dir = Path(folder)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / archive.name
    shutil.copy2(archive, target)
    return str(target)


def upload_s3(archive: Path, settings) -> str:
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError(ts("Для выгрузки в S3 установите пакет boto3")) from exc
    bucket = settings.get("s3_bucket")
    if not bucket:
        raise RuntimeError(ts("Не указан S3 bucket в настройках"))
    client = boto3.client(
        "s3",
        endpoint_url=settings.get("s3_endpoint") or None,
        region_name=settings.get("s3_region") or None,
        aws_access_key_id=settings.get("s3_access_key") or None,
        aws_secret_access_key=settings.get("s3_secret_key") or None,
    )
    key = (settings.get("s3_prefix") or "") + archive.name
    client.upload_file(str(archive), bucket, key)
    days = max(1, min(7, int(settings.get("s3_link_days") or 7)))
    return client.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=days * 86400
    )


def part_limit(settings) -> int:
    if settings.get("telegram_api_url"):
        return LOCAL_API_LIMIT_MB * MB
    return max(1, min(49, int(settings.get("telegram_part_mb") or 49))) * MB


async def send_to_telegram(
    bot,
    crypto,
    users: list,
    archive: Path,
    caption: str,
    settings,
    tmp_dir: Path,
    links: list[str],
    allow_split: bool = True,
) -> dict[str, Any]:
    stats = {"sent": 0, "failed": 0, "mode": "file", "recipients": []}
    has_personal = any(u.personal_bot_token and u.personal_chat_id for u in users)
    if bot is None or (not bot.available and not has_personal):
        stats["mode"] = "no_bot"
        return stats
    size = archive.stat().st_size
    limit = part_limit(settings)
    parts: list[Path] = []
    if size > limit:
        if links:
            stats["mode"] = "link"
        elif allow_split:
            stats["mode"] = "parts"
            parts = await asyncio.to_thread(split_file, archive, limit, tmp_dir)
        else:
            stats["mode"] = "path"
    try:
        for user in users:
            token = crypto.decrypt(user.personal_bot_token or "") if user.personal_bot_token else ""
            personal = bool(token and user.personal_chat_id)
            chat_id = user.personal_chat_id if personal else user.telegram_chat_id
            if not chat_id or (not personal and not bot.available):
                continue
            try:
                if stats["mode"] == "file":
                    await bot.send_file(chat_id, archive, caption, token if personal else None)
                elif stats["mode"] == "parts":
                    total = len(parts)
                    for index, part in enumerate(parts, 1):
                        part_caption = ts("{caption}\nЧасть {index}/{total}", caption=caption, index=index, total=total) if index == 1 else ts("Часть {index}/{total}", index=index, total=total)
                        await bot.send_file(chat_id, part, part_caption, token if personal else None)
                    hint = (
                        ts("Архив разбит на части. Откройте первую часть в 7-Zip или объедините: <code>copy /b {name}.001+{name}.002 {name}</code>", name=esc(archive.name))
                    )
                    await bot.send_text(chat_id, hint, token if personal else None)
                elif stats["mode"] == "link":
                    text = caption + ts("\n\nФайл больше лимита Telegram, ссылка для скачивания:\n") + "\n".join(esc(x) for x in links)
                    await bot.send_text(chat_id, text, token if personal else None)
                else:
                    text = caption + "\n\n" + ts("Файл {size} больше лимита Telegram и сохранён на сервере:", size=human_size(size)) + f"\n<code>{esc(archive)}</code>"
                    await bot.send_text(chat_id, text, token if personal else None)
                stats["sent"] += 1
                stats["recipients"].append(user.username)
            except Exception as exc:
                log.warning(ts("Не удалось отправить бэкап пользователю %s: %s"), user.username, exc)
                stats["failed"] += 1
    finally:
        for part in parts:
            part.unlink(missing_ok=True)
    return stats
