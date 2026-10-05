from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from opswatch import APP_NAME, __version__
from opswatch.config import AppConfig
from opswatch.runtime import Runtime
from opswatch.web.routes import account, admin, events, sources

STATIC_DIR = Path(__file__).resolve().parent / "static"
NO_CACHE = {"Cache-Control": "no-cache"}


def create_app(runtime: Runtime | None = None, config: AppConfig | None = None) -> FastAPI:
    owns_runtime = runtime is None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if owns_runtime:
            rt = Runtime(config or AppConfig.load())
            app.state.rt = rt
            await rt.start()
        try:
            yield
        finally:
            if owns_runtime:
                await app.state.rt.stop()

    app = FastAPI(title=APP_NAME, version=__version__, lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
    if runtime is not None:
        app.state.rt = runtime

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        messages = []
        for error in exc.errors():
            location = ".".join(str(p) for p in error.get("loc", [])[1:])
            messages.append(f"{location}: {error.get('msg')}" if location else str(error.get("msg")))
        return JSONResponse(status_code=422, content={"detail": "; ".join(messages) or "Неверные данные"})

    for module in (account, events, sources, admin):
        app.include_router(module.router)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC_DIR / "index.html", headers=NO_CACHE)

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon():
        return FileResponse(STATIC_DIR / "favicon.svg")

    return app
