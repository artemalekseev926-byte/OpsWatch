# Архитектура OpsWatch

OpsWatch — один асинхронный процесс на Python 3.11+, внутри которого работают веб-панель (FastAPI), Telegram-бот (aiogram 3), планировщик (APScheduler) и конвейер событий. Настольное приложение для Windows — это тот же сервер плюс окно (pywebview), значок в трее и всплывающие уведомления.

## Схема модулей

```mermaid
flowchart LR
    subgraph Sources[Источники]
        DB[(MySQL / PostgreSQL / MS SQL)]
        C1[1С: файловая и серверная база]
        RAS[1С: кластер серверов через RAS]
        HTTP[HTTP-проверки, Zabbix API]
        WH[Webhook: Zabbix, Alertmanager, любые системы]
        BUG[Баг-репорты: бот /bug, веб, API]
    end

    subgraph Core[Ядро OpsWatch]
        SCH[Планировщик APScheduler]
        CON[Коннекторы-плагины]
        ING[Разбор webhook-ов]
        PIPE[Конвейер событий: дедупликация, группировка]
        ROUTE[Маршрутизация: правила, подписки, права]
        NOTI[Доставка: Telegram, входящие, ПК, шаблоны]
        MET[История метрик]
        ESC[Эскалация]
        BAK[Резервное копирование]
    end

    subgraph UI[Интерфейсы]
        WEB[Веб-панель FastAPI + SPA]
        BOT[Telegram-бот aiogram 3]
        DESK[Окно Windows, трей, уведомления]
    end

    DB --> CON
    C1 --> CON
    RAS --> CON
    CON --> MET
    MET --> WEB
    HTTP --> CON
    WH --> ING
    BUG --> PIPE
    SCH --> CON
    SCH --> BAK
    SCH --> ESC
    CON --> PIPE
    ING --> PIPE
    BAK --> PIPE
    PIPE --> ROUTE --> NOTI
    ESC --> NOTI
    NOTI --> BOT
    NOTI --> WEB
    NOTI --> DESK
    BAK --> BOT
```

## Структура репозитория

```
opswatch/
  config.py            настройки из .env и переменных окружения
  db.py, models.py     SQLAlchemy 2 (async), SQLite по умолчанию, PostgreSQL опционально
  migrator.py          миграции схемы Alembic, распознавание баз версии 0.1.0
  migrations/          ревизии Alembic
  i18n.py, locales/    переводы: tr (язык запроса/пользователя), ts (язык системных событий), tl (язык ОС)
  security.py          scrypt-хэши паролей, Fernet-шифрование секретов, токены сессий
  permissions.py       права, видимость категорий и источников
  runtime.py           сборка всех компонентов в один объект
  core/
    events.py          модель входящего события EventIn, нормализация важности
    pipeline.py        приём, группировка, авто-закрытие, подтверждение, эскалация
    router.py          правила маршрутизации, подписки, тихие часы
    notifier.py        очередь доставки в Telegram, обновление сообщений
    render.py          шаблоны сообщений, подстановки, проверка разметки, кнопки
    metrics.py         запись и выборка истории метрик для графиков
    ingest.py          разбор Zabbix / Alertmanager / универсального JSON
    sources.py         опрос коннекторов, статус «недоступен/доступен»
    scheduler.py       задания опроса, бэкапов, обслуживания и очистки
  connectors/          коннекторы: sql, onec, onec_log, onec_cluster (RAS/RAC), monitoring, checks
  services/            первичная настройка, хранилище настроек, баг-репорты, перенос данных между базами
  backup/              движки дампов, архивирование AES-256, доставка, ротация
  bot/                 менеджер бота и обработчики команд
  web/                 FastAPI, маршруты API, статический фронтенд
  desktop/             окно, трей, агент уведомлений, служба Windows, иконка
packaging/             спецификация PyInstaller и файлы для zip-архива
examples/              скрипт Zabbix, конфиг Alertmanager, пример плагина
tests/                 pytest
```

## Модель данных

