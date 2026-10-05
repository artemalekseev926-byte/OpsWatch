from __future__ import annotations

import threading

import uvicorn

from opswatch.config import AppConfig
from opswatch.web.app import create_app


class Server(uvicorn.Server):
    def __init__(self, config: uvicorn.Config, app) -> None:
        super().__init__(config)
        self.app = app

    async def shutdown(self, sockets=None) -> None:
        runtime = getattr(self.app.state, "rt", None)
        if runtime is not None:
            runtime.chat.close()
        await super().shutdown(sockets=sockets)


def build_server(config: AppConfig, host: str | None = None, port: int | None = None) -> uvicorn.Server:
    app = create_app(config=config)
    uv_config = uvicorn.Config(
        app,
        host=host or config.host,
        port=port or config.port,
        log_config=None,
        access_log=False,
        lifespan="on",
        proxy_headers=True,
        timeout_graceful_shutdown=10,
    )
    return Server(uv_config, app)


def run_server(config: AppConfig, host: str | None = None, port: int | None = None) -> None:
    build_server(config, host, port).run()


class ServerThread(threading.Thread):
    def __init__(self, config: AppConfig, host: str | None = None, port: int | None = None) -> None:
        super().__init__(name="opswatch-server", daemon=True)
        self.server = build_server(config, host, port)
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            self.server.run()
        except BaseException as exc:
            self.error = exc

    @property
    def started(self) -> bool:
        return bool(self.server.started)

    def stop(self, timeout: float = 15) -> None:
        self.server.should_exit = True
        self.join(timeout)
