"""Прогон сверки по набору папок полисов и сравнение с эталоном ФСЦ.

Что делает:
  1. Обходит указанную папку и находит в ней папки полисов (ГП + ДС + Декларации).
  2. СНАЧАЛА снимает копии существующих файлов «NNN – результат проверки.xlsx»
     — это эталон с колонкой «Комментарии ФСЦ». Без этого шага прогон затёр бы
     разметку экспертов, потому что результат пишется рядом с декларацией.
  3. Прогоняет сверку по каждой декларации отдельно, замеряя время.
  4. Сравнивает новые ответы с эталонными и считает итоги.

Про честность метрики. Эксперт размечал СТАРЫЕ ответы, поэтому автоматически
можно установить только четыре вещи:
    сохранено   — эксперт сказал «верно», ответ не изменился;
    РЕГРЕСС     — эксперт сказал «верно», а ответ стал другим;
    изменено    — эксперт сказал «некорректно», ответ изменился (верен ли
                  новый ответ, может сказать только эксперт);
    не исправлено — эксперт сказал «некорректно», ответ тот же.
«Количество правильных ответов» = сохранено + изменено-и-подтверждённое, но
вторую часть посчитать без эксперта нельзя, поэтому скрипт выводит её отдельной
строкой как «требует проверки», а не приписывает себе.

Запуск:
    python tools/cargo_regression.py --root "M:\\...\\Действующие Ген. полисы"
    python tools/cargo_regression.py --root ... --compare-only   (без вызова API)
"""
import argparse
import csv
import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from openpyxl import load_workbook

DEFAULT_API = "http://127.0.0.1:8001"
RESULT_MARKER = "результат проверки"
EXPERT_COLUMN_MARKER = "ФСЦ"

# Вердикты эксперта — свободный текст, поэтому классифицируем по ключевым словам.
_CORRECT_MARKERS = ("верно", "верный")
_WRONG_MARKERS = ("некорректн", "неправильно", "ошибочно", "не учтен", "отсутств")


def classify_verdict(text: str) -> str:
    """«верно» | «неверно» | «частично» | «нет разметки»"""
    t = (text or "").strip().lower()
    if not t:
        return "нет разметки"
    if t.startswith("частично") or "частично" in t:
        return "частично"
    # «некорректно» проверяем раньше «верно»: в тексте вида «неверно» и
    # «некорректная проверка» встречается корень «верн».
    if any(m in t for m in _WRONG_MARKERS):
        return "неверно"
    if any(m in t for m in _CORRECT_MARKERS):
        return "верно"
    return "частично"


@dataclass
class RowKey:
    declaration_ref: str
    field_name: str

    def __hash__(self):
        return hash((self.declaration_ref.strip(), self.field_name.strip().lower()))

    def __eq__(self, other):
        return (self.declaration_ref.strip(), self.field_name.strip().lower()) == (
            other.declaration_ref.strip(), other.field_name.strip().lower()
        )


@dataclass
class DeclarationRun:
    policy_folder: str
    declaration: str
    seconds: float = 0.0
    http_status: int = 0
    error: str = ""
    rows_new: int = 0
    rows_baseline: int = 0
    kept_correct: int = 0
    regressions: int = 0
    changed_needs_review: int = 0
    still_wrong: int = 0
    unmatched_new: int = 0
    unmatched_baseline: int = 0
    details: list[dict] = field(default_factory=list)


def read_result_rows(path: Path) -> tuple[dict, bool]:
    """{RowKey: {'result','comment','expert'}}, есть ли колонка эксперта."""
    ws = load_workbook(path, data_only=True).active
    header = [str(ws.cell(1, c).value or "") for c in range(1, ws.max_column + 1)]
    expert_col = next((i + 1 for i, h in enumerate(header) if EXPERT_COLUMN_MARKER in h), None)

    rows = {}
    for r in range(2, ws.max_row + 1):
        ref = str(ws.cell(r, 1).value or "").strip()
        fld = str(ws.cell(r, 2).value or "").strip()
        if not ref and not fld:
            continue
        rows[RowKey(ref, fld)] = {
            "result": str(ws.cell(r, 4).value or "").strip(),
            "comment": str(ws.cell(r, 5).value or "").strip(),
            "expert": str(ws.cell(r, expert_col).value or "").strip() if expert_col else "",
        }
    return rows, expert_col is not None


