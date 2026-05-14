import asyncio
import time
import shutil
import os
from pathlib import Path

import requests
import edifice
from edifice import (
    App, Window,
    VBoxView, HBoxView,
    Label, Button, ProgressBar,
    use_state, use_async_call,
)
from PySide6.QtWidgets import QFileDialog

# ── Path config ───────────────────────────────────────────────────────────────

PROJECT_DIR       = Path(__file__).parent.parent
UPLOADS_DIR       = PROJECT_DIR / "uploads"
NORMATIVE_DIR     = PROJECT_DIR / "normative_base"
CONTAINER_UPLOADS = "/app/uploads"
API_URL           = "http://localhost:8001/api/update"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _estimate_seconds(path: Path) -> int:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(str(path), read_only=True)
        rows = max(0, (wb.active.max_row or 1) - 1)
        wb.close()
        chunks = max(1, (rows + 24) // 25)
    except Exception:
        chunks = 10
    return chunks * 15


def _fmt(seconds: int) -> str:
    m, s = divmod(abs(seconds), 60)
    return f"{m}:{s:02d}"

# ── Styles ────────────────────────────────────────────────────────────────────

_BG    = "#002033"
_CARD  = "#0d2e45"
_MUTED = "#8eafc0"
_WHITE = "#ffffff"
_BLUE  = "#1a6fa8"
_DIM   = "#4a5560"
_GREEN = "#1a7a4a"

def card():
    return {"background-color": _CARD, "border-radius": "8px",
            "padding": "14px", "margin-bottom": "10px"}

def label_s():
    return {"color": _MUTED, "font-size": "12px"}

def value_s():
    return {"color": _WHITE, "font-size": "13px"}

def btn(color=_BLUE):
    return {"background-color": color, "color": _WHITE,
            "border-radius": "6px", "padding": "8px 18px", "font-size": "13px"}

# ── Component ─────────────────────────────────────────────────────────────────

@edifice.component
def DocumentAssistantApp(self):
    normative_file, set_normative_file = use_state("")
    client_file,    set_client_file    = use_state("")
    status,         set_status         = use_state("Готов к работе")
    progress,       set_progress       = use_state(0)       # 0–100 int
    elapsed,        set_elapsed        = use_state(0)
    estimated,      set_estimated      = use_state(0)
    result_file,    set_result_file    = use_state("")
    processing,     set_processing     = use_state(False)

    # ── Callbacks ─────────────────────────────────────────────────────────

    def pick_normative(_=None):
        path, _ = QFileDialog.getOpenFileName(
            None, "Нормативная база", str(NORMATIVE_DIR),
            "Документы (*.xlsx *.xls *.docx *.pdf *.txt)",
        )
        if path:
            set_normative_file(path)

    def pick_client(_=None):
        path, _ = QFileDialog.getOpenFileName(
            None, "Файл клиента", str(UPLOADS_DIR),
            "Документы (*.xlsx *.xls *.docx *.pdf)",
        )
        if path:
            set_client_file(path)

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
            # Copy normative base if new file selected (in thread — blocking IO)
            if normative_file:
                src = Path(normative_file)
                NORMATIVE_DIR.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(shutil.copy2, src, NORMATIVE_DIR / src.name)

            # Copy client file
            UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            src = Path(client_file)
            dst = UPLOADS_DIR / src.name
            await asyncio.to_thread(shutil.copy2, src, dst)
            container_path = f"{CONTAINER_UPLOADS}/{src.name}"

            est = await asyncio.to_thread(_estimate_seconds, dst)
            set_estimated(est)
            set_status(f"Обработка... (≈{_fmt(est)})")

            t0 = time.time()

            # Ticker task — updates progress every second on the event loop
            async def tick():
                while True:
                    await asyncio.sleep(1)
                    el = int(time.time() - t0)
                    set_elapsed(el)
                    set_progress(min(95, int(el * 100 / max(est, 1))))

            tick_task = asyncio.create_task(tick())

            try:
                resp = await asyncio.to_thread(
                    requests.post, API_URL,
                    json={"request_id": int(t0), "file_path": container_path,
                          "user_name": "gui_user"},
                    timeout=900,
                )
            finally:
                tick_task.cancel()

            elapsed_total = int(time.time() - t0)

            if resp.ok:
                out_name = Path(resp.json()["output_file"]).name
                set_result_file(str(UPLOADS_DIR / out_name))
                set_progress(100)
                set_status(f"Готово за {_fmt(elapsed_total)}")
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

    with Window(title="Document Assistant",
                style={"background-color": _BG, "min-width": "700px", "min-height": "520px"}):
        with VBoxView(style={"background-color": _BG, "padding": "24px"}):

            Label(text="Document Assistant",
                  style={"color": _WHITE, "font-size": "20px",
                         "font-weight": "bold", "margin-bottom": "20px"})

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
                        Label(text=f"Ожидаемое: {_fmt(estimated)}",
                              style=label_s())

            # Result button
            if result_file:
                Button(title="Открыть результат",
                       on_click=open_result,
                       style=btn(_GREEN))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    App(DocumentAssistantApp()).start()
