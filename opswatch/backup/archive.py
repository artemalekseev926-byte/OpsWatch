from __future__ import annotations

import hashlib
from pathlib import Path

import pyzipper

from opswatch.i18n import ts

CHUNK = 4 * 1024 * 1024


class BackupError(Exception):
    pass


def make_archive(files: list[Path], destination: Path, password: str = "", base: Path | None = None) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".part")
    kwargs = {"compression": pyzipper.ZIP_DEFLATED, "compresslevel": 6, "allowZip64": True}
    if password:
        kwargs["encryption"] = pyzipper.WZ_AES
    with pyzipper.AESZipFile(tmp, "w", **kwargs) as archive:
        if password:
            archive.setpassword(password.encode("utf-8"))
            archive.setencryption(pyzipper.WZ_AES, nbits=256)
        for file in files:
            if base is not None:
                try:
                    name = file.relative_to(base).as_posix()
                except ValueError:
                    name = file.name
            else:
                name = file.name
            archive.write(file, arcname=name)
    tmp.replace(destination)
    return destination


def verify_archive(path: Path, password: str = "") -> int:
    try:
        with pyzipper.AESZipFile(path) as archive:
            if password:
                archive.setpassword(password.encode("utf-8"))
            names = archive.namelist()
            if not names:
                raise BackupError(ts("Архив пуст"))
            bad = archive.testzip()
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError(ts("Архив не прошёл проверку: {exc}", exc=exc)) from exc
    if bad:
        raise BackupError(ts("Архив повреждён: {bad}", bad=bad))
    return len(names)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def split_file(path: Path, part_size: int, target_dir: Path | None = None) -> list[Path]:
    if part_size <= 0:
        raise ValueError("part_size must be positive")
    target_dir = target_dir or path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    with path.open("rb") as source:
        index = 1
        while True:
            written = 0
            part_path = target_dir / f"{path.name}.{index:03d}"
            with part_path.open("wb") as part:
                while written < part_size:
                    chunk = source.read(min(CHUNK, part_size - written))
                    if not chunk:
                        break
                    part.write(chunk)
                    written += len(chunk)
            if written == 0:
                part_path.unlink(missing_ok=True)
                break
            parts.append(part_path)
            index += 1
            if written < part_size:
                break
    return parts


def join_parts(parts: list[Path], destination: Path) -> Path:
    with destination.open("wb") as target:
        for part in sorted(parts):
            with part.open("rb") as source:
                while True:
                    chunk = source.read(CHUNK)
                    if not chunk:
                        break
                    target.write(chunk)
    return destination
