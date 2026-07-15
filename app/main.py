import asyncio
import time
import shutil
import os
import json
from pathlib import Path

import requests
import edifice
from edifice import (
    App, Window,
    VBoxView, HBoxView,
    Label, Button, ProgressBar, Slider,
    use_state, use_async_call,
)
from PySide6.QtWidgets import QFileDialog, QApplication
from PySide6.QtGui import QFontDatabase, QFont
from loguru import logger

# ── Path config ───────────────────────────────────────────────────────────────

import sys

# For PyInstaller EXE, use current working directory as base
# For dev, use project root
if getattr(sys, 'frozen', False):
    BASE_DIR = Path.cwd()  # Use current working directory for EXE
else:
    BASE_DIR = Path(__file__).parent.parent  # Use project root for dev

PROJECT_DIR = BASE_DIR
UPLOADS_DIR = BASE_DIR / "uploads"
NORMATIVE_DIR = BASE_DIR / "normative_base"
_LOGO_PATH = Path(__file__).parent / "assets" / "vsk_logo.png"

# ── Логирование ───────────────────────────────────────────────────────────────
_LOG_PATH = Path(__file__).parent / "app.log"
logger.remove()  # Удаляем дефолтный handler
logger.add(_LOG_PATH, format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}", rotation="10 MB")
logger.add(lambda msg: print(msg, end=""), format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}")  # Также в консоль

# Загрузка конфига
_CONFIG_PATH = Path(__file__).parent / "config.json"
def _load_config():
    default = {
        "api_base_url": "http://localhost:8001",
        "llm": {
            "max_chars": 2200000,
            "max_sections": 300,
            "max_chunks": 0,
            "batch_size": 25,
            "temperature": 0.2
        },
        "qwen": {
            "api_url": "https://model-1.ai-api.vsk.ru/v1/completions",
            "model_name": "Qwen3.6-35B-A3B-NVFP4",
            "max_tokens": 100000,
            "num_ctx": 400000
        }
    }
    if _CONFIG_PATH.exists():
        try:
            loaded = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            default.update(loaded)
            return default
        except Exception as e:
            logger.warning(f"Не удалось загрузить конфиг: {e}, используются дефолты")
    return default

_CONFIG = _load_config()
API_URL           = _CONFIG.get("api_base_url", "http://localhost:8001") + "/api/update"
API_ESTIMATE_URL  = _CONFIG.get("api_base_url", "http://localhost:8001") + "/api/estimate"
LLM_CONFIG        = _CONFIG.get("llm", {})
QWEN_CONFIG       = _CONFIG.get("qwen", {})

# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt(seconds: int) -> str:
    m, s = divmod(abs(seconds), 60)
    return f"{m}:{s:02d}"

def _fmt_long(seconds: int) -> str:
    h, rem = divmod(abs(seconds), 3600)
    m = rem // 60
    if h > 0:
        return f"~{h} ч {m} мин"
    return f"~{m} мин"

# ── Styles ────────────────────────────────────────────────────────────────────

_BG    = "#002033"
_CARD  = "#0d2e45"
_MUTED = "#8eafc0"
_WHITE = "#ffffff"
_BLUE  = "#1a6fa8"
_DIM   = "#4a5560"
_GREEN = "#1a7a4a"
_ORANGE = "#c47a1e"

def card():
    return {"background-color": _CARD, "border-radius": "8px",
            "padding": "14px", "margin-bottom": "10px"}

def label_s():
    return {"color": _MUTED, "font-size": "13px"}

def value_s():
    return {"color": _WHITE, "font-size": "13px"}

def btn(color=_BLUE):
    return {"background-color": color, "color": _WHITE,
            "border-radius": "6px", "padding": "12px 18px", "font-size": "13px"}

# ── Component ─────────────────────────────────────────────────────────────────

