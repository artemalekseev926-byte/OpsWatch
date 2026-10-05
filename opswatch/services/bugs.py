from __future__ import annotations

import mimetypes
import re
import secrets
from pathlib import Path
from typing import Any

from opswatch.core.events import EventIn
from opswatch.i18n import ts
from opswatch.models import Event, User

MAX_ATTACHMENT = 20 * 1024 * 1024
ALLOWED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".txt", ".log", ".pdf", ".zip", ".7z", ".json", ".xml",
    ".csv", ".docx", ".xlsx", ".mxl", ".epf", ".erf",
}


def clean_filename(name: str) -> str:
    name = Path(name or "file").name
    name = re.sub(r"[^\w.\- ()]+", "_", name, flags=re.UNICODE).strip() or "file"
    return name[:150]


def save_attachment(folder: Path, filename: str, content: bytes, content_type: str = "") -> dict[str, Any]:
    if len(content) > MAX_ATTACHMENT:
        raise ValueError(ts("Файл больше 20 МБ"))
    filename = clean_filename(filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(ts("Недопустимый тип файла: {value}", value=suffix or ts("без расширения")))
    folder.mkdir(parents=True, exist_ok=True)
    stored = f"{secrets.token_hex(12)}{suffix}"
    (folder / stored).write_bytes(content)
    return {
        "filename": filename,
        "stored_name": stored,
        "content_type": content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
        "size": len(content),
    }


async def create_bug(
    pipeline,
    title: str,
    text: str,
    reporter: User | None,
    reporter_label: str = "",
    severity: str = "warning",
    attachments: list[dict[str, Any]] | None = None,
    source_id: int | None = None,
    source_name: str = "",
    channel: str = "web",
    extra: dict[str, Any] | None = None,
) -> Event | None:
    text = (text or "").strip()
    title = (title or "").strip() or (text.splitlines()[0][:120] if text else ts("Баг-репорт"))
    who = reporter_label or (reporter.full_name or reporter.username if reporter else ts("аноним"))
    details = {"reporter": who, "channel": channel}
    if extra:
        details.update(extra)
    return await pipeline.ingest(
        EventIn(
            title=title,
            message=text,
            severity=severity,
            category="bug",
            type=f"bug.{channel}",
            source_id=source_id,
            source_name=source_name or ts("Баг-репорт: {who}", who=who),
            details=details,
            fingerprint=secrets.token_hex(16),
            reporter_id=reporter.id if reporter else None,
            attachments=attachments or [],
        )
    )
