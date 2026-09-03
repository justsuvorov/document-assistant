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
    Label, Button, ProgressBar, Slider, CheckBox,
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

# Отображается справочно на экране "Сверка грузов" — фактический путь настраивается
# на сервере через SPECIAL_CONDITIONS_GLOBAL_PATH (.env), здесь только для информации
# оператора: этот файл подключается автоматически к КАЖДОЙ сверке, без выбора в GUI.
GLOBAL_SPECIAL_CONDITIONS_PATH = (
    r"\\fstorfs\disk_m\БОС_ФСЦ_УПиСД\ДГ\Информационный\ДпГ УПиСД ФСЦ.xlsm"
)

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
_API_BASE          = _CONFIG.get("api_base_url", "http://localhost:8001")
API_URL            = _API_BASE + "/api/update"
API_ESTIMATE_URL   = _API_BASE + "/api/estimate"
API_RECONCILE_URL  = _API_BASE + "/api/reconcile"
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
_RED    = "#a83232"

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

def small_btn(color=_BLUE):
    return {"background-color": color, "color": _WHITE,
            "border-radius": "5px", "padding": "4px 10px", "font-size": "12px"}

def mode_tab(active: bool):
    return {"background-color": _BLUE if active else "transparent",
            "color": _WHITE if active else _MUTED,
            "border-radius": "6px", "padding": "8px 16px", "font-size": "13px"}

# ── Reusable file/folder pickers ────────────────────────────────────────────────

def _open_file_dialog(title: str, start_dir: str, filters: str) -> str:
    dialog = QFileDialog(None, title, start_dir, filters)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    if dialog.exec():
        files = dialog.selectedFiles()
        return files[0] if files else ""
    return ""

def _open_files_dialog(title: str, start_dir: str, filters: str) -> tuple:
    dialog = QFileDialog(None, title, start_dir, filters)
    dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    if dialog.exec():
        return tuple(dialog.selectedFiles())
    return ()

def _open_folder_dialog(title: str, start_dir: str) -> str:
    dialog = QFileDialog(None, title, start_dir)
    dialog.setFileMode(QFileDialog.FileMode.Directory)
    dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    if dialog.exec():
        files = dialog.selectedFiles()
        return files[0] if files else ""
    return ""

# ── DMS screen (POST /api/update) ───────────────────────────────────────────────

