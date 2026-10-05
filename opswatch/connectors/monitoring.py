from __future__ import annotations

import time
from typing import Any

import httpx

from opswatch.connectors.base import Connector, ConnectorError, Field, PollResult, register
from opswatch.i18n import ts

ZABBIX_SEVERITY = {0: "info", 1: "info", 2: "warning", 3: "warning", 4: "critical", 5: "critical"}
ZABBIX_SEVERITY_OPTIONS = [
    ["0", "Не классифицировано и выше"],
    ["1", "Информация и выше"],
    ["2", "Предупреждение и выше"],
    ["3", "Средняя и выше"],
    ["4", "Высокая и выше"],
    ["5", "Чрезвычайная"],
]


@register
class HttpCheckConnector(Connector):
    type = "http_check"
    title = "HTTP(S) проверка"
    category = "monitoring"
    description = "Доступность сайта, API или HTTP-сервиса 1С, код ответа и время отклика"
    default_interval = 60
    fields = [
        Field("url", "URL", required=True, placeholder="https://example.com/health"),
        Field("method", "Метод", type="select", default="GET", options=[["GET", "GET"], ["HEAD", "HEAD"]]),
        Field("expected_status", "Ожидаемый код (пусто — любой < 400)", type="number"),
        Field("contains", "Ответ должен содержать текст"),
        Field("latency_warn_ms", "Предупреждать при отклике дольше, мс", type="number", default=0),
        Field("timeout", "Таймаут, сек", type="number", default=15),
        Field("verify_ssl", "Проверять SSL-сертификат", type="bool", default=True),
        Field("user", "Пользователь (Basic)"),
        Field("password", "Пароль", type="password", secret=True),
    ]

    async def _request(self) -> tuple[httpx.Response, float]:
        url = str(self.option("url", "")).strip()
        if not url:
            raise ConnectorError(ts("Не указан URL"))
        auth = None
        if self.option("user"):
            auth = (str(self.option("user")), str(self.option("password", "")))
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=self.int_option("timeout", 15),
                verify=self.bool_option("verify_ssl", True),
                follow_redirects=True,
            ) as client:
                response = await client.request(str(self.option("method", "GET")), url, auth=auth)
        except httpx.HTTPError as exc:
            raise ConnectorError(f"{type(exc).__name__}: {exc}") from exc
        return response, (time.perf_counter() - started) * 1000

    async def poll(self) -> PollResult:
        response, latency = await self._request()
        expected = self.int_option("expected_status", 0)
        if expected and response.status_code != expected:
            raise ConnectorError(ts("Код ответа {status_code}, ожидался {expected}", status_code=response.status_code, expected=expected))
        if not expected and response.status_code >= 400:
            raise ConnectorError(ts("Код ответа {status_code}", status_code=response.status_code))
        needle = str(self.option("contains", "") or "")
        if needle and needle not in response.text:
            raise ConnectorError(ts("В ответе нет текста «{needle}»", needle=needle))
        events = []
        warn = self.int_option("latency_warn_ms", 0)
        fp = self.fingerprint("latency")
        if warn:
            if latency > warn:
                events.append(
                    self.event(
                        title=ts("{name}: медленный ответ {latency:.0f} мс", name=self.ctx.name, latency=latency),
                        message=ts("Порог {warn} мс", warn=warn),
                        type="http.slow",
                        fingerprint=fp,
                    )
                )
            else:
                events.append(self.resolved(fp))
        metrics = {"status": response.status_code, "latency_ms": round(latency)}
        return PollResult(events=events, metrics=metrics, message=ts("HTTP {status_code}, {latency:.0f} мс", status_code=response.status_code, latency=latency))


