import json
import csv
import sys
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            return [dict(row) for row in rdr]
    except Exception:
        return None


def _parse_bool(s: str) -> Optional[bool]:
    if s is None:
        return None
    sl = s.strip().lower()
    if sl in ("true", "t", "1", "yes", "y"):
        return True
    if sl in ("false", "f", "0", "no", "n"):
        return False
    return None


def _float_eq(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _expected_scale(specimen_csv: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    records = _read_csv_dicts(specimen_csv)
    if records is None:
        return None
    panel_height_mm = 90.0
    label_block_mm = 8.0
    padding_mm = 2.0
    available_mm = panel_height_mm - label_block_mm - (2 * padding_mm)
    expected: Dict[str, Dict[str, Any]] = {}
    for row in records:
        try:
            species = row["species"].strip()
            dlen = float(row["dorsal_view_length_mm"])
        except Exception:
            return None
        scale_factor_percent = round(100.0 * min(1.0, available_mm / dlen), 1)
        fits = available_mm >= dlen
        expected[species] = {
            "dorsal_view_mm": dlen,
            "available_mm": available_mm,
            "scale_factor_percent": scale_factor_percent,
            "fits": fits,
        }
    return expected


def _parse_scale_plan_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, Any]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.reader(f)
            rows = list(rdr)
    except Exception:
        return None
    if not rows:
        return None
    header = rows[0]
    body = rows[1:]
    parsed: List[Dict[str, Any]] = []
    for r in body:
        if not r or all(not cell.strip() for cell in r):
            continue
        row_dict = {}
        try:
            row_dict["species"] = r[0].strip()
            row_dict["dorsal_view_mm"] = float(r[1])
            row_dict["available_mm"] = float(r[2])
            row_dict["scale_factor_percent"] = float(r[3])
            fits_val = r[4].strip()
            fits = _parse_bool(fits_val)
            if fits is None:
                if fits_val in ("True", "False"):
                    fits = fits_val == "True"
                else:
                    return None
            row_dict["fits"] = fits
        except Exception:
            return None
        parsed.append(row_dict)
    return header, parsed


def _run_expected_check_assets(cmd_script: Path, assets_json: Path) -> Tuple[List[Tuple[str, str, str]], int, Tuple[int, int]]:
    expected_messages: List[Tuple[str, str, str]] = []
    data = _read_json(assets_json) or {}
    errors = 0
    warnings = 0
    for species, info in data.items():
        has = bool(info.get('has_dorsal_photo'))
        dpi = int(info.get('dpi') or 0)
        credit = (info.get('credit') or '').strip()
        license_ok = bool(info.get('license_approved'))
        if not has:
            expected_messages.append(("ERROR", species, "Missing dorsal photo"))
            errors += 1
        if not license_ok:
            expected_messages.append(("ERROR", species, "License not approved"))
            errors += 1
        if has and dpi < 300:
            expected_messages.append(("WARNING", species, f"DPI below 300: {dpi}"))
            warnings += 1
        if has and not credit:
            expected_messages.append(("WARNING", species, "Missing credit metadata"))
            warnings += 1
    exit_code = 1 if errors > 0 else 0
    return expected_messages, exit_code, (errors, warnings)


def _parse_check_assets_output(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    messages: List[Tuple[str, str, str]] = []
    for ln in lines:
        m = re.match(r"^(ERROR|WARNING) \[(.+?)\] (.+)$", ln.strip())
        if m:
            messages.append((m.group(1), m.group(2), m.group(3)))
    exit_code: Optional[int] = None
    for ln in reversed(lines):
        m = re.match(r"^\s*Exit code:\s*(-?\d+)\s*$", ln)
        if m:
            try:
                exit_code = int(m.group(1))
            except Exception:
                exit_code = None
            break
    summary: Optional[Tuple[int, int]] = None
    for ln in lines:
        m = re.match(r"^Summary:\s*(\d+)\s*errors,\s*(\d+)\s*warnings\s*$", ln)
        if m:
            try:
                summary = (int(m.group(1)), int(m.group(2)))
            except Exception:
                summary = None
            break
    return {"messages": messages, "exit_code": exit_code, "summary": summary}


def _load_log_analysis_json(path: Path) -> Optional[List[Dict[str, Any]]]:
    arr = _read_json(path)
    if not isinstance(arr, list):
        return None
    norm = []
    for it in arr:
        if not isinstance(it, dict):
            return None
        t = it.get("type")
        s = it.get("species")
        m = it.get("message")
        if not (isinstance(t, str) and isinstance(s, str) and isinstance(m, str)):
            return None
        norm.append({"type": t, "species": s, "message": m})
    return norm


def _counter_tuples(items: List[Tuple[str, str, str]]) -> Dict[Tuple[str, str, str], int]:
    c: Dict[Tuple[str, str, str], int] = {}
    for it in items:
        c[it] = c.get(it, 0) + 1
    return c


def _find_section(text: str, title: str, all_titles: List[str]) -> Optional[str]:
    lines = text.splitlines()
    title_l = title.strip().lower()
    start_idx = None
    for i, ln in enumerate(lines):
        ln_norm = ln.strip().lower()
        if ln_norm == title_l or (ln_norm.startswith("#") and title_l in ln_norm):
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        ln_norm = lines[j].strip().lower()
        for t in all_titles:
            tl = t.strip().lower()
            if ln_norm == tl or (ln_norm.startswith("#") and tl in ln_norm):
                end_idx = j
                break
        if end_idx != len(lines) and end_idx == j:
            break
    section = "\n".join(lines[start_idx:end_idx]).strip()
    return section


def _line_mentions_fit(line: str, expected_fits: bool) -> bool:
    l = line.lower()
    if expected_fits:
        if "does not fit" in l or "doesn't fit" in l or "not fit" in l:
            return False
        return "fit" in l
    else:
        return ("does not fit" in l) or ("doesn't fit" in l) or ("not fit" in l)


def _extract_numbered_items(section_text: str) -> List[str]:
    items = []
    for ln in section_text.splitlines():
        if re.match(r"^\s*\d+[.)]\s+", ln):
            items.append(ln)
    return items


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "scale_plan_exists_and_header": 0.0,
        "scale_plan_species_coverage": 0.0,
        "scale_plan_values_correct": 0.0,
        "check_assets_output_exit_code_and_summary": 0.0,
        "check_assets_output_messages": 0.0,
        "log_analysis_json_valid": 0.0,
        "log_analysis_matches_expected": 0.0,
        "meeting_notes_has_sections": 0.0,
        "meeting_notes_scale_decisions_coverage": 0.0,
        "meeting_notes_asset_issues_coverage": 0.0,
        "meeting_notes_open_questions_coverage": 0.0,
        "meeting_notes_next_steps_count": 0.0,
    }

    input_specimen = workspace / "input" / "specimen_measurements.csv"
    input_assets = workspace / "input" / "assets_status.json"
    input_field_notes = workspace / "input" / "field_notes.html"
    scripts_check = workspace / "scripts" / "check_assets.py"

    out_dir = workspace / "output"
    scale_plan_csv = out_dir / "scale_plan.csv"
    check_assets_output_txt = out_dir / "check_assets_output.txt"
    log_analysis_json = out_dir / "log_analysis.json"
    meeting_notes_md = out_dir / "meeting_notes.md"

    expected_scale = _expected_scale(input_specimen)
    parsed_scale = None
    if scale_plan_csv.exists():
        parsed_scale = _parse_scale_plan_csv(scale_plan_csv)

    required_header = ["species", "dorsal_view_mm", "available_mm", "scale_factor_percent", "fits"]
    if parsed_scale is not None:
        header, body = parsed_scale
        if header == required_header and body:
            scores["scale_plan_exists_and_header"] = 1.0

    if expected_scale is not None and parsed_scale is not None:
        _, body = parsed_scale
        output_species = [row["species"] for row in body]
        exp_species = set(expected_scale.keys())
        out_species_set = set(output_species)
        matched = len(exp_species & out_species_set)
        total = len(exp_species)
        denom = max(total, len(out_species_set))
        scores["scale_plan_species_coverage"] = (matched / denom) if denom > 0 else 0.0

    if expected_scale is not None and parsed_scale is not None:
        _, body = parsed_scale
        correct = 0
        total = len(expected_scale)
        for species, exp in expected_scale.items():
            rows = [r for r in body if r["species"] == species]
            if len(rows) != 1:
                continue
            r = rows[0]
            ok = (
                _float_eq(r["dorsal_view_mm"], float(exp["dorsal_view_mm"])) and
                _float_eq(r["available_mm"], float(exp["available_mm"])) and
                _float_eq(r["scale_factor_percent"], float(exp["scale_factor_percent"])) and
                (bool(r["fits"]) == bool(exp["fits"]))
            )
            if ok:
                correct += 1
        if total > 0:
            scores["scale_plan_values_correct"] = correct / total

    expected_messages, expected_exit_code, (exp_errs, exp_warns) = _run_expected_check_assets(scripts_check, input_assets)
    parsed_assets_output = None
    if check_assets_output_txt.exists():
        parsed_assets_output = _parse_check_assets_output(check_assets_output_txt)
    if parsed_assets_output is not None:
        ec_ok = (parsed_assets_output.get("exit_code") == expected_exit_code)
        summary = parsed_assets_output.get("summary")
        summary_ok = (summary == (exp_errs, exp_warns))
        text = _read_text(check_assets_output_txt) or ""
        nonempty_lines = [ln for ln in text.splitlines() if ln.strip()]
        last_has_exit = False
        if nonempty_lines:
            m = re.match(r"^\s*Exit code:\s*(-?\d+)\s*$", nonempty_lines[-1])
            if m:
                try:
                    last_has_exit = int(m.group(1)) == expected_exit_code
                except Exception:
                    last_has_exit = False
        if ec_ok and summary_ok and last_has_exit:
            scores["check_assets_output_exit_code_and_summary"] = 1.0

    if parsed_assets_output is not None:
        got_msgs = parsed_assets_output.get("messages") or []
        exp_counter = _counter_tuples(expected_messages)
        got_counter = _counter_tuples(got_msgs)
        matched = 0
        for k, v in exp_counter.items():
            matched += min(v, got_counter.get(k, 0))
        expected_total = sum(exp_counter.values())
        extras = 0
        for k, v in got_counter.items():
            if k not in exp_counter:
                extras += v
            else:
                if v > exp_counter[k]:
                    extras += v - exp_counter[k]
        denom = expected_total + extras
        score = (matched / denom) if denom > 0 else 0.0
        scores["check_assets_output_messages"] = score

    log_arr = None
    if log_analysis_json.exists():
        log_arr = _load_log_analysis_json(log_analysis_json)
    if log_arr is not None:
        scores["log_analysis_json_valid"] = 1.0

    if log_arr is not None:
        got = [(it["type"], it["species"], it["message"]) for it in log_arr]
        exp_counter = _counter_tuples(expected_messages)
        got_counter = _counter_tuples(got)
        matched = 0
        for k, v in exp_counter.items():
            matched += min(v, got_counter.get(k, 0))
        expected_total = sum(exp_counter.values())
        extras = 0
        for k, v in got_counter.items():
            if k not in exp_counter:
                extras += v
            else:
                if v > exp_counter[k]:
                    extras += v - exp_counter[k]
        denom = expected_total + extras
        score = (matched / denom) if denom > 0 else 0.0
        scores["log_analysis_matches_expected"] = score

    meeting_text = None
    if meeting_notes_md.exists():
        meeting_text = _read_text(meeting_notes_md)
    sections = ["Summary", "Scale decisions", "Asset issues", "Open questions from field notes", "Next steps"]
    if meeting_text:
        found_count = 0
        for t in sections:
            sec = _find_section(meeting_text, t, sections)
            if sec is not None and len(sec.strip()) > 0:
                found_count += 1
        scores["meeting_notes_has_sections"] = found_count / len(sections)

        scale_sec = _find_section(meeting_text, "Scale decisions", sections)
        if scale_sec and expected_scale is not None:
            covered = 0
            total = len(expected_scale)
            for sp, exp in expected_scale.items():
                lines = [ln for ln in scale_sec.splitlines() if sp in ln]
                if not lines:
                    continue
                expected_scale_str = f"{exp['scale_factor_percent']:.1f}"
                found_scale = any(expected_scale_str in ln for ln in lines)
                found_fit = any(_line_mentions_fit(ln, bool(exp["fits"])) for ln in lines)
                if found_scale and found_fit:
                    covered += 1
            if total > 0:
                scores["meeting_notes_scale_decisions_coverage"] = covered / total

        assets_sec = _find_section(meeting_text, "Asset issues", sections)
        if assets_sec:
            def msg_keywords(msg: str) -> List[str]:
                ml = msg.lower()
                if "missing dorsal photo" in ml:
                    return ["missing", "photo"]
                if "license not approved" in ml:
                    return ["license", "approv"]
                if "dpi below" in ml:
                    return ["dpi", "below"]
                if "missing credit metadata" in ml:
                    return ["missing", "credit"]
                return [tok for tok in re.findall(r"[a-z]+", ml) if len(tok) > 3][:2]

            cov = 0
            tot = len(expected_messages)
            for t, sp, msg in expected_messages:
                sec_l = assets_sec.lower()
                if sp not in assets_sec:
                    continue
                kws = msg_keywords(msg)
                if all(k in sec_l for k in kws):
                    cov += 1
            if tot > 0:
                scores["meeting_notes_asset_issues_coverage"] = cov / tot

        open_sec = _find_section(meeting_text, "Open questions from field notes", sections)
        if open_sec:
            field_notes_text = _read_text(input_field_notes) or ""
            species_in_notes = []
            for m in re.finditer(r"<tr>\s*<td>([^<]+)</td>\s*<td>", field_notes_text, re.IGNORECASE | re.DOTALL):
                spname = m.group(1).strip()
                species_in_notes.append(spname)
            species_set = set(species_in_notes)
            covered = 0
            total = len(species_set)
            for sp in species_set:
                found = False
                for ln in open_sec.splitlines():
                    if sp in ln and "?" in ln:
                        found = True
                        break
                if found:
                    covered += 1
            if total > 0:
                scores["meeting_notes_open_questions_coverage"] = covered / total

        next_sec = _find_section(meeting_text, "Next steps", sections)
        if next_sec:
            items = _extract_numbered_items(next_sec)
            n = len(items)
            if 3 <= n <= 6:
                scores["meeting_notes_next_steps_count"] = 1.0
            else:
                scores["meeting_notes_next_steps_count"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()