@edifice.component
def DmsScreen(self):
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

    def pick_normative(_=None):
        path = _open_file_dialog(
            "Нормативная база", str(NORMATIVE_DIR),
            "Документы (*.xlsx *.xlsm *.xls *.docx *.pdf *.txt)",
        )
        if path:
            set_normative_file(path)
            set_estimate_data(None)

    def pick_client(_=None):
        path = _open_file_dialog(
            "Файл клиента", str(UPLOADS_DIR),
            "Документы (*.xlsx *.xlsm *.xls *.docx *.pdf)",
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

    with VBoxView():
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


# ── Cargo screen (POST /api/reconcile) ──────────────────────────────────────────

@edifice.component
def CargoScreen(self):
    policy_folder,          set_policy_folder          = use_state("")
    special_conditions_file, set_special_conditions_file = use_state("")
    declaration_files,      set_declaration_files      = use_state(())   # tuple[str, ...]
    force_rebuild_matrix,   set_force_rebuild_matrix   = use_state(True)

    status,      set_status      = use_state("Готов к работе")
    processing,  set_processing  = use_state(False)
    elapsed,     set_elapsed     = use_state(0)
    result,      set_result      = use_state(None)   # full /api/reconcile response dict

    # ── Document choosing ────────────────────────────────────────────────

    def pick_policy_folder(_=None):
        path = _open_folder_dialog("Папка полиса (ген. полис + ДС)", str(BASE_DIR))
        if path:
            set_policy_folder(path)
            set_result(None)

    def pick_special_conditions(_=None):
        path = _open_file_dialog(
            "Файл особых условий (опционально)",
            policy_folder or str(BASE_DIR),
            "Документы (*.xlsx *.xlsm *.xls *.docx *.pdf *.txt)",
        )
        if path:
            set_special_conditions_file(path)

    def clear_special_conditions(_=None):
        set_special_conditions_file("")

    def pick_declarations(_=None):
        # Replaces the current selection — a single multi-select dialog already
        # covers "неограниченное число деклараций" from the business spec.
        paths = _open_files_dialog(
            "Декларации для сверки (можно выбрать несколько)",
            policy_folder or str(BASE_DIR),
            "Документы (*.xlsx *.xlsm *.xls *.docx *.pdf)",
        )
        if paths:
            set_declaration_files(paths)
            set_result(None)

    def add_declarations(_=None):
        # Merges an additional multi-select into the existing list, skipping
        # duplicates, so users aren't forced to re-pick everything at once.
        paths = _open_files_dialog(
            "Добавить декларации",
            policy_folder or str(BASE_DIR),
            "Документы (*.xlsx *.xlsm *.xls *.docx *.pdf)",
        )
        if paths:
            merged = list(declaration_files)
            for p in paths:
                if p not in merged:
                    merged.append(p)
            set_declaration_files(tuple(merged))
            set_result(None)

    def remove_declaration(path_to_remove):
        def _handler(_=None):
            set_declaration_files(tuple(p for p in declaration_files if p != path_to_remove))
            set_result(None)
        return _handler

    def clear_declarations(_=None):
        set_declaration_files(())
        set_result(None)

    # ── Processing ────────────────────────────────────────────────────────

    async def _process_async():
        if not policy_folder:
            set_status("Выберите папку полиса (ген. полис + ДС)")
            return
        if not declaration_files:
            set_status("Выберите хотя бы одну декларацию")
            return

        set_processing(True)
        set_result(None)
        set_elapsed(0)
        set_status(f"Сверка {len(declaration_files)} деклараций...")

        t0 = time.time()

        async def tick():
            while True:
                await asyncio.sleep(1)
                set_elapsed(int(time.time() - t0))

        tick_task = asyncio.create_task(tick())

        try:
            payload = {
                "request_id": int(t0),
                "user_name": "gui_user",
                "policy_folder": policy_folder,
                "declaration_paths": list(declaration_files),
                "special_conditions_path": special_conditions_file or None,
                "force_rebuild_matrix": force_rebuild_matrix,
            }
            try:
                resp = await asyncio.to_thread(
                    requests.post, API_RECONCILE_URL, json=payload, timeout=3600,
                )
            finally:
                tick_task.cancel()

            elapsed_total = int(time.time() - t0)

            if resp.ok:
                data = resp.json()
                set_result(data)
                set_status(f"Готово за {_fmt_long(elapsed_total)}")
            else:
                set_status(f"Ошибка {resp.status_code}: {resp.text[:200]}")

        except Exception as exc:
            set_status(f"Ошибка: {str(exc)[:200]}")
        finally:
            set_processing(False)

    process, _ = use_async_call(_process_async)

    def on_process(_=None):
        if not processing:
            process()

    def open_path(path: str):
        def _handler(_=None):
            if path:
                os.startfile(path)
        return _handler

    # ── Render ────────────────────────────────────────────────────────────

    policy_label = policy_folder if policy_folder else "Не выбрана"
    cond_label   = Path(special_conditions_file).name if special_conditions_file else "Не выбран (опционально)"

    with VBoxView():
        # Policy folder
        with VBoxView(style=card()):
            Label(text="Папка полиса (ген. полис + все ДС)",
                  style={**label_s(), "margin-bottom": "8px"})
            with HBoxView():
                Label(text=policy_label,
                      style={**value_s(), "color": _WHITE if policy_folder else _MUTED})
                Button(title="Выбрать папку", on_click=pick_policy_folder, style=btn())

        # Special conditions (optional)
        with VBoxView(style=card()):
            Label(text="Особые условия клиента", style={**label_s(), "margin-bottom": "8px"})
            with HBoxView():
                Label(text=cond_label,
                      style={**value_s(), "color": _WHITE if special_conditions_file else _MUTED})
                Button(title="Выбрать", on_click=pick_special_conditions, style=btn())
                if special_conditions_file:
                    Button(title="✕", on_click=clear_special_conditions,
                           style=small_btn(_DIM))
            Label(
                text=f"Общие особые условия (применяются всегда): {GLOBAL_SPECIAL_CONDITIONS_PATH}",
                style={**value_s(), "color": _MUTED, "margin-top": "8px", "font-size": "12px"},
            )

        # Declarations (multi)
        with VBoxView(style=card()):
            with HBoxView(style={"margin-bottom": "8px"}):
                Label(text=f"Декларации для сверки ({len(declaration_files)})",
                      style=label_s())
            with HBoxView(style={"margin-bottom": "8px"}):
                Button(title="Выбрать декларации", on_click=pick_declarations, style=btn())
                Button(title="Добавить ещё", on_click=add_declarations, style=btn(_DIM))
                if declaration_files:
                    Button(title="Очистить", on_click=clear_declarations, style=btn(_RED))

            if declaration_files:
                for decl_path in declaration_files:
                    with HBoxView(style={"margin-bottom": "4px"}):
                        Label(text=Path(decl_path).name, style={**value_s(), "margin-right": "8px"})
                        Button(title="✕", on_click=remove_declaration(decl_path),
                               style=small_btn(_DIM))
            else:
                Label(text="Ничего не выбрано", style=label_s())

        # Options
        with HBoxView(style={"margin-bottom": "10px"}):
            CheckBox(checked=force_rebuild_matrix, on_change=lambda v: set_force_rebuild_matrix(v),
                     style={"margin-right": "8px"})
            Label(text="Пересчитать матрицу актуальных правил заново (игнорировать кэш) — по умолчанию включено",
                  style=label_s())

        # Process button
        Button(
            title="Сверка..." if processing else "Начать сверку",
            on_click=on_process,
            style={**btn(_DIM if processing else _BLUE),
                   "margin-bottom": "12px", "font-size": "14px"},
        )

        # Status card
        with VBoxView(style=card()):
            Label(text="Статус", style={**label_s(), "margin-bottom": "6px"})
            Label(text=status, style={**value_s(), "margin-bottom": "8px"})
            if processing:
                with HBoxView():
                    Label(text=f"Прошло: {_fmt(elapsed)}", style=label_s())

        # Results
        if result:
            matrix_info = result.get("matrix", {})
            with VBoxView(style=card()):
                Label(text="Матрица актуальных правил", style={**label_s(), "margin-bottom": "6px"})
                with HBoxView():
                    Label(text=f"Пунктов: {matrix_info.get('clause_count', 0)}",
                          style={**value_s(), "margin-right": "24px"})
                    Label(
                        text="Взята из кэша" if matrix_info.get("cache_hit") else "Пересчитана",
                        style=value_s(),
                    )

            carrier_info = result.get("carrier_list") or {}
            with VBoxView(style=card()):
                Label(text="Перечень перевозчиков", style={**label_s(), "margin-bottom": "6px"})
                if carrier_info.get("found"):
                    Label(text=f"Найден: {carrier_info.get('file')}", style=value_s())
                    Label(text=f"Источник: {carrier_info.get('source')}", style=label_s())
                else:
                    Label(text="Не найден — проверка перевозчика не выполнялась",
                          style={**value_s(), "color": _ORANGE})

            for decl in result.get("declarations", []):
                with VBoxView(style=card()):
                    number = decl.get("declaration_number", "?")
                    decl_type = "одна перевозка" if decl.get("type") == "single" else "мультистрочная"
                    with HBoxView(style={"margin-bottom": "6px"}):
                        Label(text=f"Декларация {number}", style={**value_s(), "font-weight": "bold",
                                                                     "margin-right": "12px"})
                        Label(text=f"{decl_type}, строк: {decl.get('row_count', 0)}", style=label_s())

                    for warning in decl.get("warnings", []) or []:
                        Label(text=f"⚠ {warning}", style={"color": _ORANGE, "font-size": "12px",
                                                            "margin-bottom": "4px"})

                    output_file = decl.get("output_file", "")
                    if output_file:
                        with HBoxView():
                            Label(text=Path(output_file).name, style={**label_s(), "margin-right": "12px"})
                            Button(title="Открыть", on_click=open_path(output_file), style=small_btn(_GREEN))


# ── Root component: mode switch ─────────────────────────────────────────────────

@edifice.component
def DocumentAssistantApp(self):
    mode, set_mode = use_state("dms")  # "dms" | "cargo"

    with Window(title="Ассистент сверки документов",
                style={"background-color": _BG, "min-width": "760px", "min-height": "640px"}):
        with VBoxView(style={"background-color": _BG, "padding": "24px"}):

            with HBoxView(style={"margin-bottom": "16px", "align": "left"}):
                if _LOGO_PATH.exists():
                    edifice.Image(src=str(_LOGO_PATH),
                                  style={"width": "48px", "height": "48px",
                                         "margin-right": "14px"})
                Label(text="Ассистент сверки документов",
                      style={"color": _WHITE, "font-size": "20px",
                             "font-weight": "bold"})

            # Mode switch
            with HBoxView(style={"margin-bottom": "16px"}):
                Button(title="ДМС", on_click=lambda _=None: set_mode("dms"),
                       style=mode_tab(mode == "dms"))
                Button(title="Сверка грузов", on_click=lambda _=None: set_mode("cargo"),
                       style={**mode_tab(mode == "cargo"), "margin-left": "8px"})

            if mode == "dms":
                DmsScreen()
            else:
                CargoScreen()


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