def find_policy_folders(root: Path) -> list[Path]:
    """Папка считается папкой полиса, если рядом есть ГП или папка ДС/Декларации."""
    from document_assistant.cargo.filename_parsing import PolicyFilenameParser
    from document_assistant.cargo.policy_discovery import PolicyFolderScanner

    parser = PolicyFilenameParser()
    scanner = PolicyFolderScanner(parser)
    found = []
    for candidate in [root, *sorted(p for p in root.iterdir() if p.is_dir())]:
        try:
            has_policy = scanner.find_policy_file(str(candidate)) is not None
        except Exception:
            has_policy = False
        has_ds = scanner.resolve_ds_folder(str(candidate)) is not None
        has_decl = (candidate / "Декларации").is_dir()
        if has_policy or (has_ds and has_decl):
            found.append(candidate)
    return found


def snapshot_baselines(policy_folder: Path, store: Path) -> dict[str, Path]:
    """Копируем существующие отчёты ДО прогона — иначе сверка их перезапишет."""
    store.mkdir(parents=True, exist_ok=True)
    saved = {}
    for f in policy_folder.rglob(f"*{RESULT_MARKER}*.xlsx"):
        target = store / f"{policy_folder.name}__{f.name}"
        shutil.copy2(f, target)
        saved[f.name] = target
    return saved


def list_declarations(policy_folder: Path) -> list[Path]:
    from document_assistant.cargo.declaration_discovery import DeclarationDiscovery

    return [Path(p) for p in DeclarationDiscovery.resolve(str(policy_folder), None)]


def compare(baseline: dict, new: dict) -> dict:
    """Сопоставление по (номер строки, наименование поля)."""
    stats = dict(kept_correct=0, regressions=0, changed_needs_review=0,
                 still_wrong=0, unmatched_new=0, unmatched_baseline=0, details=[])

    for key, base in baseline.items():
        verdict = classify_verdict(base["expert"])
        cur = new.get(key)
        if cur is None:
            stats["unmatched_baseline"] += 1
            continue
        same = cur["result"].strip().lower() == base["result"].strip().lower()
        if verdict == "верно":
            if same:
                stats["kept_correct"] += 1
            else:
                stats["regressions"] += 1
                stats["details"].append({
                    "тип": "РЕГРЕСС", "строка": key.declaration_ref, "поле": key.field_name,
                    "было": base["result"], "стало": cur["result"], "вердикт ФСЦ": base["expert"][:80],
                })
        elif verdict in ("неверно", "частично"):
            if same:
                stats["still_wrong"] += 1
                stats["details"].append({
                    "тип": "не исправлено", "строка": key.declaration_ref, "поле": key.field_name,
                    "было": base["result"], "стало": cur["result"], "вердикт ФСЦ": base["expert"][:80],
                })
            else:
                stats["changed_needs_review"] += 1
                stats["details"].append({
                    "тип": "изменено, нужна проверка", "строка": key.declaration_ref,
                    "поле": key.field_name, "было": base["result"], "стало": cur["result"],
                    "вердикт ФСЦ": base["expert"][:80],
                })

    stats["unmatched_new"] = sum(1 for k in new if k not in baseline)
    return stats