@register
class ZabbixApiConnector(Connector):
    type = "zabbix_api"
    title = "Zabbix API (опрос проблем)"
    category = "monitoring"
    description = "Периодически забирает активные проблемы из Zabbix и закрывает их автоматически"
    default_interval = 60
    fields = [
        Field("url", "Адрес Zabbix", required=True, placeholder="https://zabbix.local/"),
        Field("token", "API-токен", type="password", secret=True, required=True),
        Field("min_severity", "Минимальная важность", type="select", default="2", options=ZABBIX_SEVERITY_OPTIONS),
        Field("verify_ssl", "Проверять SSL-сертификат", type="bool", default=True),
    ]

    def endpoint(self) -> str:
        url = str(self.option("url", "")).strip().rstrip("/")
        if not url:
            raise ConnectorError(ts("Не указан адрес Zabbix"))
        return url if url.endswith("api_jsonrpc.php") else url + "/api_jsonrpc.php"

    async def call(self, method: str, params: dict[str, Any]) -> Any:
        token = str(self.option("token", ""))
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        headers = {"Content-Type": "application/json-rpc"}
        if method != "apiinfo.version":
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=20, verify=self.bool_option("verify_ssl", True)) as client:
            try:
                response = await client.post(self.endpoint(), json=payload, headers=headers)
                data = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise ConnectorError(ts("Zabbix API недоступен: {exc}", exc=exc)) from exc
            if "error" in data and method != "apiinfo.version":
                legacy = dict(payload, auth=token)
                headers.pop("Authorization", None)
                try:
                    response = await client.post(self.endpoint(), json=legacy, headers=headers)
                    data = response.json()
                except (httpx.HTTPError, ValueError) as exc:
                    raise ConnectorError(ts("Zabbix API недоступен: {exc}", exc=exc)) from exc
        if "error" in data:
            error = data["error"]
            raise ConnectorError(f"Zabbix API: {error.get('message')} {error.get('data', '')}".strip())
        return data.get("result")

    async def problems(self) -> list[dict[str, Any]]:
        minimum = self.int_option("min_severity", 2)
        return await self.call(
            "problem.get",
            {
                "output": ["eventid", "name", "severity", "clock", "acknowledged", "opdata"],
                "selectTags": "extend",
                "recent": False,
                "severities": list(range(minimum, 6)),
                "sortfield": ["eventid"],
                "sortorder": "DESC",
                "limit": 500,
            },
        ) or []

    async def poll(self) -> PollResult:
        problems = await self.problems()
        state = dict(self.ctx.state or {})
        previous = set(state.get("open", []))
        current = set()
        events = []
        for problem in problems:
            event_id = str(problem.get("eventid"))
            current.add(event_id)
            if event_id in previous:
                continue
            tags = {t.get("tag"): t.get("value") for t in problem.get("tags") or []}
            severity = ZABBIX_SEVERITY.get(int(problem.get("severity", 0)), "warning")
            events.append(
                self.event(
                    title=problem.get("name") or ts("Проблема Zabbix"),
                    message=problem.get("opdata") or "",
                    severity=severity,
                    type="zabbix.problem",
                    external_id=f"zbx:{event_id}",
                    details={"eventid": event_id, **{f"tag:{k}": v for k, v in tags.items()}},
                )
            )
        for gone in previous - current:
            resolve = self.resolved(fingerprint="", message=ts("Проблема закрыта в Zabbix"))
            resolve.fingerprint = None
            resolve.external_id = f"zbx:{gone}"
            events.append(resolve)
        state["open"] = sorted(current)
        return PollResult(events=events, metrics={"problems": len(current)}, state=state, message=ts("Активных проблем: {len}", len=len(current)))

    async def test(self) -> PollResult:
        version = await self.call("apiinfo.version", {})
        problems = await self.problems()
        return PollResult(
            metrics={"version": version, "problems": len(problems)},
            message=ts("Zabbix {version}, активных проблем: {len}", version=version, len=len(problems)),
        )


class WebhookSource(Connector):
    passive = True
    category = "monitoring"
    default_interval = 0

    async def test(self) -> PollResult:
        return PollResult(message=ts("Источник принимает события по webhook — проверьте отправку со стороны системы"))


@register
class ZabbixWebhookSource(WebhookSource):
    type = "zabbix_webhook"
    title = "Zabbix (webhook)"
    description = "Приём оповещений через тип оповещения Webhook в Zabbix"
    fields = []


@register
class AlertmanagerSource(WebhookSource):
    type = "alertmanager"
    title = "Prometheus Alertmanager"
    description = "Приём оповещений через webhook_configs Alertmanager"
    fields = []


@register
class GenericWebhookSource(WebhookSource):
    type = "webhook"
    title = "Универсальный webhook"
    description = "Любая система, способная отправить HTTP POST с JSON (в том числе баг-репорты)"
    fields = [
        Field("default_severity", "Важность по умолчанию", type="select", default="warning",
              options=[["info", "Информация"], ["warning", "Предупреждение"], ["critical", "Критично"]]),
    ]
