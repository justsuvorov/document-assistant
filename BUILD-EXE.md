# Сборка standalone приложения (2 EXE файла)

## Что будет

- **API-сервис.exe** — FastAPI на порту 8001 (консольное окно для логов)
- **ВСК ДМС-ассистент.exe** — GUI приложение (подключается к API)

Оба запускаются независимо и не требуют Docker.

---

## Шаг 1: Установи зависимости

```bash
# API зависимости
pip install -r requirements.txt

# GUI зависимости
pip install -r app/requirements.txt

# PyInstaller
pip install pyinstaller
```

---

## Шаг 2: Собери оба EXE

```bash
# API сервис
pyinstaller build_api.spec --clean --noconfirm

# GUI приложение
pyinstaller build.spec --clean --noconfirm
```

Готовые файлы в папке `dist/`:
- `dist/API-сервис.exe` (~200-300 MB)
- `dist/ВСК ДМС-ассистент.exe` (~200-300 MB)

---

## Шаг 3: Запусти оба приложения

### Вариант 1: Автоматический запуск (рекомендуемый)

```bash
run-all.bat
```

Откроются два окна:
1. **API-сервис** — консольное окно с логами
2. **ВСК ДМС-ассистент** — GUI приложение

### Вариант 2: Ручной запуск

**Окно 1 (API):**
```bash
dist\API-сервис.exe
```
Должно вывести:
```
[INFO] Starting gunicorn ...
[INFO] Listening at: http://0.0.0.0:8001
```

**Окно 2 (GUI):**
```bash
dist\ВСК ДМС-ассистент.exe
```

---

## Конфигурация

### API (до сборки)

Отредактируй `.env` перед сборкой:
```bash
NORMATIVE_BASE=/app/normative_base
QWEN_API_URL=https://model-1.ai-api.vsk.ru/v1/completions
QWEN_MODEL_NAME=Qwen3.6-35B-A3B-NVFP4
...
```

### GUI (после сборки)

Рядом с `ВСК ДМС-ассистент.exe` есть `app/config.json`:
```json
{
  "api_base_url": "http://localhost:8001"
}
```

Можешь менять параметры в config.json без пересборки.

---

## Логирование

- **API**: консольное окно `API-сервис.exe`
- **GUI**: файл `app.log` рядом с `ВСК ДМС-ассистент.exe`

---

## Размеры файлов

- API-сервис.exe: ~200-300 MB
- ВСК ДМС-ассистент.exe: ~200-300 MB
- **Итого**: ~400-600 MB

Если нужно сжать:
```bash
# Отключить консоль для API (потеряешь логи)
# или использовать UPX compression
```

---

## Распространение

Для пользователей:
1. Дай оба EXE файла
2. Дай batch файл `run-all.bat`
3. Дай папку `app/` с `config.json` (для GUI конфига)

Пользователь просто двойкликает `run-all.bat` и всё запускается.

---

## Оптимизация

Если размеры слишком большие:

**Уменьшить размер API:**
```bash
# Исключить неиспользуемые модули
# в build_api.spec добавить в excludedimports
```

**Или использовать::**
```bash
# PyInstaller с UPX (компрессия)
pyinstaller build_api.spec --upx-dir=<path-to-upx>
```

**Или отдельный дистрибьютив:**
- GUI EXE (~150 MB)
- API в Docker (если позволяет)
