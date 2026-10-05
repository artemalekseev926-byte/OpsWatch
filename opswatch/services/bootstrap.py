from __future__ import annotations

import logging

from sqlalchemy import func, select

from opswatch.constants import BUILTIN_ROLES, DEFAULT_RULES
from opswatch.db import Database
from opswatch.i18n import system_language, tr, ts
from opswatch.models import Role, Rule, User
from opswatch.security import hash_password

log = logging.getLogger(__name__)


async def bootstrap(db: Database, admin_username: str, admin_password: str) -> None:
    async with db.session() as session:
        existing = {r.name: r for r in (await session.execute(select(Role))).scalars().all()}
        for spec in BUILTIN_ROLES:
            role = existing.get(spec["name"])
            if role is None:
                session.add(Role(name=spec["name"], title=spec["title"], permissions=spec["permissions"], builtin=True))
            elif spec["name"] == "admin":
                role.permissions = list(spec["permissions"])
        await session.flush()

        users_count = (await session.execute(select(func.count(User.id)))).scalar_one()
        if users_count == 0:
            admin_role = (await session.execute(select(Role).where(Role.name == "admin"))).scalar_one()
            lang = system_language()
            session.add(
                User(
                    username=admin_username,
                    password_hash=hash_password(admin_password),
                    full_name=tr("Администратор", lang),
                    language=lang,
                    status="active",
                    is_superuser=True,
                    role_id=admin_role.id,
                )
            )
            log.warning(ts("Создан администратор по умолчанию: %s (смените пароль в профиле)"), admin_username)

        rules_count = (await session.execute(select(func.count(Rule.id)))).scalar_one()
        if rules_count == 0:
            for spec in DEFAULT_RULES:
                session.add(Rule(**spec))
        await session.commit()
