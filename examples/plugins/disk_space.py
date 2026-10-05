import shutil

from opswatch.connectors import Connector, ConnectorError, Field, PollResult, register


@register
class DiskSpaceConnector(Connector):
    type = "disk_space"
    title = "Свободное место на диске"
    category = "monitoring"
    description = "Предупреждает, когда на диске или в сетевой папке заканчивается место"
    default_interval = 300
    fields = [
        Field("path", "Диск или папка", required=True, placeholder="D:\\"),
        Field("warn_percent", "Предупреждение, % занято", type="number", default=85),
        Field("critical_percent", "Критично, % занято", type="number", default=95),
    ]

    async def poll(self) -> PollResult:
        path = str(self.option("path", "")).strip()
        try:
            usage = shutil.disk_usage(path)
        except OSError as exc:
            raise ConnectorError(f"Путь недоступен: {exc}") from exc
        used = round(usage.used / usage.total * 100, 1)
        fingerprint = self.fingerprint("usage")
        metrics = {"used_percent": used, "free_gb": round(usage.free / 1024**3, 1)}
        if used >= self.int_option("critical_percent", 95):
            severity = "critical"
        elif used >= self.int_option("warn_percent", 85):
            severity = "warning"
        else:
            return PollResult(events=[self.resolved(fingerprint)], metrics=metrics, message=f"Занято {used}%")
        event = self.event(
            title=f"{self.ctx.name}: занято {used}%",
            message=f"Свободно {metrics['free_gb']} ГБ на {path}",
            severity=severity,
            type="disk.usage",
            fingerprint=fingerprint,
        )
        return PollResult(events=[event], metrics=metrics, message=f"Занято {used}%")
