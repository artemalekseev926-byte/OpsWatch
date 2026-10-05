from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Callable

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from opswatch.core.render import esc, truncate
from opswatch.core.router import in_quiet_hours
from opswatch.db import Database, iso, utcnow
from opswatch.i18n import tr
from opswatch.models import ChatMember, ChatMessage, ChatRoom, Role, User
from opswatch.services.queries import event_for_user

log = logging.getLogger(__name__)

MAX_TEXT = 4000
MAX_TITLE = 200
ONLINE_SECONDS = 70
FORWARD_PAUSE = 60
MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9._-]{3,32})")
REPLY_TAG_RE = re.compile(r"#c(\d+)\b")


class ChatError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def display_name(user: User | None) -> str:
    if user is None:
        return ""
    return user.full_name or user.username


def direct_key(a: int, b: int) -> str:
    low, high = sorted((a, b))
    return f"{low}:{high}"


def mentions(text: str) -> set[str]:
    return {m.lower() for m in MENTION_RE.findall(text or "")}


class ChatHub:
    def __init__(self) -> None:
        self.rev = int(time.time())
        self.last_id = 0
        self.seen: dict[int, float] = {}
        self.closing = False
        self._event = asyncio.Event()

    def touch(self, user_id: int) -> None:
        self.seen[user_id] = time.monotonic()

    def online(self, user_id: int) -> bool:
        seen = self.seen.get(user_id)
        return seen is not None and time.monotonic() - seen < ONLINE_SECONDS

    def publish(self, message_id: int | None = None, structural: bool = False) -> None:
        if message_id:
            self.last_id = max(self.last_id, message_id)
        if structural:
            self.rev += 1
        event, self._event = self._event, asyncio.Event()
        event.set()

    def waiter(self) -> asyncio.Event:
        return self._event