def run_one(api: str, policy_folder: Path, declaration: Path,
            force_rebuild: bool, timeout: float) -> tuple[float, int, str, dict]:
    payload = {
        "request_id": int(time.time()),
        "policy_folder": str(policy_folder),
        "declaration_paths": [str(declaration)],
        "force_rebuild_matrix": force_rebuild,
    }
    started = time.perf_counter()
    try:
        resp = httpx.post(f"{api}/api/reconcile", json=payload, timeout=timeout)
        elapsed = time.perf_counter() - started
        if resp.status_code != 200:
            return elapsed, resp.status_code, resp.text[:300], {}
        return elapsed, 200, "", resp.json()
    except Exception as e:
        return time.perf_counter() - started, 0, f"{type(e).__name__}: {e}"[:300], {}


def main() -> int:
    ap = argparse.ArgumentParser(description="Регрессионный прогон сверки грузов")
    ap.add_argument("--root", required=True, help="Папка с папками полисов")
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--out", default="reports/cargo_regression")
    ap.add_argument("--timeout", type=float, default=3600.0, help="Таймаут одного запроса, сек")
    ap.add_argument("--compare-only", action="store_true",
                    help="Не вызывать API: только сравнить текущие отчёты с эталоном")
    ap.add_argument("--limit", type=int, default=0, help="Обработать не больше N деклараций")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    root = Path(args.root)
    if not root.is_dir():
        print(f"[ERROR] Папка не найдена: {root}")
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    baseline_store = out / "baseline"

    policy_folders = find_policy_folders(root)
    if not policy_folders:
        print(f"[ERROR] В {root} не найдено ни одной папки полиса (нужны ГП и/или ДС + Декларации)")
        return 2
    print(f"[INFO] Папок полисов: {len(policy_folders)}")

    runs: list[DeclarationRun] = []
    processed = 0

    for pf in policy_folders:
        print(f"\n=== {pf.name} ===")
        baselines = snapshot_baselines(pf, baseline_store)
        print(f"[INFO] Снято эталонов: {len(baselines)}")

        declarations = list_declarations(pf)
        if not declarations:
            print("[WARN] Деклараций не найдено — пропуск")
            continue

        first = True
        for decl in declarations:
            if args.limit and processed >= args.limit:
                break
            processed += 1
            run = DeclarationRun(policy_folder=pf.name, declaration=decl.name)

            if args.compare_only:
                run.seconds = 0.0
                run.http_status = 200
            else:
                # Матрицу строим один раз на папку, дальше берём из кэша —
                # иначе при force_rebuild=true по умолчанию она пересобиралась
                # бы для каждой декларации и прогон растянулся бы на часы.
                elapsed, status, err, _ = run_one(args.api, pf, decl, first, args.timeout)
                first = False
                run.seconds, run.http_status, run.error = elapsed, status, err
                if status != 200:
                    print(f"[FAIL] {decl.name}: HTTP {status} за {elapsed:.1f}с — {err[:120]}")
                    runs.append(run)
                    continue

            result_file = next(
                (f for f in decl.parent.glob(f"*{RESULT_MARKER}*.xlsx")
                 if f.stem.split()[0].lstrip("0") == decl.stem.split()[0].lstrip("0")),
                None,
            )
            if result_file is None or not result_file.exists():
                run.error = "файл результата не найден"
                print(f"[WARN] {decl.name}: результат не найден")
                runs.append(run)
                continue

            new_rows, _ = read_result_rows(result_file)
            run.rows_new = len(new_rows)

            base_path = baselines.get(result_file.name)
            if base_path is None:
                run.error = "нет эталона для сравнения"
                print(f"[INFO] {decl.name}: {run.rows_new} строк за {run.seconds:.1f}с (эталона нет)")
                runs.append(run)
                continue

            base_rows, has_expert = read_result_rows(base_path)
            run.rows_baseline = len(base_rows)
            if not has_expert:
                run.error = "в эталоне нет колонки «Комментарии ФСЦ»"

            stats = compare(base_rows, new_rows)
            for k in ("kept_correct", "regressions", "changed_needs_review",
                      "still_wrong", "unmatched_new", "unmatched_baseline"):
                setattr(run, k, stats[k])
            run.details = stats["details"]

            print(
                f"[OK]   {decl.name}: {run.seconds:6.1f}с | строк {run.rows_new:4} | "
                f"сохранено верных {run.kept_correct:3} | регресс {run.regressions:3} | "
                f"изменено {run.changed_needs_review:3} | не исправлено {run.still_wrong:3}"
            )
            runs.append(run)

    _write_reports(out, runs)
    _print_summary(runs)
    return 1 if any(r.regressions or r.http_status not in (0, 200) for r in runs) else 0


