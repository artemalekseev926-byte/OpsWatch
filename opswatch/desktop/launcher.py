from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from typing import Callable

import httpx

from opswatch import APP_NAME, __version__
from opswatch.config import AppConfig
from opswatch.logs import ensure_streams, setup_logging

log = logging.getLogger("opswatch.desktop")

PREFS_FILE = "desktop.json"

SETUP_HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>OpsWatch</title>
<style>
:root{--bg:#f5f6f8;--s:#fff;--b:#e2e5ea;--t:#171a1f;--m:#6b7280;--a:#2563eb;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--s:#171a20;--b:#2a2f38;--t:#e8eaee;--m:#9aa2ae;--a:#5b8cff;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--t);
font:14px/1.5 "Segoe UI",system-ui,sans-serif}.w{width:520px;max-width:calc(100% - 32px)}
.logo{width:48px;height:48px;border-radius:13px;background:var(--a);display:grid;place-items:center;margin:0 auto 12px}
h1{text-align:center;margin:0 0 4px;font-size:24px}.sub{text-align:center;color:var(--m);margin-bottom:22px}
.c{background:var(--s);border:1px solid var(--b);border-radius:12px;padding:18px;margin-bottom:12px}
.c h2{margin:0 0 4px;font-size:16px}.c p{margin:0 0 12px;color:var(--m)}
button{height:36px;padding:0 16px;border-radius:8px;border:1px solid var(--a);background:var(--a);color:#fff;font:inherit;font-weight:600;cursor:pointer}
button.o{background:transparent;color:var(--a)}input{width:100%;height:36px;border:1px solid var(--b);border-radius:8px;padding:0 10px;
background:var(--s);color:var(--t);font:inherit;margin-bottom:10px}.e{color:#dc2626;min-height:20px;margin-top:6px}
</style></head><body><div class="w">
<div class="logo"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg></div>
<h1>OpsWatch</h1><div class="sub">Выберите, как запустить программу на этом компьютере</div>
<div class="c"><h2>Этот компьютер — сервер</h2><p>Здесь будут храниться настройки, источники, бэкапы и пользователи. Другие сотрудники подключаются к этому компьютеру.</p>
<button onclick="go('server')">Запустить сервер</button></div>
<div class="c"><h2>Подключиться к серверу</h2><p>OpsWatch уже работает на другом компьютере — укажите его адрес.</p>
<input id="u" placeholder="http://192.168.1.10:8765"><button class="o" onclick="go('client')">Подключиться</button></div>
<div class="e" id="e"></div></div>
<script>
async function go(mode){const e=document.getElementById('e');e.textContent='Подождите…';
try{const r=await window.pywebview.api.setup_choose(mode,document.getElementById('u').value);if(!r.ok)e.textContent=r.error;}
catch(x){e.textContent=String(x)}}
</script></body></html>"""


def prefs_path(config: AppConfig) -> Path:
    return Path(config.data_dir) / PREFS_FILE


def load_prefs(config: AppConfig) -> dict:
    try:
        return json.loads(prefs_path(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_prefs(config: AppConfig, prefs: dict) -> None:
    prefs_path(config).write_text(json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")


def is_healthy(base: str, timeout: float = 3.0) -> bool:
    try:
        response = httpx.get(base.rstrip("/") + "/api/health", timeout=timeout)
        return response.status_code == 200 and response.json().get("app") == APP_NAME
    except Exception:
        return False


def wait_healthy(base: str, timeout: float = 60.0, server=None) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server is not None and not server.is_alive():
            return False
        if is_healthy(base, 2):
            return True
        time.sleep(0.4)
    return False


def normalize_url(value: str) -> str:
    value = (value or "").strip().rstrip("/")
    if not value:
        return ""
    if "://" not in value:
        value = "http://" + value
    host_part = value.split("://", 1)[1]
    if ":" not in host_part.split("/")[0]:
        value = value + ":8765"
    return value


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def system_notify(title: str, body: str) -> None:
    if sys.platform.startswith("linux"):
        try:
            subprocess.Popen(["notify-send", "-a", APP_NAME, title, body])
        except OSError:
            pass


class DesktopAgent:
    def __init__(self, notify: Callable[[str, str], None], interval: float = 15.0) -> None:
        self.notify = notify
        self.interval = interval
        self.base = ""
        self.token = ""
        self.enabled = False
        self.last_id = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="opswatch-agent", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def set_session(self, base: str, token: str, enabled: bool) -> None:
        with self._lock:
            if token != self.token or base != self.base:
                self.last_id = 0
            self.base = (base or "").rstrip("/")
            self.token = token or ""
            self.enabled = bool(enabled)
        self._wake.set()

    def poll_once(self) -> list[dict]:
        with self._lock:
            base, token, enabled, last_id = self.base, self.token, self.enabled, self.last_id
        if not (base and token and enabled):
            return []
        response = httpx.get(
            f"{base}/api/notifications/poll",
            params={"after": last_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if response.status_code != 200:
            return []
        data = response.json()
        items = (data.get("items") or []) if last_id else []
        with self._lock:
            if token == self.token:
                self.last_id = max(self.last_id, int(data.get("last_id") or 0))
        if not data.get("desktop"):
            return []
        return items

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                items = self.poll_once()
                for item in items[:3]:
                    self.notify(item.get("title") or APP_NAME, item.get("body") or "")
                if len(items) > 3:
                    self.notify(APP_NAME, f"Ещё уведомлений: {len(items) - 3}")
            except Exception:
                log.debug("desktop poll failed", exc_info=True)
            self._wake.wait(self.interval)
            self._wake.clear()


class Bridge:
    def __init__(self, app: "DesktopApp") -> None:
        self._app = app

    def set_session(self, base, token, enabled, name=""):
        self._app.agent.set_session(base, token, enabled)
        return True

    def change_server(self):
        self._app.show_setup()
        return True

    def setup_choose(self, mode, url=""):
        return self._app.apply_setup(mode, url)

    def notify(self, title, body=""):
        self._app.notify(title, body)
        return True


class DesktopApp:
    def __init__(self, args: argparse.Namespace) -> None:
        overrides = {}
        if args.data_dir:
            overrides["data_dir"] = Path(args.data_dir)
        if args.port:
            overrides["port"] = args.port
        self.args = args
        self.config = AppConfig.load(**overrides)
        setup_logging(self.config.logs_dir, self.config.log_level, console=False)
        self.prefs = load_prefs(self.config)
        self.server = None
        self.window = None
        self.icon = None
        self.target = ""
        self.quitting = False
        self.hidden_hint_shown = False
        self.startup_error = ""
        self.agent = DesktopAgent(self.notify)

    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.config.port}"

    def start_server(self) -> str:
        url = self.local_url()
        if is_healthy(url):
            return url
        if self.server is None:
            from opswatch.server import ServerThread

            self.server = ServerThread(self.config)
            self.server.start()
        if not wait_healthy(url, 90, self.server):
            error = getattr(self.server, "error", None)
            raise RuntimeError(f"Сервер не запустился: {error or 'порт ' + str(self.config.port) + ' занят?'}")
        return url

    def resolve_target(self) -> str:
        if self.args.connect:
            self.prefs = {"mode": "client", "server_url": normalize_url(self.args.connect)}
            save_prefs(self.config, self.prefs)
        elif self.args.server:
            self.prefs = {"mode": "server"}
            save_prefs(self.config, self.prefs)
        mode = self.prefs.get("mode")
        if mode == "client" and self.prefs.get("server_url"):
            return self.prefs["server_url"]
        if mode == "server":
            return self.start_server()
        return ""

    def apply_setup(self, mode: str, url: str = "") -> dict:
        try:
            if mode == "client":
                target = normalize_url(url)
                if not target:
                    return {"ok": False, "error": "Укажите адрес сервера"}
                if not is_healthy(target, 5):
                    return {"ok": False, "error": f"Сервер OpsWatch не отвечает по адресу {target}"}
                self.prefs = {"mode": "client", "server_url": target}
            else:
                target = self.start_server()
                self.prefs = {"mode": "server"}
            save_prefs(self.config, self.prefs)
            self.target = target
            if self.window is not None:
                self.window.load_url(target)
            return {"ok": True}
        except Exception as exc:
            log.exception("setup failed")
            return {"ok": False, "error": str(exc)}

    def show_setup(self) -> None:
        if self.window is not None:
            self.window.load_html(SETUP_HTML)
            self.show_window()

    def notify(self, title: str, body: str) -> None:
        title = (title or APP_NAME)[:63]
        body = (body or " ")[:255]
        if self.icon is not None:
            try:
                self.icon.notify(body, title)
                return
            except Exception:
                log.debug("tray notify failed", exc_info=True)
        system_notify(title, body)

    def show_window(self) -> None:
        if self.window is None:
            if self.target:
                webbrowser.open(self.target)
            return
        try:
            self.window.show()
            self.window.restore()
        except Exception:
            log.debug("show failed", exc_info=True)

    def open_browser(self) -> None:
        if self.target:
            webbrowser.open(self.target)

    def quit(self) -> None:
        self.quitting = True
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass

    def on_closing(self):
        if self.quitting or self.icon is None:
            self.quitting = True
            return True
        threading.Thread(target=self.window.hide, daemon=True).start()
        if not self.hidden_hint_shown:
            self.hidden_hint_shown = True
            self.notify(APP_NAME, "Программа продолжает работать в трее и покажет уведомления")
        return False

    def start_tray(self) -> None:
        try:
            import pystray

            from opswatch.desktop.icon import make_icon
        except Exception:
            log.info("Трей недоступен", exc_info=True)
            return
        menu = pystray.Menu(
            pystray.MenuItem("Открыть OpsWatch", lambda *_: self.show_window(), default=True),
            pystray.MenuItem("Открыть в браузере", lambda *_: self.open_browser()),
            pystray.MenuItem("Сменить сервер", lambda *_: self.show_setup()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", lambda *_: self.quit()),
        )
        try:
            self.icon = pystray.Icon("OpsWatch", make_icon(64), f"{APP_NAME} {__version__}", menu)
            self.icon.run_detached()
        except Exception:
            log.info("Не удалось запустить значок в трее", exc_info=True)
            self.icon = None

    def run(self) -> int:
        try:
            self.target = self.resolve_target()
        except Exception as exc:
            log.exception("start failed")
            self.target = ""
            self.prefs = {}
            self.startup_error = str(exc)
        self.agent.start()
        self.start_tray()
        try:
            import webview
        except Exception:
            webview = None
            log.info("pywebview недоступен", exc_info=True)
        try:
            if webview is not None and not self.args.browser:
                storage = Path(self.config.data_dir) / "webview"
                storage.mkdir(parents=True, exist_ok=True)
                self.window = webview.create_window(
                    APP_NAME,
                    url=self.target or None,
                    html=None if self.target else SETUP_HTML,
                    js_api=Bridge(self),
                    width=1320,
                    height=860,
                    min_size=(960, 620),
                    background_color="#f5f6f8",
                )
                self.window.events.closing += self.on_closing
                webview.start(private_mode=False, storage_path=str(storage))
            else:
                self.run_browser_mode()
        except Exception:
            log.exception("Окно не открылось, переключаюсь на браузер")
            self.window = None
            self.run_browser_mode()
        finally:
            self.shutdown()
        return 0

    def run_browser_mode(self) -> None:
        if not self.target:
            self.target = self.start_server()
            self.prefs = {"mode": "server"}
            save_prefs(self.config, self.prefs)
        webbrowser.open(self.target)
        try:
            while not self.quitting:
                if self.server is not None and not self.server.is_alive():
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

    def shutdown(self) -> None:
        self.quitting = True
        self.agent.stop()
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
        if self.server is not None:
            self.server.stop()


def selftest(args: argparse.Namespace) -> int:
    from opswatch.server import ServerThread

    report = Path(args.report) if args.report else Path(tempfile.gettempdir()) / "opswatch-selftest.txt"
    lines = [f"{APP_NAME} {__version__} selftest", f"python {sys.version}", f"frozen {getattr(sys, 'frozen', False)}"]
    code = 1
    with tempfile.TemporaryDirectory() as tmp:
        port = free_port()
        config = AppConfig.load(data_dir=Path(tmp), port=port, host="127.0.0.1")
        setup_logging(config.logs_dir, "INFO", console=False)
        server = ServerThread(config)
        server.start()
        base = f"http://127.0.0.1:{port}"
        try:
            if not wait_healthy(base, 120, server):
                lines.append(f"health: FAIL {server.error!r}")
            else:
                lines.append("health: OK")
                login = httpx.post(base + "/api/auth/login", json={"username": "admin1", "password": "admin1"}, timeout=10)
                lines.append(f"login: {login.status_code}")
                headers = {"Authorization": "Bearer " + login.json()["token"]}
                meta = httpx.get(base + "/api/meta", headers=headers, timeout=10).json()
                lines.append("connectors: " + ",".join(c["type"] for c in meta.get("connectors", [])))
                index = httpx.get(base + "/", timeout=10)
                lines.append(f"index: {index.status_code} {len(index.text)}")
                for module in ("webview", "pystray", "pymssql", "asyncpg", "aiomysql", "pyzipper"):
                    try:
                        __import__(module)
                        lines.append(f"import {module}: OK")
                    except Exception as exc:
                        lines.append(f"import {module}: FAIL {exc}")
                code = 0 if login.status_code == 200 and len(meta.get("connectors", [])) >= 10 else 1
        except Exception as exc:
            lines.append(f"error: {exc!r}")
        finally:
            server.stop()
        log_file = config.logs_dir / "opswatch.log"
        if log_file.exists():
            lines.append("--- log ---")
            lines.append(log_file.read_text(encoding="utf-8", errors="replace")[-4000:])
    lines.append(f"result: {'OK' if code == 0 else 'FAIL'}")
    report.write_text("\n".join(lines), encoding="utf-8")
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="OpsWatch", description=f"{APP_NAME} {__version__}")
    parser.add_argument("--server", action="store_true", help="Запустить как сервер на этом компьютере")
    parser.add_argument("--connect", metavar="URL", help="Подключиться к серверу по адресу")
    parser.add_argument("--browser", action="store_true", help="Открыть в браузере вместо окна программы")
    parser.add_argument("--port", type=int)
    parser.add_argument("--data-dir")
    parser.add_argument("--reset", action="store_true", help="Сбросить выбор режима (сервер/клиент)")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--report")
    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_streams()
    args, _unknown = build_parser().parse_known_args(argv)
    if args.selftest:
        return selftest(args)
    if args.reset:
        config = AppConfig.load(**({"data_dir": Path(args.data_dir)} if args.data_dir else {}))
        prefs_path(config).unlink(missing_ok=True)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OpsWatch.Desktop")
        except Exception:
            pass
    os.environ.setdefault("PYWEBVIEW_LOG", "warning")
    return DesktopApp(args).run()


if __name__ == "__main__":
    sys.exit(main())
