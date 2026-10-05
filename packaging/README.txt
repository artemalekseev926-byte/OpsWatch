OpsWatch — мониторинг, резервное копирование и уведомления в Telegram
=====================================================================

Быстрый старт
-------------
1. Распакуйте архив в любую папку (например, C:\OpsWatch).
2. Запустите OpsWatch.exe.
3. При первом запуске выберите режим:
   • «Этот компьютер — сервер» — на компьютере, где будет работать OpsWatch;
   • «Подключиться к серверу» — на компьютерах сотрудников (укажите адрес сервера,
     например http://192.168.1.10:8765).
4. Войдите: логин admin1, пароль admin1 (смените пароль в профиле).
5. Остальные сотрудники нажимают «Регистрация», администратор подтверждает их
   на вкладке «Пользователи» и выдаёт роль (права).

Telegram
--------
Администратор: Настройки → Telegram → токен бота от @BotFather.
Пользователь: Профиль → «Привязать Telegram» → открыть бота и нажать «Старт».
Уведомления на компьютере: Профиль → «Уведомления Windows».

Работа как служба Windows (без входа пользователя)
--------------------------------------------------
Откройте командную строку от имени администратора в папке программы:
  OpsWatchServer.exe install
  OpsWatchServer.exe start
Веб-панель будет доступна по адресу http://<адрес-сервера>:8765
Удаление службы: OpsWatchServer.exe remove
Запуск сервера в консоли: OpsWatchServer.exe run

Данные
------
Все данные хранятся в папке data рядом с программой:
  data\opswatch.db — настройки, пользователи и журнал;
  data\secret.key  — ключ шифрования паролей (сохраните его в надёжном месте!);
  data\backups     — резервные копии;
  data\logs        — журналы работы.

Настройки запуска можно задать в файле .env (образец — .env.example).
Порт по умолчанию 8765 — разрешите его в брандмауэре Windows для доступа из сети.

Обновление и PostgreSQL
-----------------------
Новую версию распакуйте поверх старой — папка data и файл .env сохранятся,
схема базы обновится автоматически при запуске.
Перенести данные из SQLite в PostgreSQL (сервер должен быть остановлен):
  OpsWatchServer.exe migrate-db postgresql://user:password@host/opswatch --write-env

Язык
----
Интерфейс и уведомления — на русском и английском: переключатель на экране входа
и в профиле. Язык по умолчанию задаётся в .env: OPSWATCH_LANGUAGE=ru или en.

Примеры интеграций — в папке examples. Собственные коннекторы — в папке plugins.

Лицензия MIT.


OpsWatch — monitoring, backups and Telegram notifications
==========================================================

1. Unzip the archive to any folder (for example, C:\OpsWatch) and run OpsWatch.exe.
2. Choose "This computer is the server" or "Connect to a server".
3. Sign in with admin1 / admin1 and change the password in the profile.
4. Switch the language to English on the sign-in screen or in the profile.

Windows service (elevated command prompt in the program folder):
  OpsWatchServer.exe install
  OpsWatchServer.exe start

All data is kept in the data folder next to the program; keep data\secret.key safe.
Move data to PostgreSQL: OpsWatchServer.exe migrate-db postgresql://user:password@host/opswatch --write-env
Set the default language in .env: OPSWATCH_LANGUAGE=en
