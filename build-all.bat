@echo off
REM Файл сохранён в UTF-8, а cmd по умолчанию читает батники в OEM-кодировке
REM (cp866). Без переключения кодовой страницы русский текст выводится
REM кракозябрами, а главное - литералы с кириллицей внутри команд (пути вида
REM "dist\API-сервис.exe") не совпадают с реальными именами файлов, и проверки
REM ложно срабатывают как "файл не найден".

REM Полная сборка обоих EXE файлов с копированием конфигов

echo.
echo ========================================
echo  Сборка ВСК ДМС-ассистент (2 EXE)
echo ========================================
echo.

REM Проверка что мы в правильной директории
if not exist "main.py" (
    echo ERROR: main.py не найден!
    echo Запусти этот батник из корня проекта
    pause
    exit /b 1
)

REM %~dp0 - папка самого батника: вызов работает независимо от текущего
REM каталога и от настройки NoDefaultCurrentDirectoryInExePath.
call "%~dp0load-proxy.bat"

echo.
echo [1/4] Установка зависимостей...
if defined PIP_CONFIG_FILE echo         pip использует конфиг: %PIP_CONFIG_FILE%
if defined PIP_INDEX_URL   echo         индекс пакетов: %PIP_INDEX_URL%

pip install -r requirements.txt -q
if errorlevel 1 goto :pip_failed
pip install -r app/requirements.txt -q
if errorlevel 1 goto :pip_failed
pip install pyinstaller -q
if errorlevel 1 goto :pip_failed
goto :pip_ok

:pip_failed
echo.
echo ERROR: не удалось установить зависимости.
echo.
echo Если ошибка связана с сетью или SSL - проверьте прокси:
echo   1. Скопируйте proxy.env.example в proxy.env и укажите адрес прокси
echo   2. При ошибке SSLError/CERTIFICATE_VERIFY_FAILED укажите в proxy.env
echo      корпоративный сертификат (PIP_CERT) или PIP_TRUSTED_HOST
echo   3. Если у вас уже есть pip.ini - пропишите PIP_CONFIG_FILE
echo.
pause
exit /b 1

:pip_ok

echo [2/4] Сборка API сервиса...
pyinstaller build_api.spec --clean --noconfirm
REM Проверяем код возврата PyInstaller и наличие файла по ASCII-маске:
REM имя exe содержит кириллицу, и сравнение с ней зависит от кодовой страницы.
if errorlevel 1 goto :api_failed
dir /b "dist\API-*.exe" >nul 2>&1 || goto :api_failed
echo OK: dist/API-сервис.exe
goto :api_ok

:api_failed
echo ERROR: Сборка API не удалась! Смотрите вывод PyInstaller выше.
pause
exit /b 1

:api_ok

echo [3/4] Сборка GUI приложения...
pyinstaller build.spec --clean --noconfirm
if errorlevel 1 (
    echo ERROR: Сборка GUI не удалась!
    pause
    exit /b 1
)
echo OK: dist/ВСК ДМС-ассистент.exe

echo [4/4] Копирование конфигов...
REM Копируем .env.dist (для EXE, с относительными путями) вместо .env
if exist ".env.dist" (
    copy .env.dist dist\.env >nul 2>&1
) else (
    copy .env dist\.env >nul 2>&1
)
echo OK: dist/.env (для EXE с относительными путями)

REM Убеждаемся что app/config.json скопирован
if not exist "dist/app/config.json" (
    mkdir dist\app >nul 2>&1
    copy app\config.json dist\app\config.json >nul 2>&1
)
echo OK: dist/app/config.json

echo.
echo ========================================
echo  OK Сборка завершена успешно!
echo ========================================
echo.
echo Структура dist/:
echo ├── API-сервис.exe
echo ├── .env                 (для API)
echo ├── ВСК ДМС-ассистент.exe
echo ├── normative_base/      (для API)
echo ├── examples/            (для API)
echo └── app/
echo     └── config.json      (для GUI)
echo.
echo Для запуска:
echo   run-all.bat
echo.
pause