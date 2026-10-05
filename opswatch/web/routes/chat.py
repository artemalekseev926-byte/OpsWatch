from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from opswatch.models import User
from opswatch.services.chat import ChatError
from opswatch.web.deps import active_user, get_rt

router = APIRouter(prefix="/api/chat", tags=["chat"])


class DirectIn(BaseModel):
    user_id: int


class GroupIn(BaseModel):
    title: str
    description: str = ""
    user_ids: list[int] = []
    roles: list[str] = []
    sync_roles: bool = True


class GroupUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    roles: list[str] | None = None
    sync_roles: bool | None = None


class MembersIn(BaseModel):
    user_ids: list[int] = []
    roles: list[str] = []
    sync_roles: bool = False


class MemberUpdate(BaseModel):
    is_admin: bool


class MessageIn(BaseModel):
    text: str = ""
    event_id: int | None = None


class EditIn(BaseModel):
    text: str


class ReadIn(BaseModel):
    last_id: int | None = None


class MuteIn(BaseModel):
    muted: bool


async def call(coro):
    try:
        return await coro
    except ChatError as exc:
        raise HTTPException(exc.status, exc.message) from exc


@router.get("/contacts")
async def contacts(user: User = Depends(active_user), rt=Depends(get_rt)):
    return {"items": await call(rt.chat.contacts(user))}


@router.get("/rooms")
async def rooms(user: User = Depends(active_user), rt=Depends(get_rt)):
    return await call(rt.chat.rooms(user))


@router.post("/direct")
async def direct(data: DirectIn, user: User = Depends(active_user), rt=Depends(get_rt)):
    return await call(rt.chat.direct(user, data.user_id))


@router.post("/rooms")
async def create_group(data: GroupIn, user: User = Depends(active_user), rt=Depends(get_rt)):
    return await call(rt.chat.create_group(user, data.title, data.description, data.user_ids, data.roles, data.sync_roles))


@router.get("/rooms/{room_id}")
async def room(room_id: int, user: User = Depends(active_user), rt=Depends(get_rt)):
    return await call(rt.chat.room(user, room_id))


@router.put("/rooms/{room_id}")
async def update_group(room_id: int, data: GroupUpdate, user: User = Depends(active_user), rt=Depends(get_rt)):
    return await call(rt.chat.update_group(user, room_id, data.title, data.description, data.roles, data.sync_roles))


@router.delete("/rooms/{room_id}")
async def delete_group(room_id: int, user: User = Depends(active_user), rt=Depends(get_rt)):
    await call(rt.chat.delete_room(user, room_id))
    return {"ok": True}


@router.post("/rooms/{room_id}/members")
async def add_members(room_id: int, data: MembersIn, user: User = Depends(active_user), rt=Depends(get_rt)):
    return await call(rt.chat.add_members(user, room_id, data.user_ids, data.roles, data.sync_roles))


@router.put("/rooms/{room_id}/members/{member_id}")
async def update_member(room_id: int, member_id: int, data: MemberUpdate, user: User = Depends(active_user), rt=Depends(get_rt)):
    return await call(rt.chat.set_admin(user, room_id, member_id, data.is_admin))


@router.delete("/rooms/{room_id}/members/{member_id}")
async def remove_member(room_id: int, member_id: int, user: User = Depends(active_user), rt=Depends(get_rt)):
    result = await call(rt.chat.remove_member(user, room_id, member_id))
    return result or {"ok": True, "left": True}


@router.put("/rooms/{room_id}/mute")
async def mute(room_id: int, data: MuteIn, user: User = Depends(active_user), rt=Depends(get_rt)):
    return await call(rt.chat.set_muted(user, room_id, data.muted))


@router.get("/rooms/{room_id}/messages")
async def messages(room_id: int, before: int | None = None, limit: int = 50, user: User = Depends(active_user), rt=Depends(get_rt)):
    return await call(rt.chat.messages(user, room_id, before, limit))


@router.post("/rooms/{room_id}/messages")
async def post_message(room_id: int, data: MessageIn, user: User = Depends(active_user), rt=Depends(get_rt)):
    return await call(rt.chat.post(user, room_id, data.text, data.event_id))


@router.post("/rooms/{room_id}/read")
async def read(room_id: int, data: ReadIn, user: User = Depends(active_user), rt=Depends(get_rt)):
    last_read = await call(rt.chat.mark_read(user, room_id, data.last_id))
    return {"last_read_id": last_read, "unread": await rt.chat.unread_total(user)}


@router.put("/messages/{message_id}")
async def edit_message(message_id: int, data: EditIn, user: User = Depends(active_user), rt=Depends(get_rt)):
    return await call(rt.chat.edit(user, message_id, data.text))


@router.delete("/messages/{message_id}")
async def delete_message(message_id: int, user: User = Depends(active_user), rt=Depends(get_rt)):
    return await call(rt.chat.delete_message(user, message_id))


@router.get("/updates")
async def updates(after: int = 0, rev: int | None = None, timeout: float = 25.0, user: User = Depends(active_user), rt=Depends(get_rt)):
    return await call(rt.chat.updates(user, after, rev, timeout))
