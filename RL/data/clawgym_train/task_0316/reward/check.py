import json
import csv
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any


def _safe_load_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        if not path.exists():
            return None, "missing"
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None, "not_dict"
        return data, None
    except Exception as e:
        return None, f"error:{e}"


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        if not path.exists():
            return None, "missing"
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, f"error:{e}"


def _safe_parse_csv(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    try:
        if not path.exists():
            return None, "missing"
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        return rows, None
    except Exception as e:
        return None, f"error:{e}"


def _compute_expected_validation(workspace: Path, catalog_csv: Path) -> Tuple[Optional[dict], Optional[str]]:
    rows, err = _safe_parse_csv(catalog_csv)
    if rows is None:
        return None, err or "csv_parse_failed"

    details = []
    ok = 0
    mismatched = 0
    missing = 0

    for row in rows:
        fid = (row.get("id") or "").strip()
        fpath = (row.get("file_path") or "").strip()
        exp_raw = (row.get("expected_size") or "").strip()
        try:
            expected = int(exp_raw)
        except Exception:
            expected = None

        fp = Path(fpath)
        if not fp.is_absolute():
            fp = workspace / fpath

        if not fp.exists():
            details.append({
                "id": fid,
                "file_path": fpath,
                "expected_size": expected,
                "actual_size": None,
                "status": "missing",
            })
            missing += 1
            continue

        try:
            data = fp.read_bytes()
        except Exception:
            details.append({
                "id": fid,
                "file_path": fpath,
                "expected_size": expected,
                "actual_size": None,
                "status": "missing",
            })
            missing += 1
            continue

        actual = len(data)
        status = "ok"
        if expected is None:
            status = "ok"
        elif actual != expected:
            status = "mismatch"

        if status == "ok":
            ok += 1
        elif status == "mismatch":
            mismatched += 1

        details.append({
            "id": fid,
            "file_path": fpath,
            "expected_size": expected,
            "actual_size": actual,
            "status": status,
        })

    res = {
        "total_items": len(rows),
        "ok": ok,
        "mismatched": mismatched,
        "missing": missing,
        "details": details,
    }
    return res, None


def _extract_section(lines: List[str], header: str) -> Tuple[int, int]:
    """
    Return the start (exclusive) and end (exclusive) indices of the section with the given header line.
    The section ends at the next section indicator among: 'Observations', 'Next steps', any top-level header starting with '# ', or end of file.
    """
    start = -1
    end = len(lines)
    for i, line in enumerate(lines):
        if line.strip() == header:
            start = i + 1
            break
    if start == -1:
        return -1, -1
    for j in range(start, len(lines)):
        t = lines[j].strip()
        if t in ("Observations", "Next steps") or t.startswith("# "):
            end = j
            break
    return start, end


def _parse_mismatch_bullets(section_lines: List[str]) -> List[str]:
    bullets = []
    for line in section_lines:
        s = line.strip()
        if s.startswith("- "):
            bullets.append(s)
        elif s == "":
            continue
    return bullets


def _check_weekly_status_totals(lines: List[str], json_data: dict) -> float:
    # Ensure placeholders have been removed
    if any("{{TOTAL}}" in l or "{{OK}}" in l or "{{MISMATCH}}" in l or "{{MISSING}}" in l for l in lines):
        return 0.0

    totals = {
        "total_items": json_data.get("total_items"),
        "ok": json_data.get("ok"),
        "mismatched": json_data.get("mismatched"),
        "missing": json_data.get("missing"),
    }

    found = {
        "total_items": False,
        "ok": False,
        "mismatched": False,
        "missing": False,
    }

    pat_total = re.compile(r"^-+\s*Total items checked:\s*(\d+)\s*$")
    pat_ok = re.compile(r"^-+\s*OK:\s*(\d+)\s*$")
    pat_mis = re.compile(r"^-+\s*Mismatched:\s*(\d+)\s*$")
    pat_miss = re.compile(r"^-+\s*Missing files:\s*(\d+)\s*$")

    for l in lines:
        stripped = l.strip()
        m = pat_total.match(stripped)
        if m:
            if int(m.group(1)) == totals["total_items"]:
                found["total_items"] = True
            continue
        m = pat_ok.match(stripped)
        if m:
            if int(m.group(1)) == totals["ok"]:
                found["ok"] = True
            continue
        m = pat_mis.match(stripped)
        if m:
            if int(m.group(1)) == totals["mismatched"]:
                found["mismatched"] = True
            continue
        m = pat_miss.match(stripped)
        if m:
            if int(m.group(1)) == totals["missing"]:
                found["missing"] = True
            continue

    return 1.0 if all(found.values()) else 0.0


def _check_weekly_status_mismatch_list(lines: List[str], json_data: dict) -> float:
    start, end = _extract_section(lines, "Mismatched items")
    if start == -1:
        return 0.0
    section = lines[start:end]
    bullets = _parse_mismatch_bullets(section)

    details = json_data.get("details")
    if not isinstance(details, list):
        return 0.0
    expected_bullets = []
    for d in details:
        if not isinstance(d, dict):
            return 0.0
        if d.get("status") == "mismatch":
            fid = d.get("id")
            exp = d.get("expected_size")
            act = d.get("actual_size")
            expected_bullets.append(f"- {fid} (expected {exp} bytes, actual {act} bytes)")

    if len(expected_bullets) == 0:
        return 1.0 if len(bullets) == 1 and bullets[0] == "- None" else 0.0
    else:
        return 1.0 if set(bullets) == set(expected_bullets) and len(bullets) == len(expected_bullets) else 0.0


def _check_weekly_status_observation(lines: List[str], json_data: dict) -> float:
    if any(l.strip().startswith("TODO:") for l in lines):
        return 0.0

    start, end = _extract_section(lines, "Observations")
    if start == -1:
        return 0.0
    section = [l.rstrip("\n") for l in lines[start:end]]
    obs_lines = [l for l in section if l.strip().startswith("Observation:")]
    if len(obs_lines) != 1:
        return 0.0
    obs = obs_lines[0].strip()

    mismatches = [d.get("id") for d in (json_data.get("details") or []) if isinstance(d, dict) and d.get("status") == "mismatch"]

    lower_obs = obs.lower()
    if len(mismatches) == 0:
        if "all files matched" in lower_obs or "no mismatches" in lower_obs:
            return 1.0
        else:
            return 0.0
    else:
        if "all files matched" in lower_obs:
            return 0.0
        ok_ids = all((isinstance(fid, str) and fid in obs) for fid in mismatches)
        return 1.0 if ok_ids else 0.0


def _check_weekly_status_structure_preserved(lines: List[str]) -> float:
    title_ok = any(l.strip() == "# Weekly System Status — Digital Archive Ingest" for l in lines)
    next_steps_idx = -1
    for i, l in enumerate(lines):
        if l.strip() == "Next steps":
            next_steps_idx = i
            break
    if not title_ok or next_steps_idx == -1:
        return 0.0
    # Scan bullets under Next steps until next header or EOF
    following = [l.strip() for l in lines[next_steps_idx + 1:]]
    bullets = [l for l in following if l.startswith("- ")]
    expected_bullets = {
        "- Re-validate once mismatches are corrected.",
        "- Document any remediation in the lab notebook.",
    }
    if expected_bullets.issubset(set(bullets)):
        return 1.0
    return 0.0


def _check_validation_json_structure(data: dict) -> float:
    required_top = {"total_items", "ok", "mismatched", "missing", "details"}
    if not all(k in data for k in required_top):
        return 0.0
    if not isinstance(data.get("total_items"), int):
        return 0.0
    if not isinstance(data.get("ok"), int):
        return 0.0
    if not isinstance(data.get("mismatched"), int):
        return 0.0
    if not isinstance(data.get("missing"), int):
        return 0.0
    details = data.get("details")
    if not isinstance(details, list):
        return 0.0
    for d in details:
        if not isinstance(d, dict):
            return 0.0
        for key in ["id", "file_path", "status"]:
            if key not in d:
                return 0.0
        if d.get("expected_size") is not None and not isinstance(d.get("expected_size"), int):
            return 0.0
        if d.get("actual_size") is not None and not isinstance(d.get("actual_size"), int):
            return 0.0
        if d.get("status") not in ("ok", "mismatch", "missing"):
            return 0.0
    return 1.0


def _check_validation_json_correctness(workspace: Path, json_data: dict) -> float:
    expected, err = _compute_expected_validation(workspace, workspace / "input" / "catalog.csv")
    if expected is None:
        return 0.0
    try:
        if json_data.get("total_items") != expected.get("total_items"):
            return 0.0
        if json_data.get("ok") != expected.get("ok"):
            return 0.0
        if json_data.get("mismatched") != expected.get("mismatched"):
            return 0.0
        if json_data.get("missing") != expected.get("missing"):
            return 0.0
        jd = json_data.get("details")
        ed = expected.get("details")
        if not isinstance(jd, list) or not isinstance(ed, list):
            return 0.0
        if len(jd) != len(ed):
            return 0.0
        for jrow, erow in zip(jd, ed):
            if (jrow.get("id") != erow.get("id") or
                jrow.get("file_path") != erow.get("file_path") or
                jrow.get("expected_size") != erow.get("expected_size") or
                jrow.get("actual_size") != erow.get("actual_size") or
                jrow.get("status") != erow.get("status")):
                return 0.0
        return 1.0
    except Exception:
        return 0.0


def _check_system_status_summary(path: Path, json_data: dict) -> Tuple[float, float]:
    text, err = _safe_read_text(path)
    if text is None:
        return 0.0, 0.0
    lines = [l.strip() for l in text.splitlines() if l.strip() != ""]
    if len(lines) != 4:
        return 0.0, 0.0
    values = {}
    for l in lines:
        m = re.match(r"^(Total items|OK|Mismatched|Missing):\s+(\d+)$", l)
        if not m:
            return 0.0, 0.0
        key = m.group(1)
        val = int(m.group(2))
        if key in values:
            return 0.0, 0.0
        values[key] = val
    keys_required = {"Total items", "OK", "Mismatched", "Missing"}
    if set(values.keys()) != keys_required:
        return 0.0, 0.0
    fmt_score = 1.0
    expected_map = {
        "Total items": json_data.get("total_items"),
        "OK": json_data.get("ok"),
        "Mismatched": json_data.get("mismatched"),
        "Missing": json_data.get("missing"),
    }
    values_ok = 1.0 if all(values[k] == expected_map[k] for k in keys_required) else 0.0
    return fmt_score, values_ok


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "validation_results_json_exists": 0.0,
        "validation_results_json_structure": 0.0,
        "validation_results_json_correctness": 0.0,
        "weekly_status_totals_updated": 0.0,
        "weekly_status_mismatch_list_correct": 0.0,
        "weekly_status_observation_sentence": 0.0,
        "weekly_status_structure_preserved": 0.0,
        "system_status_summary_exists_and_format": 0.0,
        "system_status_summary_values_match_json": 0.0,
    }

    val_json_path = workspace / "output" / "validation_results.json"
    val_json, _ = _safe_load_json(val_json_path)
    if val_json is not None:
        scores["validation_results_json_exists"] = 1.0
        scores["validation_results_json_structure"] = _check_validation_json_structure(val_json)
        scores["validation_results_json_correctness"] = _check_validation_json_correctness(workspace, val_json)

    weekly_path = workspace / "docs" / "weekly_status_draft.md"
    weekly_text, _ = _safe_read_text(weekly_path)
    if weekly_text is not None and val_json is not None:
        lines = weekly_text.splitlines()
        scores["weekly_status_totals_updated"] = _check_weekly_status_totals(lines, val_json)
        scores["weekly_status_mismatch_list_correct"] = _check_weekly_status_mismatch_list(lines, val_json)
        scores["weekly_status_observation_sentence"] = _check_weekly_status_observation(lines, val_json)
        scores["weekly_status_structure_preserved"] = _check_weekly_status_structure_preserved(lines)

    if val_json is not None:
        summary_path = workspace / "output" / "system_status_summary.md"
        fmt_score, values_score = _check_system_status_summary(summary_path, val_json)
        scores["system_status_summary_exists_and_format"] = fmt_score
        scores["system_status_summary_values_match_json"] = values_score

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()