def _write_reports(out: Path, runs: list[DeclarationRun]) -> None:
    summary_csv = out / "summary.csv"
    with summary_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Папка полиса", "Декларация", "Секунд", "HTTP", "Строк новых",
                    "Строк эталона", "Сохранено верных", "Регресс",
                    "Изменено (нужна проверка)", "Не исправлено",
                    "Новых строк вне эталона", "Строк эталона без пары", "Ошибка"])
        for r in runs:
            w.writerow([r.policy_folder, r.declaration, f"{r.seconds:.1f}", r.http_status,
                        r.rows_new, r.rows_baseline, r.kept_correct, r.regressions,
                        r.changed_needs_review, r.still_wrong,
                        r.unmatched_new, r.unmatched_baseline, r.error])

    details_csv = out / "details.csv"
    with details_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Декларация", "Тип", "Строка", "Поле", "Было", "Стало", "Вердикт ФСЦ"])
        for r in runs:
            for d in r.details:
                w.writerow([r.declaration, d["тип"], d["строка"], d["поле"],
                            d["было"], d["стало"], d["вердикт ФСЦ"]])

    (out / "runs.json").write_text(
        json.dumps([r.__dict__ for r in runs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n[INFO] Отчёты: {summary_csv}, {details_csv}")


def _print_summary(runs: list[DeclarationRun]) -> None:
    ok = [r for r in runs if r.http_status == 200 and not r.error]
    failed = [r for r in runs if r.http_status not in (0, 200)]
    total_rows = sum(r.rows_new for r in runs)
    kept = sum(r.kept_correct for r in runs)
    regr = sum(r.regressions for r in runs)
    changed = sum(r.changed_needs_review for r in runs)
    still = sum(r.still_wrong for r in runs)
    graded = kept + regr + changed + still

    print("\n" + "=" * 62)
    print("ИТОГИ")
    print("=" * 62)
    print(f"Деклараций обработано      : {len(runs)} (успешно {len(ok)}, ошибок {len(failed)})")
    print(f"Строк в новых отчётах      : {total_rows}")
    print()
    print(f"Размечено экспертом ранее  : {graded}")
    if graded:
        print(f"  сохранено верных         : {kept:4}  ({100*kept//graded}%)")
        print(f"  РЕГРЕСС (было верно)     : {regr:4}  ({100*regr//graded}%)")
        print(f"  изменено, нужна проверка : {changed:4}  ({100*changed//graded}%)")
        print(f"  не исправлено            : {still:4}  ({100*still//graded}%)")
    print()
    if runs:
        times = [r.seconds for r in runs if r.seconds > 0]
        if times:
            print(f"Время на декларацию        : всего {sum(times):.0f}с, "
                  f"медиана {sorted(times)[len(times)//2]:.1f}с, макс {max(times):.1f}с")
            slowest = sorted(runs, key=lambda r: -r.seconds)[:3]
            for r in slowest:
                if r.seconds > 0:
                    print(f"  дольше всего: {r.declaration} — {r.seconds:.1f}с ({r.rows_new} строк)")
    if failed:
        print("\nОшибки:")
        for r in failed:
            print(f"  {r.declaration}: HTTP {r.http_status} — {r.error[:100]}")
    print("=" * 62)
    print("«Изменено, нужна проверка» — строки, где прежний ответ эксперт признал")
    print("неверным и ответ изменился. Верен ли новый, отметьте в details.csv.")


if __name__ == "__main__":
    raise SystemExit(main())
