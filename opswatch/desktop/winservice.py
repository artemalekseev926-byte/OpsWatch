from __future__ import annotations

import sys

from opswatch import APP_NAME, __version__
from opswatch.config import AppConfig
from opswatch.logs import ensure_streams, setup_logging

SERVICE_NAME = "OpsWatch"
DISPLAY_NAME = "OpsWatch"
DESCRIPTION = "OpsWatch: мониторинг, резервное копирование и уведомления в Telegram"

USAGE = f"""{APP_NAME} {__version__} — сервер

  OpsWatchServer.exe run        запустить сервер в этом окне
  OpsWatchServer.exe install    установить службу Windows (автозапуск)
  OpsWatchServer.exe start      запустить службу
  OpsWatchServer.exe stop       остановить службу
  OpsWatchServer.exe restart    перезапустить службу
  OpsWatchServer.exe status     состояние службы
  OpsWatchServer.exe remove     удалить службу

Команды службы выполняйте от имени администратора.
Веб-панель: http://<адрес-компьютера>:8765 (логин admin1 / пароль admin1)
"""


def run_console() -> int:
    from opswatch.server import run_server

    config = AppConfig.load()
    setup_logging(config.logs_dir, config.log_level, console=True)
    print(f"{APP_NAME} запущен: http://127.0.0.1:{config.port}  (Ctrl+C — остановить)")
    run_server(config)
    return 0


def _service_class():
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

    class OpsWatchService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = DISPLAY_NAME
        _svc_description_ = DESCRIPTION

        def __init__(self, args):
            super().__init__(args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.server = None

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            if self.server is not None:
                self.server.should_exit = True
            win32event.SetEvent(self.stop_event)

        def SvcDoRun(self):
            from opswatch.server import build_server

            servicemanager.LogInfoMsg(f"{APP_NAME} {__version__} starting")
            config = AppConfig.load()
            setup_logging(config.logs_dir, config.log_level, console=False)
            self.server = build_server(config)
            self.server.run()
            servicemanager.LogInfoMsg(f"{APP_NAME} stopped")

    return OpsWatchService


def manage(command: str) -> int:
    import win32service
    import win32serviceutil

    cls = _service_class()
    try:
        if command == "install":
            win32serviceutil.InstallService(
                win32serviceutil.GetServiceClassString(cls),
                SERVICE_NAME,
                DISPLAY_NAME,
                startType=win32service.SERVICE_AUTO_START,
                exeName=sys.executable,
                description=DESCRIPTION,
            )
            print("Служба установлена. Запустите её командой: OpsWatchServer.exe start")
        elif command == "remove":
            try:
                win32serviceutil.StopService(SERVICE_NAME)
            except Exception:
                pass
            win32serviceutil.RemoveService(SERVICE_NAME)
            print("Служба удалена")
        elif command == "start":
            win32serviceutil.StartService(SERVICE_NAME)
            print("Служба запускается")
        elif command == "stop":
            win32serviceutil.StopService(SERVICE_NAME)
            print("Служба останавливается")
        elif command == "restart":
            win32serviceutil.RestartService(SERVICE_NAME)
            print("Служба перезапущена")
        elif command == "status":
            state = win32serviceutil.QueryServiceStatus(SERVICE_NAME)[1]
            names = {1: "остановлена", 2: "запускается", 3: "останавливается", 4: "работает"}
            print(f"Служба {SERVICE_NAME}: {names.get(state, state)}")
        else:
            print(USAGE)
            return 2
    except Exception as exc:
        print(f"Ошибка: {exc}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ensure_streams()
    argv = sys.argv[1:] if argv is None else argv
    command = argv[0].lower() if argv else ""
    if command in {"-h", "--help", "help", "/?"}:
        print(USAGE)
        return 0
    if command == "run":
        return run_console()
    if command == "selftest":
        from opswatch.desktop.launcher import main as desktop_main

        return desktop_main(["--selftest"] + argv[1:])
    if sys.platform != "win32":
        if not command:
            return run_console()
        print("Управление службой доступно только в Windows")
        return 1
    if command:
        return manage(command)
    import pywintypes
    import servicemanager

    cls = _service_class()
    try:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(cls)
        servicemanager.StartServiceCtrlDispatcher()
    except pywintypes.error as exc:
        if getattr(exc, "winerror", None) == 1063:
            print(USAGE)
            return run_console()
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
