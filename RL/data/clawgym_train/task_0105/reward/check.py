import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None


def _is_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            header = f.read(5)
            return header == b"%PDF-"
    except Exception:
        return False


def _parse_iso8601_utc(s: str) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    try:
        s2 = s.strip()
        if s2.endswith("Z"):
            dt = datetime.fromisoformat(s2.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            return False
        return dt.utcoffset() == timezone.utc.utcoffset(dt)
    except Exception:
        return False


def _safe_int(s: Any) -> Optional[int]:
    try:
        if s is None:
            return None
        if isinstance(s, int):
            return s
        if isinstance(s, float):
            return int(s)
        s2 = str(s).strip()
        if not s2:
            return None
        return int(s2)
    except Exception:
        return None


def _word_count(s: str) -> int:
    return len([w for w in s.strip().split() if w])


def _load_packages_list(workspace: Path) -> List[str]:
    pkgs_path = workspace / "input" / "packages.txt"
    content = _read_text(pkgs_path)
    if content is None:
        return []
    pkgs = []
    for line in content.splitlines():
        t = line.strip()
        if t:
            pkgs.append(t)
    return pkgs


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "csv_exists_and_columns": 0.0,
        "csv_row_count_matches_input": 0.0,
        "csv_field_values_valid": 0.0,
        "stats_exists_and_schema": 0.0,
        "stats_values_match_csv": 0.0,
        "raw_pages_count_and_types_match": 0.0,
        "notes_bullets_constraints": 0.0,
        "report_pdf_valid": 0.0,
        "build_log_exists_and_engine": 0.0,
        "errors_summary_correctness": 0.0,
        "run_sh_present_and_logs": 0.0,
        "scripts_dir_present": 0.0,
        "readme_usage_instructions": 0.0,
    }

    csv_path = workspace / "output" / "ctan_metadata.csv"
    stats_path = workspace / "output" / "stats.json"
    raw_dir = workspace / "output" / "raw"
    notes_path = workspace / "output" / "notes_rewritten.md"
    pdf_path = workspace / "output" / "report.pdf"
    build_log_path = workspace / "output" / "build.log"
    errors_path = workspace / "output" / "errors.txt"
    run_sh_path = workspace / "run.sh"
    readme_path = workspace / "README.md"

    pkgs_list = _load_packages_list(workspace)
    csv_rows = _read_csv_dicts(csv_path)
    stats_json = _read_json(stats_path)
    build_log = _read_text(build_log_path)
    errors_txt = _read_text(errors_path)
    notes_text = _read_text(notes_path)
    readme_text = _read_text(readme_path)

    # 1) CSV existence and required columns
    required_columns = [
        "package",
        "source_type",
        "retrieved_at",
        "http_status",
        "name",
        "version",
        "license",
        "description",
        "description_length",
    ]
    if csv_rows is not None:
        header_fields = []
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header_fields = next(reader, [])
        except Exception:
            header_fields = []
        if header_fields and set(required_columns).issubset(set(header_fields)):
            scores["csv_exists_and_columns"] = 1.0

    # 2) CSV row count matches input packages and package names alignment
    if csv_rows is not None and pkgs_list:
        csv_packages = [row.get("package", "").strip() for row in csv_rows]
        if len(csv_rows) == len(pkgs_list):
            if Counter(csv_packages) == Counter([p.strip() for p in pkgs_list]):
                scores["csv_row_count_matches_input"] = 1.0

    # 3) CSV field value validations
    csv_field_valid = False
    if csv_rows is not None:
        all_ok = True
        for row in csv_rows:
            st = row.get("source_type", "").strip().lower()
            if st not in {"html", "json"}:
                all_ok = False
                break
            hs_raw = row.get("http_status", "")
            hs = _safe_int(hs_raw)
            if hs is None or hs < 0:
                all_ok = False
                break
            rt = row.get("retrieved_at", "")
            if not _parse_iso8601_utc(rt):
                all_ok = False
                break
            desc = row.get("description", "")
            dl = _safe_int(row.get("description_length", ""))
            if dl is None or dl != len(desc):
                all_ok = False
                break
        csv_field_valid = all_ok
    if csv_field_valid:
        scores["csv_field_values_valid"] = 1.0

    # 4) stats.json existence and schema
    stats_schema_ok = False
    if isinstance(stats_json, dict):
        needed_keys = {
            "total_packages",
            "success_count",
            "failure_count",
            "avg_description_length",
            "licenses",
            "statuses",
            "source_types",
            "downloaded_pages_count",
        }
        if needed_keys.issubset(set(stats_json.keys())):
            tp = _safe_int(stats_json.get("total_packages"))
            sc = _safe_int(stats_json.get("success_count"))
            fc = _safe_int(stats_json.get("failure_count"))
            try:
                adl = float(stats_json.get("avg_description_length"))
            except Exception:
                adl = None
            licenses_ok = isinstance(stats_json.get("licenses"), dict)
            statuses_ok = isinstance(stats_json.get("statuses"), dict)
            stypes_ok = isinstance(stats_json.get("source_types"), dict)
            dpc = _safe_int(stats_json.get("downloaded_pages_count"))
            if (
                tp is not None
                and sc is not None
                and fc is not None
                and adl is not None
                and licenses_ok
                and statuses_ok
                and stypes_ok
                and dpc is not None
            ):
                stats_schema_ok = True
    if stats_schema_ok:
        scores["stats_exists_and_schema"] = 1.0

    # 5) stats values match recomputed aggregates from CSV and raw dir
    stats_match_ok = False
    if stats_schema_ok and csv_rows is not None:
        try:
            total = len(csv_rows)
            statuses_count: Dict[str, int] = {}
            licenses_count: Dict[str, int] = {}
            stypes_count: Dict[str, int] = {}
            desc_lengths: List[int] = []
            success_count = 0
            for r in csv_rows:
                hs = r.get("http_status", "")
                hs_val = _safe_int(hs)
                hs_str = str(hs_val if hs_val is not None else hs).strip()
                if hs_str == "200":
                    success_count += 1
                statuses_count[hs_str] = statuses_count.get(hs_str, 0) + 1
                lic = r.get("license", "")
                licenses_count[lic] = licenses_count.get(lic, 0) + 1
                st = r.get("source_type", "").strip().lower()
                stypes_count[st] = stypes_count.get(st, 0) + 1
                dl = _safe_int(r.get("description_length", ""))
                if dl is None:
                    dl = len(r.get("description", ""))
                desc_lengths.append(dl)
            failure_count = total - success_count
            avg_len = round((sum(desc_lengths) / total) if total else 0.0, 1)

            raw_count = 0
            if raw_dir.exists() and raw_dir.is_dir():
                for p in raw_dir.glob("*"):
                    if p.is_file() and p.suffix.lower() in {".html", ".json"}:
                        raw_count += 1

            sj = stats_json
            conds = []
            conds.append(_safe_int(sj.get("total_packages")) == total)
            conds.append(_safe_int(sj.get("success_count")) == success_count)
            conds.append(_safe_int(sj.get("failure_count")) == failure_count)
            try:
                conds.append(round(float(sj.get("avg_description_length")), 1) == avg_len)
            except Exception:
                conds.append(False)

            sj_licenses = sj.get("licenses", {})
            if isinstance(sj_licenses, dict):
                norm_sj_licenses = {str(k): _safe_int(v) for k, v in sj_licenses.items()}
                if all(v is not None for v in norm_sj_licenses.values()):
                    conds.append(norm_sj_licenses == licenses_count)
                else:
                    conds.append(False)
            else:
                conds.append(False)

            sj_statuses = sj.get("statuses", {})
            if isinstance(sj_statuses, dict):
                norm_sj_statuses = {str(k): _safe_int(v) for k, v in sj_statuses.items()}
                if all(v is not None for v in norm_sj_statuses.values()):
                    conds.append(norm_sj_statuses == statuses_count)
                else:
                    conds.append(False)
            else:
                conds.append(False)

            sj_stypes = sj.get("source_types", {})
            if isinstance(sj_stypes, dict):
                norm_sj_stypes = {str(k).lower(): _safe_int(v) for k, v in sj_stypes.items()}
                if all(v is not None for v in norm_sj_stypes.values()):
                    conds.append(norm_sj_stypes == stypes_count)
                else:
                    conds.append(False)
            else:
                conds.append(False)

            conds.append(_safe_int(sj.get("downloaded_pages_count")) == raw_count == total)
            stats_match_ok = all(conds)
        except Exception:
            stats_match_ok = False
    if stats_match_ok:
        scores["stats_values_match_csv"] = 1.0

    # 6) raw pages count and types match with CSV source_type distribution
    raw_match_ok = False
    if csv_rows is not None:
        try:
            csv_html = sum(1 for r in csv_rows if r.get("source_type", "").strip().lower() == "html")
            csv_json = sum(1 for r in csv_rows if r.get("source_type", "").strip().lower() == "json")
            raw_html = 0
            raw_json = 0
            raw_total = 0
            if raw_dir.exists() and raw_dir.is_dir():
                for p in raw_dir.glob("*"):
                    if p.is_file():
                        if p.suffix.lower() == ".html":
                            raw_html += 1
                            raw_total += 1
                        elif p.suffix.lower() == ".json":
                            raw_json += 1
                            raw_total += 1
            if raw_total == len(csv_rows) and raw_html == csv_html and raw_json == csv_json:
                raw_match_ok = True
        except Exception:
            raw_match_ok = False
    if raw_match_ok:
        scores["raw_pages_count_and_types_match"] = 1.0

    # 7) notes rewriting constraints: at most 8 bullets; each bullet <= 20 words
    notes_ok = False
    if isinstance(notes_text, str):
        bullets = []
        for line in notes_text.splitlines():
            l = line.strip()
            if l.startswith("- "):
                bullets.append(l[2:].strip())
            elif l.startswith("* "):
                bullets.append(l[2:].strip())
        if 1 <= len(bullets) <= 8 and all(_word_count(b) <= 20 for b in bullets):
            notes_ok = True
    if notes_ok:
        scores["notes_bullets_constraints"] = 1.0

    # 8) report.pdf validity
    if pdf_path.exists() and pdf_path.is_file() and _is_pdf(pdf_path):
        scores["report_pdf_valid"] = 1.0

    # 9) build.log exists and includes chosen LaTeX engine mention
    engine_ok = False
    if isinstance(build_log, str) and build_log.strip():
        if re.search(r"\b(pdflatex|xelatex|lualatex|latexmk)\b", build_log, re.IGNORECASE):
            engine_ok = True
    if engine_ok:
        scores["build_log_exists_and_engine"] = 1.0

    # 10) errors summary consistency
    errors_ok = False
    if isinstance(build_log, str):
        error_lines = [ln for ln in build_log.splitlines() if re.search(r"error", ln, re.IGNORECASE)]
        warning_lines = [ln for ln in build_log.splitlines() if re.search(r"warning", ln, re.IGNORECASE)]
        has_issues = (len(error_lines) + len(warning_lines)) > 0
        if has_issues:
            if isinstance(errors_txt, str) and errors_txt.strip():
                has_exit_code = re.search(r"exit\s*code", errors_txt, re.IGNORECASE) is not None
                err_count_ok = False
                warn_count_ok = False
                for m in re.finditer(r"errors?\D+(\d+)", errors_txt, re.IGNORECASE):
                    if _safe_int(m.group(1)) == len(error_lines):
                        err_count_ok = True
                        break
                for m in re.finditer(r"warnings?\D+(\d+)", errors_txt, re.IGNORECASE):
                    if _safe_int(m.group(1)) == len(warning_lines):
                        warn_count_ok = True
                        break
                if not err_count_ok:
                    for m in re.finditer(r"error\s+count\D+(\d+)", errors_txt, re.IGNORECASE):
                        if _safe_int(m.group(1)) == len(error_lines):
                            err_count_ok = True
                            break
                if not warn_count_ok:
                    for m in re.finditer(r"warning\s+count\D+(\d+)", errors_txt, re.IGNORECASE):
                        if _safe_int(m.group(1)) == len(warning_lines):
                            warn_count_ok = True
                            break
                if has_exit_code and err_count_ok and warn_count_ok:
                    errors_ok = True
                else:
                    errors_ok = False
            else:
                errors_ok = False
        else:
            if not errors_path.exists():
                errors_ok = True
            else:
                if isinstance(errors_txt, str):
                    zero_err = re.search(r"errors?\D+0", errors_txt or "", re.IGNORECASE)
                    zero_warn = re.search(r"warnings?\D+0", errors_txt or "", re.IGNORECASE)
                    zero_exit = re.search(r"exit\s*code", errors_txt or "", re.IGNORECASE)
                    if zero_exit and zero_err and zero_warn:
                        errors_ok = True
                    else:
                        errors_ok = False
                else:
                    errors_ok = False
    if errors_ok:
        scores["errors_summary_correctness"] = 1.0

    # 11) run.sh presence and logs to output/build.log
    run_ok = False
    run_text = _read_text(run_sh_path)
    if isinstance(run_text, str):
        logs_ref = "build.log" in run_text
        orchestrates_ref = ("ctan" in run_text.lower()) or ("ctan_metadata.csv" in run_text) or ("report.pdf" in run_text)
        run_ok = logs_ref and orchestrates_ref
    if run_ok:
        scores["run_sh_present_and_logs"] = 1.0

    # 12) scripts dir present with at least one .py or .sh
    scripts_ok = False
    scripts_dir = workspace / "scripts"
    if scripts_dir.exists() and scripts_dir.is_dir():
        has_script = any(p.is_file() and p.suffix in {".py", ".sh"} for p in scripts_dir.glob("*"))
        if has_script:
            scripts_ok = True
    if scripts_ok:
        scores["scripts_dir_present"] = 1.0

    # 13) README usage instructions
    readme_ok = False
    if isinstance(readme_text, str):
        has_run = re.search(r"\brun\.sh\b", readme_text, re.IGNORECASE) is not None
        has_output = re.search(r"\boutput\b", readme_text, re.IGNORECASE) is not None
        readme_ok = has_run and has_output
    if readme_ok:
        scores["readme_usage_instructions"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()