```mermaid
erDiagram
    ROLE ||--o{ USER : "назначена"
    USER ||--o{ AUTH_SESSION : "входы"
    USER ||--o{ SUBSCRIPTION : "подписки"
    USER ||--o{ NOTIFICATION : "входящие"
    SOURCE ||--o{ EVENT : "порождает"
    EVENT ||--o{ ATTACHMENT : "вложения"
    EVENT ||--o{ NOTIFICATION : "доставки"
    SOURCE ||--o{ BACKUP_JOB : "резервируется"
    BACKUP_JOB ||--o{ BACKUP_RECORD : "запуски"
    SOURCE ||--o{ METRIC_POINT : "история"

    ROLE { string name string title json permissions }
    USER { string username string status bool is_superuser bigint telegram_chat_id bool notify_desktop string quiet_start string language }
    SOURCE { string type string category json config text secrets_encrypted json visible_roles string ingest_token json state }
    EVENT { string category string type string severity string fingerprint string external_id int count string status json escalation }
    RULE { json categories json source_ids json event_types string min_severity json target_roles int escalate_after_min }
    BACKUP_JOB { string schedule int keep_last bool encrypt text password_encrypted json destinations }
    BACKUP_RECORD { string status string file_path string sha256 bool verified json delivery }
    NOTIFICATION { string kind string telegram_status bigint telegram_message_id bool is_read }
    METRIC_POINT { string name float value datetime ts }
```

* **Категории событий**: `monitoring`, `database`, `onec`, `backup`, `bug`, `system`.
* **Важность**: `info`, `warning`, `critical`.
* **Статусы**: `new` → `acked` (принято) → `resolved` (решено).
* Пароли баз данных, токены ботов и пароли архивов хранятся только в зашифрованном виде (`Fernet`, ключ — `data/secret.key` или `OPSWATCH_SECRET_KEY`).
* Схема базы описана ревизиями Alembic в `opswatch/migrations/versions`; при запуске сервер применяет недостающие ревизии. Новая ревизия: `alembic revision --autogenerate -m "..."` из корня репозитория (файл `alembic.ini`).
* Метрики источников (`METRIC_POINT`) записываются при опросе не чаще раза в 5 минут на показатель и удаляются через `metric_retention_days` дней.

## Путь события от источника до Telegram

```mermaid
sequenceDiagram
    participant S as Источник (Zabbix / SQL / 1С)
    participant P as Конвейер
    participant R as Маршрутизатор
    participant N as Доставка
    participant T as Telegram
    participant U as Пользователь

    S->>P: событие (title, severity, category, fingerprint)
    P->>P: есть открытое событие с тем же отпечатком?
    alt повтор в окне группировки
        P->>P: count += 1, без уведомления
    else новое или окно истекло
        P->>R: кому отправить?
        R->>R: правила → подписки → права и видимость источника
        R-->>P: получатели + шаги эскалации
        P->>N: записи во «Входящие»
        N->>T: сообщение с кнопками «Принял / Решено / Подробнее» (без звука в тихие часы)
        T->>U: личное сообщение
    end
    U->>T: «Принял»
    T->>P: ack → сообщения у всех получателей обновляются
    S->>P: восстановление (resolve)
    P->>N: «✅ Решено» ответом на исходное сообщение
```

### Защита от спама

* **Группировка** — одинаковые события (по отпечатку) не рассылаются повторно чаще, чем раз в `group_window_min` минут; счётчик повторов растёт.
* **Тихие часы** — у каждого пользователя свои; некритичные уведомления приходят без звука.
* **Эскалация** — правило может указать «если критичное событие не подтверждено за N минут — отправить ролям/пользователям X».
* **Подписки** — пользователь может подписаться на категорию целиком или заглушить её (кроме критичных по правилам).

## Режимы запуска

| Режим | Команда | Для чего |
| --- | --- | --- |
| Настольное приложение | `OpsWatch.exe` | окно, трей, уведомления Windows; выбор «сервер» или «подключиться к серверу» |
| Служба Windows | `OpsWatchServer.exe install` / `start` | круглосуточная работа без входа пользователя |
| Консоль | `OpsWatchServer.exe run`, `opswatch run` | сервер без окна |
| Docker | `docker compose up -d` | Linux-серверы |
| Docker + PostgreSQL | `docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d` | хранение в PostgreSQL |
| Перенос данных | `OpsWatchServer.exe migrate-db <url> --write-env` | из SQLite в PostgreSQL и обратно |
| Обновление схемы | `OpsWatchServer.exe upgrade-db` | без запуска сервера |

## План развития по этапам

1. **MVP (готово)**: ядро событий, Telegram-бот, коннекторы MySQL/PostgreSQL/MS SQL, бэкапы, маршрутизация, веб-панель, роли.
2. **1С (готово базово)**: файловые и серверные базы, журнал регистрации (`.lgd` и `.lgp`), проверка целостности, HTTP/OData.
3. **Мониторинг (готово базово)**: Zabbix webhook и API, Alertmanager, универсальный webhook, HTTP-проверки.
4. **Версия 0.2 (готово)**: миграции схемы (Alembic) и хранение в PostgreSQL, мониторинг кластера 1С через RAS/RAC, графики метрик, шаблоны сообщений, английский интерфейс.
5. **Дальше**: двухфакторный вход, LDAP/Active Directory, отчёты по SLA, мобильная версия панели.