class ChatService:
    def __init__(self, db: Database, settings, crypto, bot_getter: Callable[[], Any]) -> None:
        self.db = db
        self.settings = settings
        self.crypto = crypto
        self.bot_getter = bot_getter
        self.hub = ChatHub()
        self._forwarded: dict[tuple[int, int], float] = {}
        self._tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        async with self.db.session() as session:
            self.hub.last_id = await session.scalar(select(func.max(ChatMessage.id))) or 0

    def close(self) -> None:
        self.hub.closing = True
        self.hub.publish(structural=True)

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        self.close()

    async def flush(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def enabled(self) -> bool:
        return bool(self.settings.get("chat_enabled"))

    def check_enabled(self) -> None:
        if not self.enabled():
            raise ChatError(403, tr("Чат отключён администратором"))

    async def _member(self, session: AsyncSession, room_id: int, user_id: int) -> ChatMember | None:
        return await session.scalar(select(ChatMember).where(ChatMember.room_id == room_id, ChatMember.user_id == user_id))

    async def _room_for(self, session: AsyncSession, user: User, room_id: int) -> tuple[ChatRoom, ChatMember]:
        room = await session.get(ChatRoom, room_id)
        member = await self._member(session, room_id, user.id) if room else None
        if room is None or member is None:
            raise ChatError(404, tr("Чат не найден"))
        return room, member

    def _can_manage(self, user: User, room: ChatRoom, member: ChatMember | None) -> bool:
        if room.kind != "group":
            return False
        return bool(user.is_superuser or (member is not None and member.is_admin))

    async def _active_users(self, session: AsyncSession, ids: list[int] | set[int]) -> list[User]:
        ids = {int(i) for i in ids if i}
        if not ids:
            return []
        return list((await session.execute(select(User).where(User.id.in_(ids), User.status == "active"))).scalars().unique().all())

    async def _users_with_roles(self, session: AsyncSession, roles: list[str]) -> list[User]:
        if not roles:
            return []
        rows = await session.execute(
            select(User).join(Role, User.role_id == Role.id).where(Role.name.in_(roles), User.status == "active")
        )
        return list(rows.scalars().unique().all())

    async def _names(self, session: AsyncSession, ids: set[int]) -> dict[int, str]:
        ids = {i for i in ids if i}
        if not ids:
            return {}
        rows = (await session.execute(select(User.id, User.full_name, User.username).where(User.id.in_(ids)))).all()
        return {row[0]: row[1] or row[2] for row in rows}

    async def _clean_roles(self, session: AsyncSession, roles: list[str]) -> list[str]:
        wanted = [str(r) for r in roles or [] if r]
        if not wanted:
            return []
        known = set((await session.execute(select(Role.name).where(Role.name.in_(wanted)))).scalars().all())
        return [r for r in dict.fromkeys(wanted) if r in known]

    def _system(self, session: AsyncSession, room: ChatRoom, actor: User | None, code: str, **data: Any) -> ChatMessage:
        message = ChatMessage(
            room_id=room.id,
            user_id=actor.id if actor else None,
            kind="system",
            text="",
            data={"code": code, "who": display_name(actor), **data},
            created_at=utcnow(),
        )
        session.add(message)
        return message

    def message_dict(self, message: ChatMessage, names: dict[int, str]) -> dict[str, Any]:
        return {
            "id": message.id,
            "room_id": message.room_id,
            "user_id": message.user_id,
            "author": names.get(message.user_id, "") if message.user_id else "",
            "kind": message.kind,
            "text": "" if message.deleted else message.text,
            "data": {} if message.deleted and message.kind != "system" else (message.data or {}),
            "event_id": None if message.deleted else message.event_id,
            "created_at": iso(message.created_at),
            "edited_at": iso(message.edited_at),
            "deleted": message.deleted,
        }

    async def contacts(self, user: User) -> list[dict[str, Any]]:
        self.check_enabled()
        async with self.db.session() as session:
            users = (
                await session.execute(select(User).where(User.status == "active", User.id != user.id).order_by(User.full_name, User.username))
            ).scalars().unique().all()
            return [self.contact_dict(u) for u in users]

    def contact_dict(self, user: User) -> dict[str, Any]:
        return {
            "id": user.id,
            "name": display_name(user),
            "username": user.username,
            "role": user.role.name if user.role else "",
            "role_title": tr(user.role.title) if user.role else "",
            "online": self.hub.online(user.id),
        }

    async def _unread_by_room(self, session: AsyncSession, user_id: int) -> dict[int, int]:
        rows = await session.execute(
            select(ChatMember.room_id, func.count(ChatMessage.id))
            .join(ChatMessage, and_(ChatMessage.room_id == ChatMember.room_id, ChatMessage.id > ChatMember.last_read_id))
            .where(
                ChatMember.user_id == user_id,
                or_(ChatMessage.user_id != user_id, ChatMessage.user_id.is_(None)),
                ChatMessage.deleted.is_(False),
                ChatMessage.kind != "system",
            )
            .group_by(ChatMember.room_id)
        )
        return {room_id: count for room_id, count in rows.all()}

    async def unread_total(self, user: User) -> int:
        if not self.enabled():
            return 0
        async with self.db.session() as session:
            unread = await self._unread_by_room(session, user.id)
            muted = set(
                (await session.execute(select(ChatMember.room_id).where(ChatMember.user_id == user.id, ChatMember.muted.is_(True)))).scalars().all()
            )
        return sum(count for room_id, count in unread.items() if room_id not in muted)

    async def _room_payloads(self, session: AsyncSession, user: User, rooms: list[ChatRoom]) -> list[dict[str, Any]]:
        if not rooms:
            return []
        ids = [r.id for r in rooms]
        members = (await session.execute(select(ChatMember).where(ChatMember.room_id.in_(ids)))).scalars().all()
        by_room: dict[int, list[ChatMember]] = {}
        for m in members:
            by_room.setdefault(m.room_id, []).append(m)
        last_ids = dict(
            (await session.execute(select(ChatMessage.room_id, func.max(ChatMessage.id)).where(ChatMessage.room_id.in_(ids)).group_by(ChatMessage.room_id))).all()
        )
        last_messages = {}
        if last_ids:
            rows = (await session.execute(select(ChatMessage).where(ChatMessage.id.in_(list(last_ids.values()))))).scalars().all()
            last_messages = {m.room_id: m for m in rows}
        peer_ids = set()
        for room in rooms:
            if room.kind == "direct":
                peer_ids.update(m.user_id for m in by_room.get(room.id, []) if m.user_id != user.id)
        peers = {u.id: u for u in (await session.execute(select(User).where(User.id.in_(peer_ids)))).scalars().unique().all()} if peer_ids else {}
        names = await self._names(session, {m.user_id for m in last_messages.values() if m.user_id})
        unread = await self._unread_by_room(session, user.id)
        result = []
        for room in rooms:
            room_members = by_room.get(room.id, [])
            mine = next((m for m in room_members if m.user_id == user.id), None)
            data = {
                "id": room.id,
                "kind": room.kind,
                "title": room.title,
                "description": room.description,
                "roles": list(room.roles or []),
                "member_count": len(room_members),
                "is_admin": bool(mine and mine.is_admin),
                "can_manage": self._can_manage(user, room, mine),
                "muted": bool(mine and mine.muted),
                "last_read_id": mine.last_read_id if mine else 0,
                "unread": unread.get(room.id, 0),
                "last_message": self.message_dict(last_messages[room.id], names) if room.id in last_messages else None,
                "last_message_at": iso(room.last_message_at),
                "created_at": iso(room.created_at),
                "peer": None,
                "peer_read_id": 0,
            }
            if room.kind == "direct":
                other = next((m for m in room_members if m.user_id != user.id), None)
                peer = peers.get(other.user_id) if other else None
                if peer is not None:
                    data["peer"] = self.contact_dict(peer) | {"status": peer.status}
                    data["title"] = display_name(peer)
                    data["peer_read_id"] = other.last_read_id
                else:
                    data["title"] = data["title"] or tr("Удалённый пользователь")
            result.append(data)
        return result

    async def rooms(self, user: User) -> dict[str, Any]:
        self.check_enabled()
        self.hub.touch(user.id)
        async with self.db.session() as session:
            rooms = (
                await session.execute(
                    select(ChatRoom)
                    .join(ChatMember, ChatMember.room_id == ChatRoom.id)
                    .where(ChatMember.user_id == user.id)
                    .order_by(ChatRoom.last_message_at.desc(), ChatRoom.id.desc())
                )
            ).scalars().all()
            items = await self._room_payloads(session, user, list(rooms))
        unread = sum(item["unread"] for item in items if not item["muted"])
        return {"items": items, "rev": self.hub.rev, "last_id": self.hub.last_id, "unread": unread}

    async def room(self, user: User, room_id: int) -> dict[str, Any]:
        self.check_enabled()
        async with self.db.session() as session:
            room, _ = await self._room_for(session, user, room_id)
            data = (await self._room_payloads(session, user, [room]))[0]
            rows = (
                await session.execute(select(ChatMember, User).join(User, User.id == ChatMember.user_id).where(ChatMember.room_id == room.id))
            ).all()
            members = []
            for member, member_user in rows:
                members.append(
                    self.contact_dict(member_user)
                    | {"is_admin": member.is_admin, "via_role": member.via_role, "status": member_user.status, "me": member_user.id == user.id}
                )
            members.sort(key=lambda m: (not m["is_admin"], m["name"].lower()))
            data["members"] = members
            return data

    async def direct(self, user: User, other_id: int) -> dict[str, Any]:
        self.check_enabled()
        if other_id == user.id:
            raise ChatError(422, tr("Нельзя начать чат с самим собой"))
        key = direct_key(user.id, other_id)
        async with self.db.session() as session:
            room = await session.scalar(select(ChatRoom).where(ChatRoom.direct_key == key))
            if room is None:
                others = await self._active_users(session, [other_id])
                if not others:
                    raise ChatError(404, tr("Пользователь не найден"))
                room = ChatRoom(kind="direct", direct_key=key, created_by_id=user.id, last_message_at=utcnow())
                session.add(room)
                await session.flush()
                session.add_all([ChatMember(room_id=room.id, user_id=user.id), ChatMember(room_id=room.id, user_id=other_id)])
                await session.commit()
                self.hub.publish(structural=True)
            room_id = room.id
        return await self.room(user, room_id)

    async def create_group(
        self,
        user: User,
        title: str,
        description: str = "",
        user_ids: list[int] | None = None,
        roles: list[str] | None = None,
        sync_roles: bool = True,
    ) -> dict[str, Any]:
        self.check_enabled()
        title = (title or "").strip()[:MAX_TITLE]
        if not title:
            raise ChatError(422, tr("Укажите название группы"))
        async with self.db.session() as session:
            roles = await self._clean_roles(session, roles or [])
            room = ChatRoom(
                kind="group",
                title=title,
                description=(description or "").strip()[:2000],
                roles=roles if sync_roles else [],
                created_by_id=user.id,
                last_message_at=utcnow(),
            )
            session.add(room)
            await session.flush()
            session.add(ChatMember(room_id=room.id, user_id=user.id, is_admin=True))
            self._system(session, room, user, "created", title=title)
            added = await self._add(session, room, {user.id}, user_ids or [], roles, sync_roles)
            if added:
                self._system(session, room, user, "added", names=added, roles=roles)
            await session.commit()
            room_id = room.id
        self.hub.publish(await self._max_id(), structural=True)
        return await self.room(user, room_id)

    async def _max_id(self) -> int:
        async with self.db.session() as session:
            return await session.scalar(select(func.max(ChatMessage.id))) or 0

    async def _add(
        self,
        session: AsyncSession,
        room: ChatRoom,
        existing: set[int],
        user_ids: list[int],
        roles: list[str],
        sync_roles: bool,
    ) -> list[str]:
        added: list[str] = []
        for member_user in await self._active_users(session, user_ids):
            if member_user.id in existing:
                continue
            session.add(ChatMember(room_id=room.id, user_id=member_user.id))
            existing.add(member_user.id)
            added.append(display_name(member_user))
        for member_user in await self._users_with_roles(session, roles):
            if member_user.id in existing:
                continue
            via = member_user.role.name if sync_roles and member_user.role else ""
            session.add(ChatMember(room_id=room.id, user_id=member_user.id, via_role=via))
            existing.add(member_user.id)
            added.append(display_name(member_user))
        return added

    async def _manageable(self, session: AsyncSession, user: User, room_id: int) -> tuple[ChatRoom, ChatMember | None]:
        room = await session.get(ChatRoom, room_id)
        member = await self._member(session, room_id, user.id) if room else None
        if room is None or (member is None and not user.is_superuser):
            raise ChatError(404, tr("Чат не найден"))
        if not self._can_manage(user, room, member):
            raise ChatError(403, tr("Изменять группу могут только её администраторы"))
        return room, member

    async def update_group(
        self,
        user: User,
        room_id: int,
        title: str | None = None,
        description: str | None = None,
        roles: list[str] | None = None,
        sync_roles: bool | None = None,
    ) -> dict[str, Any]:
        self.check_enabled()
        async with self.db.session() as session:
            room, _ = await self._manageable(session, user, room_id)
            if title is not None:
                clean = title.strip()[:MAX_TITLE]
                if not clean:
                    raise ChatError(422, tr("Укажите название группы"))
                if clean != room.title:
                    room.title = clean
                    self._system(session, room, user, "renamed", title=clean)
            if description is not None:
                room.description = description.strip()[:2000]
            if roles is not None or sync_roles is not None:
                sync = sync_roles if sync_roles is not None else bool(room.roles)
                requested = await self._clean_roles(session, roles if roles is not None else list(room.roles or []))
                if sync:
                    removed, added = await self._apply_roles(session, room, requested)
                else:
                    removed = []
                    members = (await session.execute(select(ChatMember).where(ChatMember.room_id == room.id))).scalars().all()
                    for member in members:
                        member.via_role = ""
                    room.roles = []
                    added = await self._add(session, room, {m.user_id for m in members}, [], requested, False)
                if added:
                    self._system(session, room, user, "added", names=added, roles=requested)
                if removed:
                    self._system(session, room, user, "removed", names=removed)
            await session.commit()
        self.hub.publish(await self._max_id(), structural=True)
        return await self.room(user, room_id)

    async def _apply_roles(self, session: AsyncSession, room: ChatRoom, roles: list[str]) -> tuple[list[str], list[str]]:
        room.roles = roles
        removed: list[str] = []
        rows = (
            await session.execute(select(ChatMember, User).join(User, User.id == ChatMember.user_id).where(ChatMember.room_id == room.id))
        ).all()
        existing = set()
        for member, member_user in rows:
            if member.via_role and member.via_role not in roles and not member.is_admin:
                await session.delete(member)
                removed.append(display_name(member_user))
                continue
            existing.add(member.user_id)
        added = await self._add(session, room, existing, [], roles, True)
        return removed, added

    async def add_members(self, user: User, room_id: int, user_ids: list[int] | None = None, roles: list[str] | None = None, sync_roles: bool = False) -> dict[str, Any]:
        self.check_enabled()
        async with self.db.session() as session:
            room, _ = await self._manageable(session, user, room_id)
            clean_roles = await self._clean_roles(session, roles or [])
            existing = set((await session.execute(select(ChatMember.user_id).where(ChatMember.room_id == room.id))).scalars().all())
            added = await self._add(session, room, existing, user_ids or [], clean_roles, sync_roles)
            if sync_roles and clean_roles:
                room.roles = list(dict.fromkeys(list(room.roles or []) + clean_roles))
            if added:
                self._system(session, room, user, "added", names=added, roles=clean_roles)
            await session.commit()
        self.hub.publish(await self._max_id(), structural=True)
        return await self.room(user, room_id)

    async def remove_member(self, user: User, room_id: int, target_id: int) -> dict[str, Any] | None:
        self.check_enabled()
        async with self.db.session() as session:
            room = await session.get(ChatRoom, room_id)
            if room is None or room.kind != "group":
                raise ChatError(404, tr("Чат не найден"))
            own = await self._member(session, room_id, user.id)
            if target_id != user.id and not self._can_manage(user, room, own):
                raise ChatError(403, tr("Изменять группу могут только её администраторы"))
            target = await self._member(session, room_id, target_id)
            if target is None:
                raise ChatError(404, tr("Участник не найден"))
            target_user = await session.get(User, target_id)
            await session.delete(target)
            await session.flush()
            remaining = (
                await session.execute(select(ChatMember).where(ChatMember.room_id == room_id).order_by(ChatMember.joined_at, ChatMember.id))
            ).scalars().all()
            if not remaining:
                await session.delete(room)
                await session.commit()
                self.hub.publish(structural=True)
                return None
            if not any(m.is_admin for m in remaining):
                remaining[0].is_admin = True
                remaining[0].via_role = ""
            if target_id == user.id:
                self._system(session, room, user, "left")
            else:
                self._system(session, room, user, "removed", names=[display_name(target_user)])
            await session.commit()
        self.hub.publish(await self._max_id(), structural=True)
        if target_id == user.id:
            return None
        return await self.room(user, room_id)

    async def set_admin(self, user: User, room_id: int, target_id: int, is_admin: bool) -> dict[str, Any]:
        self.check_enabled()
        async with self.db.session() as session:
            await self._manageable(session, user, room_id)
            target = await self._member(session, room_id, target_id)
            if target is None:
                raise ChatError(404, tr("Участник не найден"))
            if not is_admin:
                admins = (
                    await session.scalar(select(func.count(ChatMember.id)).where(ChatMember.room_id == room_id, ChatMember.is_admin.is_(True)))
                ) or 0
                if target.is_admin and admins <= 1:
                    raise ChatError(422, tr("В группе должен остаться хотя бы один администратор"))
            target.is_admin = is_admin
            if is_admin:
                target.via_role = ""
            await session.commit()
        self.hub.publish(structural=True)
        return await self.room(user, room_id)

    async def set_muted(self, user: User, room_id: int, muted: bool) -> dict[str, Any]:
        self.check_enabled()
        async with self.db.session() as session:
            _, member = await self._room_for(session, user, room_id)
            member.muted = muted
            await session.commit()
        self.hub.publish(structural=True)
        return await self.room(user, room_id)

    async def delete_room(self, user: User, room_id: int) -> None:
        self.check_enabled()
        async with self.db.session() as session:
            room, _ = await self._manageable(session, user, room_id)
            await session.delete(room)
            await session.commit()
        self.hub.publish(structural=True)

    async def messages(self, user: User, room_id: int, before: int | None = None, limit: int = 50) -> dict[str, Any]:
        self.check_enabled()
        self.hub.touch(user.id)
        limit = max(1, min(int(limit or 50), 200))
        async with self.db.session() as session:
            await self._room_for(session, user, room_id)
            query = select(ChatMessage).where(ChatMessage.room_id == room_id)
            if before:
                query = query.where(ChatMessage.id < before)
            rows = list((await session.execute(query.order_by(ChatMessage.id.desc()).limit(limit + 1))).scalars().all())
            has_more = len(rows) > limit
            rows = list(reversed(rows[:limit]))
            names = await self._names(session, {m.user_id for m in rows if m.user_id})
            return {"items": [self.message_dict(m, names) for m in rows], "has_more": has_more}

    async def post(self, user: User, room_id: int, text: str, event_id: int | None = None, source: str = "web") -> dict[str, Any]:
        self.check_enabled()
        self.hub.touch(user.id)
        text = (text or "").strip()
        if len(text) > MAX_TEXT:
            raise ChatError(422, tr("Сообщение длиннее {limit} символов", limit=MAX_TEXT))
        if not text and not event_id:
            raise ChatError(422, tr("Пустое сообщение"))
        async with self.db.session() as session:
            room, member = await self._room_for(session, user, room_id)
            data: dict[str, Any] = {}
            kind = "text"
            if event_id:
                event = await event_for_user(session, event_id, user)
                if event is None:
                    raise ChatError(404, tr("Событие не найдено"))
                kind = "event"
                data["event"] = {
                    "id": event.id,
                    "title": event.title,
                    "severity": event.severity,
                    "category": event.category,
                    "status": event.status,
                    "source_name": event.source_name,
                }
            if source != "web":
                data["via"] = source
            now = utcnow()
            message = ChatMessage(room_id=room.id, user_id=user.id, kind=kind, text=text, data=data, event_id=event_id, created_at=now)
            session.add(message)
            room.last_message_at = now
            await session.flush()
            member.last_read_id = message.id
            await session.commit()
            names = {user.id: display_name(user)}
            payload = self.message_dict(message, names)
            message_id = message.id
        self.hub.publish(message_id)
        task = asyncio.create_task(self._forward(room_id, message_id, user.id), name=f"opswatch-chat-forward-{message_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return payload

    async def edit(self, user: User, message_id: int, text: str) -> dict[str, Any]:
        self.check_enabled()
        text = (text or "").strip()
        if not text:
            raise ChatError(422, tr("Пустое сообщение"))
        if len(text) > MAX_TEXT:
            raise ChatError(422, tr("Сообщение длиннее {limit} символов", limit=MAX_TEXT))
        async with self.db.session() as session:
            message = await session.get(ChatMessage, message_id)
            if message is None or await self._member(session, message.room_id, user.id) is None:
                raise ChatError(404, tr("Сообщение не найдено"))
            if message.user_id != user.id or message.kind == "system" or message.deleted:
                raise ChatError(403, tr("Изменять можно только свои сообщения"))
            message.text = text
            message.edited_at = utcnow()
            await session.commit()
            payload = self.message_dict(message, {user.id: display_name(user)})
        self.hub.publish(structural=True)
        return payload

    async def delete_message(self, user: User, message_id: int) -> dict[str, Any]:
        self.check_enabled()
        async with self.db.session() as session:
            message = await session.get(ChatMessage, message_id)
            member = await self._member(session, message.room_id, user.id) if message else None
            if message is None or member is None:
                raise ChatError(404, tr("Сообщение не найдено"))
            room = await session.get(ChatRoom, message.room_id)
            if message.kind == "system" or (message.user_id != user.id and not self._can_manage(user, room, member)):
                raise ChatError(403, tr("Удалять можно только свои сообщения"))
            message.deleted = True
            message.text = ""
            message.edited_at = utcnow()
            await session.commit()
            payload = self.message_dict(message, {})
        self.hub.publish(structural=True)
        return payload

    async def mark_read(self, user: User, room_id: int, last_id: int | None = None) -> int:
        self.check_enabled()
        async with self.db.session() as session:
            _, member = await self._room_for(session, user, room_id)
            newest = await session.scalar(select(func.max(ChatMessage.id)).where(ChatMessage.room_id == room_id)) or 0
            target = min(int(last_id), newest) if last_id else newest
            if target > member.last_read_id:
                member.last_read_id = target
                await session.commit()
                self.hub.publish(structural=True)
            return member.last_read_id

    async def _new_messages(self, session: AsyncSession, user: User, after: int, limit: int = 200) -> list[ChatMessage]:
        return list(
            (
                await session.execute(
                    select(ChatMessage)
                    .join(ChatMember, and_(ChatMember.room_id == ChatMessage.room_id, ChatMember.user_id == user.id))
                    .where(ChatMessage.id > after)
                    .order_by(ChatMessage.id)
                    .limit(limit)
                )
            ).scalars().all()
        )

    async def updates(self, user: User, after: int = 0, rev: int | None = None, timeout: float = 25.0) -> dict[str, Any]:
        self.check_enabled()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, min(float(timeout), 30.0))
        while True:
            self.hub.touch(user.id)
            waiter = self.hub.waiter()
            async with self.db.session() as session:
                rows = await self._new_messages(session, user, after) if after >= 0 else []
                names = await self._names(session, {m.user_id for m in rows if m.user_id})
            changed = rev is not None and rev != self.hub.rev
            remaining = deadline - loop.time()
            if rows or changed or remaining <= 0 or self.hub.closing:
                break
            try:
                await asyncio.wait_for(waiter.wait(), remaining)
            except asyncio.TimeoutError:
                continue
        last_id = max([after, self.hub.last_id] + [m.id for m in rows])
        return {
            "messages": [self.message_dict(m, names) for m in rows],
            "rev": self.hub.rev,
            "last_id": last_id,
            "unread": await self.unread_total(user),
        }

    async def desktop_items(self, user: User, after: int) -> list[dict[str, Any]]:
        if not self.enabled() or after < 0:
            return []
        async with self.db.session() as session:
            rows = (
                await session.execute(
                    select(ChatMessage, ChatRoom)
                    .join(ChatRoom, ChatRoom.id == ChatMessage.room_id)
                    .join(ChatMember, and_(ChatMember.room_id == ChatMessage.room_id, ChatMember.user_id == user.id))
                    .where(
                        ChatMessage.id > after,
                        ChatMessage.user_id != user.id,
                        ChatMessage.kind != "system",
                        ChatMessage.deleted.is_(False),
                        ChatMember.muted.is_(False),
                    )
                    .order_by(ChatMessage.id)
                    .limit(10)
                )
            ).all()
            names = await self._names(session, {m.user_id for m, _ in rows if m.user_id})
        items = []
        for message, room in rows:
            author = names.get(message.user_id, "")
            title = author if room.kind == "direct" else f"{author} · {room.title}"
            body = message.text or (message.data or {}).get("event", {}).get("title", "")
            items.append({"id": message.id, "room_id": room.id, "title": title, "body": truncate(body, 200)})
        return items

    async def sync_user(self, user_id: int) -> None:
        async with self.db.session() as session:
            user = await session.get(User, user_id)
            if user is None:
                return
            role = user.role.name if user.role and user.status == "active" else ""
            rooms = (await session.execute(select(ChatRoom).where(ChatRoom.kind == "group"))).scalars().all()
            changed = False
            for room in rooms:
                roles = list(room.roles or [])
                member = await self._member(session, room.id, user.id)
                wanted = bool(role) and role in roles
                if wanted and member is None:
                    session.add(ChatMember(room_id=room.id, user_id=user.id, via_role=role))
                    self._system(session, room, None, "auto_added", names=[display_name(user)], role=role)
                    changed = True
                elif member is not None and member.via_role and not member.is_admin:
                    if not wanted:
                        await session.delete(member)
                        self._system(session, room, None, "auto_removed", names=[display_name(user)])
                        changed = True
                    elif member.via_role != role:
                        member.via_role = role
                        changed = True
            if changed:
                await session.commit()
        if changed:
            self.hub.publish(await self._max_id(), structural=True)

    async def _forward(self, room_id: int, message_id: int, sender_id: int) -> None:
        try:
            await self._forward_inner(room_id, message_id, sender_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("chat forward failed", exc_info=True)

    async def _forward_inner(self, room_id: int, message_id: int, sender_id: int) -> None:
        bot = self.bot_getter()
        async with self.db.session() as session:
            room = await session.get(ChatRoom, room_id)
            message = await session.get(ChatMessage, message_id)
            sender = await session.get(User, sender_id)
            if room is None or message is None or sender is None or message.deleted:
                return
            rows = (
                await session.execute(
                    select(ChatMember, User).join(User, User.id == ChatMember.user_id).where(ChatMember.room_id == room_id, ChatMember.user_id != sender_id)
                )
            ).all()
            mentioned = mentions(message.text)
            public_url = (self.settings.get("public_url") or "").rstrip("/")
            now = time.monotonic()
            for member, user in rows:
                if user.status != "active" or member.muted or not user.chat_telegram or not user.notify_telegram:
                    continue
                if room.kind != "direct" and user.username.lower() not in mentioned:
                    continue
                if self.hub.online(user.id):
                    continue
                key = (user.id, room_id)
                if now - self._forwarded.get(key, -FORWARD_PAUSE) < FORWARD_PAUSE:
                    continue
                personal_token = self.crypto.decrypt(user.personal_bot_token or "")
                use_personal = bool(personal_token and user.personal_chat_id)
                if not use_personal and (bot is None or not bot.available or not user.telegram_chat_id):
                    continue
                lang = user.language or "ru"
                header = f"💬 <b>{esc(display_name(sender))}</b>"
                if room.kind != "direct":
                    header += f" · {esc(room.title)}"
                body = message.text or (message.data or {}).get("event", {}).get("title", "")
                lines = [header, esc(truncate(body, 1500))]
                if not use_personal:
                    lines.append("")
                    lines.append(f"<i>{esc(tr('Ответьте на это сообщение, чтобы написать в чат', lang))}</i> #c{room_id}")
                text = "\n".join(lines)
                keyboard = [[{"text": tr("Открыть чат", lang), "url": f"{public_url}/#/chat/{room_id}"}]] if public_url else None
                silent = in_quiet_hours(user)
                try:
                    if use_personal:
                        await bot.send_personal(personal_token, user.personal_chat_id, text, keyboard, silent)
                    else:
                        await bot.send(user.telegram_chat_id, text, keyboard, silent)
                    self._forwarded[key] = now
                except Exception:
                    log.warning("chat forward to user %s failed", user.id, exc_info=True)

    async def post_from_telegram(self, chat_id: int, room_id: int, text: str) -> dict[str, Any]:
        async with self.db.session() as session:
            user = await session.scalar(select(User).where(User.telegram_chat_id == chat_id))
        if user is None or user.status != "active":
            raise ChatError(403, tr("Сначала привяжите подтверждённый аккаунт OpsWatch (/start)."))
        message = await self.post(user, room_id, text, source="telegram")
        async with self.db.session() as session:
            room = await session.get(ChatRoom, room_id)
            title = room.title if room and room.kind == "group" else ""
        return {"message": message, "title": title}


def reply_room(text: str | None) -> int | None:
    match = REPLY_TAG_RE.search(text or "")
    return int(match.group(1)) if match else None