@edifice.component
def DocumentAssistantApp(self):
    normative_file, set_normative_file = use_state("")
    client_file,    set_client_file    = use_state("")
    status,         set_status         = use_state("Готов к работе")
    progress,       set_progress       = use_state(0)
    elapsed,        set_elapsed        = use_state(0)
    estimated,      set_estimated      = use_state(0)
    result_file,    set_result_file    = use_state("")
    processing,     set_processing     = use_state(False)

    # Estimate state
    estimate_data,  set_estimate_data  = use_state(None)   # {chunk_count, estimated_seconds}
    estimating,     set_estimating     = use_state(False)
    chunks_pct,     set_chunks_pct     = use_state(100)    # slider 10–100

    # ── Callbacks ─────────────────────────────────────────────────────────

    def _open_file_dialog(title: str, start_dir: str, filters: str) -> str:
        dialog = QFileDialog(None, title, start_dir, filters)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        if dialog.exec():
            files = dialog.selectedFiles()
            return files[0] if files else ""
        return ""

    def pick_normative(_=None):
        path = _open_file_dialog(
            "Нормативная база", str(NORMATIVE_DIR),
            "Документы (*.xlsx *.xls *.docx *.pdf *.txt)",
        )
        if path:
            set_normative_file(path)
            set_estimate_data(None)

    def pick_client(_=None):
        path = _open_file_dialog(
            "Файл клиента", str(UPLOADS_DIR),
            "Документы (*.xlsx *.xls *.docx *.pdf)",
        )
        if path:
            set_client_file(path)
            set_estimate_data(None)
            set_chunks_pct(100)

    async def _estimate_async():
        if not client_file:
            set_status("Выберите файл клиента")
            return

        set_estimating(True)
        set_status("Анализ файла...")
        try:
            # Copy client file to uploads so FastAPI can read it
            UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            src = Path(client_file)
            dst = UPLOADS_DIR / src.name
            await asyncio.to_thread(shutil.copy2, src, dst)
            file_path = str(dst)  # Полный путь к файлу

            resp = await asyncio.to_thread(
                requests.post, API_ESTIMATE_URL,
                json={"file_path": file_path},
                timeout=60,
            )
            if resp.ok:
                data = resp.json()
                set_estimate_data(data)
                set_chunks_pct(100)
                set_status("Готов к работе")
            else:
                set_status(f"Ошибка оценки: {resp.text[:100]}")
        except Exception as exc:
            set_status(f"Ошибка: {str(exc)[:200]}")
        finally:
            set_estimating(False)

    estimate_call, _ = use_async_call(_estimate_async)

    def on_estimate(_=None):
        if not estimating and not processing:
            estimate_call()

    async def _process_async():
        if not client_file:
            set_status("Выберите файл клиента")
            return

        set_processing(True)
        set_progress(0)
        set_result_file("")
        set_elapsed(0)
        set_estimated(0)
        set_status("Копирование файлов...")

        try:
            if normative_file:
                src = Path(normative_file)
                NORMATIVE_DIR.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(shutil.copy2, src, NORMATIVE_DIR / src.name)

            UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            src = Path(client_file)
            dst = UPLOADS_DIR / src.name
            try:
                await asyncio.to_thread(shutil.copy2, src, dst)
            except PermissionError:
                raise RuntimeError(
                    f"Файл '{src.name}' открыт в другой программе. "
                    "Закройте его и попробуйте снова."
                )
            file_path = str(dst)  # Полный путь к файлу

            # Calculate max_chunks from slider and estimate
            max_chunks = 0
            est_secs = 0
            if estimate_data:
                full_chunks = estimate_data["chunk_count"]
                max_chunks = max(1, round(full_chunks * chunks_pct / 100))
                est_secs = estimate_data["estimated_seconds"] * chunks_pct // 100
            else:
                est_secs = 600  # fallback

            set_estimated(est_secs)
            set_status(f"Обработка... (≈{_fmt_long(est_secs)})")

            t0 = time.time()

            async def tick():
                while True:
                    await asyncio.sleep(1)
                    el = int(time.time() - t0)
                    set_elapsed(el)
                    set_progress(min(95, int(el * 100 / max(est_secs, 1))))

            tick_task = asyncio.create_task(tick())

            try:
                resp = await asyncio.to_thread(
                    requests.post, API_URL,
                    json={"request_id": int(t0), "file_path": file_path,
                          "user_name": "gui_user", "max_chunks": max_chunks},
                    timeout=3600,
                )
            finally:
                tick_task.cancel()

            elapsed_total = int(time.time() - t0)

            if resp.ok:
                out_name = Path(resp.json()["output_file"]).name
                set_result_file(str(UPLOADS_DIR / out_name))
                set_progress(100)
                set_status(f"Готово за {_fmt_long(elapsed_total)}")
            else:
                set_status(f"Ошибка {resp.status_code}: {resp.text[:100]}")
                set_progress(0)

        except Exception as exc:
            set_status(f"Ошибка: {str(exc)[:200]}")
            set_progress(0)
        finally:
            set_processing(False)

    process, _ = use_async_call(_process_async)

    def on_process(_=None):
        if not processing:
            process()

    def open_result(_=None):
        if result_file:
            os.startfile(result_file)

    # ── Render ────────────────────────────────────────────────────────────

    norm_label   = Path(normative_file).name if normative_file else "Не выбрана"
    client_label = Path(client_file).name    if client_file    else "Не выбран"

    # Derived estimate values for current slider position
    shown_chunks = 0
    shown_time   = 0
    if estimate_data:
        shown_chunks = max(1, round(estimate_data["chunk_count"] * chunks_pct / 100))
        shown_time   = estimate_data["estimated_seconds"] * chunks_pct // 100

    with Window(title="ДМС-ассистент",
                style={"background-color": _BG, "min-width": "700px", "min-height": "580px"}):
        with VBoxView(style={"background-color": _BG, "padding": "24px"}):

            with HBoxView(style={"margin-bottom": "20px", "align": "left"}):
                if _LOGO_PATH.exists():
                    edifice.Image(src=str(_LOGO_PATH),
                                  style={"width": "48px", "height": "48px",
                                         "margin-right": "14px"})
                Label(text="ДМС-ассистент",
                      style={"color": _WHITE, "font-size": "20px",
                             "font-weight": "bold"})

            # Normative base
            with VBoxView(style=card()):
                Label(text="Нормативная база",
                      style={**label_s(), "margin-bottom": "8px"})
                with HBoxView():
                    Label(text=norm_label,
                          style={**value_s(),
                                 "color": _WHITE if normative_file else _MUTED})
                    Button(title="Выбрать", on_click=pick_normative,
                           style=btn())

            # Client file
            with VBoxView(style=card()):
                Label(text="Файл клиента",
                      style={**label_s(), "margin-bottom": "8px"})
                with HBoxView():
                    Label(text=client_label,
                          style={**value_s(),
                                 "color": _WHITE if client_file else _MUTED})
                    Button(title="Выбрать", on_click=pick_client,
                           style=btn())

            # Estimate button
            if client_file and not processing:
                Button(
                    title="Анализирую..." if estimating else "Оценить время работы",
                    on_click=on_estimate,
                    style={**btn(_DIM if estimating else _ORANGE),
                           "margin-bottom": "10px"},
                )

            # Estimate result + slider
            if estimate_data:
                with VBoxView(style=card()):
                    Label(text="Оценка обработки",
                          style={**label_s(), "margin-bottom": "8px"})
                    with HBoxView(style={"margin-bottom": "10px"}):
                        Label(text=f"Разделов: {shown_chunks} из {estimate_data['chunk_count']}",
                              style={**value_s(), "margin-right": "24px"})
                        Label(text=f"Время: {_fmt_long(shown_time)}",
                              style=value_s())
                    Slider(
                        value=chunks_pct,
                        min_value=1,
                        max_value=100,
                        on_change=lambda v: set_chunks_pct(v),
                        style={"margin-bottom": "4px"},
                    )
                    Label(text=f"{chunks_pct}% документа",
                          style=label_s())

            # Process button
            Button(
                title="Обработка..." if processing else "Подготовить",
                on_click=on_process,
                style={**btn(_DIM if processing else _BLUE),
                       "margin-bottom": "12px", "font-size": "14px"},
            )

            # Status card
            with VBoxView(style=card()):
                Label(text="Статус", style={**label_s(), "margin-bottom": "6px"})
                Label(text=status, style={**value_s(), "margin-bottom": "8px"})

                if processing or progress > 0:
                    ProgressBar(value=progress, min_value=0, max_value=100,
                                style={"height": "8px", "margin-bottom": "8px"})

                if processing and estimated > 0:
                    with HBoxView():
                        Label(text=f"Прошло: {_fmt(elapsed)}",
                              style={**label_s(), "margin-right": "24px"})
                        Label(text=f"Ожидаемое: {_fmt_long(estimated)}",
                              style=label_s())

            # Result button
            if result_file:
                Button(title="Открыть результат",
                       on_click=open_result,
                       style=btn(_GREEN))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _edifice_app = App(DocumentAssistantApp())
    _font_path = Path(__file__).parent / "assets" / "GPN_DIN_Condensed-Regular.ttf"
    _qapp = QApplication.instance()
    if _qapp and _font_path.exists():
        _font_id = QFontDatabase.addApplicationFont(str(_font_path))
        if _font_id != -1:
            _family = QFontDatabase.applicationFontFamilies(_font_id)[0]
            _qapp.setFont(QFont(_family, 11))
            _qapp.setStyleSheet(f"* {{ font-family: '{_family}'; }}")
    _edifice_app.start()
