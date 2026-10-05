# Как написать свой коннектор

Коннектор — это класс-наследник `opswatch.connectors.Connector`. Он описывает поля настройки (из них веб-панель сама строит форму) и умеет опрашивать источник. Ядро само вызывает опрос по расписанию, отмечает источник «недоступным» при исключении, закрывает события при восстановлении и рассылает уведомления.

## Минимальный пример

```python
import shutil

from opswatch.connectors import Connector, ConnectorError, Field, PollResult, register


@register
class DiskSpaceConnector(Connector):
    type = "disk_space"
    title = "Свободное место на диске"
    category = "monitoring"
    description = "Предупреждает, когда заканчивается место"
    default_interval = 300
    fields = [
        Field("path", "Диск или папка", required=True, placeholder="D:\\"),
        Field("warn_percent", "Предупреждение, % занято", type="number", default=85),
    ]

    async def poll(self) -> PollResult:
        try:
            usage = shutil.disk_usage(self.option("path"))
        except OSError as exc:
            raise ConnectorError(f"Путь недоступен: {exc}") from exc
        used = round(usage.used / usage.total * 100, 1)
        fingerprint = self.fingerprint("usage")
        if used < self.int_option("warn_percent", 85):
            return PollResult(events=[self.resolved(fingerprint)], metrics={"used_percent": used})
        return PollResult(
            events=[self.event(title=f"Занято {used}%", severity="warning", type="disk.usage", fingerprint=fingerprint)],
            metrics={"used_percent": used},
        )
```

Полная версия — в [`examples/plugins/disk_space.py`](../examples/plugins/disk_space.py).

## Подключение

* **Программа для Windows (exe)**: положите `.py`-файл в папку `plugins` рядом с `OpsWatch.exe` и перезапустите программу.
* **Установка из исходников**: та же папка `plugins` в рабочем каталоге или путь в `OPSWATCH_PLUGINS_DIR`.
* **Пакет pip**: объявите точку входа в `pyproject.toml` своего пакета:

```toml
[project.entry-points."opswatch.connectors"]
disk_space = "my_package.disk_space"
```

## Атрибуты класса

| Атрибут | Назначение |
| --- | --- |
| `type` | уникальный код типа источника |
| `title`, `description` | название и описание в интерфейсе |
| `category` | категория событий по умолчанию: `monitoring`, `database`, `onec`, `backup`, `bug`, `system` |
| `fields` | список `Field` — поля формы настройки |
| `default_interval` | интервал опроса по умолчанию, сек |
| `passive` | `True` — источник только принимает webhook и не опрашивается |
| `supports_checks` | поддерживает пользовательские SQL-проверки |
| `supports_backup` | для источника можно создать задание резервного копирования (нужен движок в `opswatch.backup.engines.ENGINES`) |
| `supports_maintenance` | есть периодическое обслуживание (`maintenance_cron()` + `maintenance()`) |

## Поля формы (`Field`)

`Field(name, label, type="text", required=False, default=None, secret=False, options=None, help="", placeholder="", group="")`

* `type`: `text`, `password`, `number`, `bool`, `select`, `textarea`, `path`, `checks`.
* `secret=True` — значение шифруется в базе и никогда не возвращается в браузер.
* `options` — для `select`: `[["value", "Подпись"], ...]`.
* `group` — заголовок блока в форме.

## Методы

| Метод | Когда вызывается |
| --- | --- |
| `async poll() -> PollResult` | по расписанию; исключение = источник недоступен |
| `async test() -> PollResult` | кнопка «Проверить подключение» |
| `maintenance_cron()` / `async maintenance()` | обслуживание по cron (например, проверка целостности 1С) |

`PollResult(events=[...], metrics={...}, state={...}, message="")`:

* `events` — список `EventIn`; используйте помощники `self.event(...)` и `self.resolved(fingerprint)`.
* `metrics` — значения для карточки источника (`size_human`, `version`, `latency_ms` и любые свои).
* `state` — словарь, сохраняется между опросами (например, последний обработанный ID).

## Отпечатки и закрытие событий

* `self.fingerprint("что-то")` даёт стабильный отпечаток, уникальный для источника. Повторы с тем же отпечатком группируются.
* Чтобы закрыть проблему, верните `self.resolved(fingerprint)` — пользователи, получившие исходное уведомление, увидят «✅ Решено».
* Для внешних систем со своими ID используйте `external_id=...` в `self.event()` и `EventIn(resolve=True, external_id=...)` для закрытия.

## Проверка

```bash
pip install -e ".[dev]"
pytest -q
```

Посмотрите тесты в `tests/test_checks.py` и `tests/test_onec.py` — коннекторы легко тестируются без реальных серверов.
