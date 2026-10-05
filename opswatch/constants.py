from __future__ import annotations

SEVERITIES = ("info", "warning", "critical")
SEVERITY_ORDER = {name: index for index, name in enumerate(SEVERITIES)}
SEVERITY_TITLES = {"info": "Информация", "warning": "Предупреждение", "critical": "Критично"}
SEVERITY_ICONS = {"info": "🔵", "warning": "🟠", "critical": "🔴"}

CATEGORIES = ("monitoring", "database", "onec", "backup", "bug", "system")
CATEGORY_TITLES = {
    "monitoring": "Мониторинг",
    "database": "Базы данных",
    "onec": "1С",
    "backup": "Бэкапы",
    "bug": "Ошибки",
    "system": "Система",
}

EVENT_STATUSES = ("new", "acked", "resolved")
EVENT_STATUS_TITLES = {"new": "Новое", "acked": "Принято", "resolved": "Решено"}

USER_STATUSES = ("pending", "active", "blocked")

PERMISSIONS = {
    "monitoring.view": "Мониторинг ресурсов: просмотр и уведомления",
    "databases.view": "Базы данных: просмотр и уведомления",
    "onec.view": "1С: просмотр и уведомления",
    "backups.view": "Бэкапы: просмотр, уведомления и получение копий",
    "bugs.view": "Баг-репорты: просмотр и уведомления",
    "system.view": "Системные события: просмотр и уведомления",
    "bugs.report": "Отправка баг-репортов",
    "events.manage": "Подтверждение и закрытие событий",
    "sources.manage": "Управление источниками",
    "backups.manage": "Управление резервным копированием",
    "rules.manage": "Управление правилами маршрутизации",
    "users.manage": "Управление пользователями и ролями",
    "settings.manage": "Глобальные настройки",
}

CATEGORY_PERMISSION = {
    "monitoring": "monitoring.view",
    "database": "databases.view",
    "onec": "onec.view",
    "backup": "backups.view",
    "bug": "bugs.view",
    "system": "system.view",
}

VIEW_ALL = [
    "monitoring.view",
    "databases.view",
    "onec.view",
    "backups.view",
    "bugs.view",
    "system.view",
]

BUILTIN_ROLES = [
    {
        "name": "admin",
        "title": "Администратор",
        "permissions": list(PERMISSIONS),
    },
    {
        "name": "sysadmin",
        "title": "Системный администратор",
        "permissions": VIEW_ALL
        + ["bugs.report", "events.manage", "sources.manage", "backups.manage"],
    },
    {
        "name": "admin1c",
        "title": "Администратор 1С",
        "permissions": [
            "onec.view",
            "databases.view",
            "backups.view",
            "bugs.view",
            "bugs.report",
            "events.manage",
        ],
    },
    {
        "name": "manager",
        "title": "Руководитель",
        "permissions": VIEW_ALL[:-1] + ["bugs.report"],
    },
    {
        "name": "accountant",
        "title": "Бухгалтер",
        "permissions": ["onec.view", "bugs.report"],
    },
    {
        "name": "user",
        "title": "Пользователь",
        "permissions": ["bugs.report"],
    },
]

DEFAULT_RULES = [
    {
        "name": "Администраторам: всё важное",
        "priority": 10,
        "categories": [],
        "min_severity": "warning",
        "target_roles": ["admin"],
    },
    {
        "name": "Инфраструктура: сисадминам с эскалацией",
        "priority": 20,
        "categories": ["monitoring", "database", "onec", "backup"],
        "min_severity": "warning",
        "target_roles": ["sysadmin"],
        "escalate_after_min": 15,
        "escalate_roles": ["admin", "manager"],
    },
    {
        "name": "1С: администраторам 1С",
        "priority": 30,
        "categories": ["onec", "backup"],
        "min_severity": "warning",
        "target_roles": ["admin1c"],
    },
    {
        "name": "Баг-репорты: поддержке",
        "priority": 40,
        "categories": ["bug"],
        "min_severity": "info",
        "target_roles": ["admin", "sysadmin", "admin1c"],
    },
    {
        "name": "Руководителю: только критичное",
        "priority": 50,
        "categories": [],
        "min_severity": "critical",
        "target_roles": ["manager"],
    },
]


def severity_at_least(value: str, minimum: str) -> bool:
    return SEVERITY_ORDER.get(value, 0) >= SEVERITY_ORDER.get(minimum, 0)


def max_severity(a: str, b: str) -> str:
    return a if SEVERITY_ORDER.get(a, 0) >= SEVERITY_ORDER.get(b, 0) else b
