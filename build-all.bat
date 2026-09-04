@echo off
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

call load-proxy.bat

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
echo Если ошибка связана с сетью или SSL — проверьте прокси:
echo   1. Скопируйте proxy.env.example в proxy.env и укажите адрес прокси
echo   2. При ошибке SSLError/CERTIFICATE_VERIFY_FAILED укажите в proxy.env
echo      корпоративный сертификат (PIP_CERT) или PIP_TRUSTED_HOST
echo   3. Если у вас уже есть pip.ini — пропишите PIP_CONFIG_FILE
echo.
pause
exit /b 1

:pip_ok

echo [2/4] Сборка API сервиса...
pyinstaller build_api.spec --clean --noconfirm
if not exist "dist\API-сервис.exe" (
    echo ERROR: Сборка API не удалась!
    pause
    exit /b 1
)
echo OK: dist/API-сервис.exe

echo [3/4] Сборка GUI приложения...
pyinstaller build.spec --clean --noconfirm
if not exist "dist\ВСК ДМС-ассистент.exe" (
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
echo  ✓ Сборка завершена успешно!
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
