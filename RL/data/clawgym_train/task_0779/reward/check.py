import json
import csv
import sys
import re
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Any, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    results = []
    for line in lines:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                results.append(obj)
            else:
                return None
        except Exception:
            return None
    return results


def _load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _parse_bool_str(s: str) -> Optional[bool]:
    if s is None:
        return None
    v = str(s).strip().lower()
    if v in ("true", "t", "1", "yes", "y"):
        return True
    if v in ("false", "f", "0", "no", "n"):
        return False
    return None


class ScriptTagParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: List[Dict[str, Any]] = []
        self._in_script = False
        self._current_attrs: Dict[str, str] = {}
        self._current_code_parts: List[str] = []
        self._index_counter = 0
        self._inline_counter = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "script":
            self._in_script = True
            self._index_counter += 1
            attrs_dict: Dict[str, str] = {}
            for k, v in attrs:
                if k is not None:
                    attrs_dict[k.lower()] = "" if v is None else v
            self._current_attrs = attrs_dict
            self._current_code_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_script:
            code = "".join(self._current_code_parts)
            src_val = self._current_attrs.get("src")
            if not src_val:
                self._inline_counter += 1
                src_val = f"inline:{self._inline_counter}"
            data_cfasync_val = self._current_attrs.get("data-cfasync")
            opted_out = isinstance(data_cfasync_val, str) and data_cfasync_val.strip().lower() == "false"
            deferred_by_rl = not opted_out
            uses_document_write = False
            mentions_jquery = False
            if src_val.startswith("inline:"):
                if "document.write" in code:
                    uses_document_write = True
                if "jQuery" in code or "$(" in code:
                    mentions_jquery = True
            script_info = {
                "index": self._index_counter,
                "src": src_val,
                "attrs": dict(self._current_attrs),
                "deferred_by_rocketloader": deferred_by_rl,
                "uses_document_write": uses_document_write,
                "mentions_jquery": mentions_jquery,
            }
            self.scripts.append(script_info)
            self._in_script = False
            self._current_attrs = {}
            self._current_code_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._current_code_parts.append(data)


def _extract_scripts_from_html(html_text: str) -> List[Dict[str, Any]]:
    parser = ScriptTagParser()
    parser.feed(html_text)
    return parser.scripts


def _parse_doc_mitigations(doc_text: str) -> List[str]:
    lines = doc_text.splitlines()
    mitigations: List[str] = []
    in_section = False
    for line in lines:
        if re.match(r"^\s*#\s*How to Opt Out/Mitigations\s*$", line):
            in_section = True
            continue
        if in_section:
            if re.match(r"^\s*#", line):
                break
            if line.strip().startswith("- "):
                mitigations.append(line.strip()[2:].strip())
    return mitigations


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "analyze_script_exists": 0.0,
        "scripts_csv_exists": 0.0,
        "scripts_csv_structure": 0.0,
        "scripts_csv_rowcount": 0.0,
        "scripts_csv_deferred_logic": 0.0,
        "scripts_csv_error_counts": 0.0,
        "scripts_csv_mentions_jquery": 0.0,
        "scripts_csv_document_write": 0.0,
        "scripts_csv_roles": 0.0,
        "top_issues_exists": 0.0,
        "top_issues_structure": 0.0,
        "top_issues_ranking": 0.0,
        "rocketloader_json_exists": 0.0,
        "rocketloader_json_counts": 0.0,
        "rocketloader_json_top_errors_valid": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_title": 0.0,
        "meeting_notes_exec_summary": 0.0,
        "meeting_notes_findings_cover_top": 0.0,
        "meeting_notes_mitigation_quotes": 0.0,
        "meeting_notes_action_items": 0.0,
        "meeting_notes_rerun_command": 0.0,
    }

    analyze_script = workspace / "scripts" / "analyze.py"
    if analyze_script.exists():
        scores["analyze_script_exists"] = 1.0

    input_html = workspace / "input" / "page_snapshot.html"
    input_errors = workspace / "input" / "console_errors.jsonl"
    input_catalog = workspace / "input" / "script_catalog.csv"
    input_doc = workspace / "input" / "rocketloader_doc.md"

    out_dir = workspace / "output"
    scripts_csv = out_dir / "scripts_with_errors.csv"
    top_csv = out_dir / "top_issues.csv"
    impact_json = out_dir / "rocketloader_impact.json"
    notes_md = out_dir / "meeting_notes.md"

    html_text = _read_text(input_html) or ""
    errors_list = _load_jsonl(input_errors) or []
    catalog_rows = _load_csv(input_catalog) or []
    doc_text = _read_text(input_doc) or ""

    expected_scripts: List[Dict[str, Any]] = []
    if html_text:
        expected_scripts = _extract_scripts_from_html(html_text)

    error_counts: Dict[str, int] = {}
    message_counts: Dict[str, int] = {}
    if errors_list:
        for evt in errors_list:
            su = evt.get("script_url")
            msg = evt.get("message")
            if isinstance(su, str):
                error_counts[su] = error_counts.get(su, 0) + 1
            if isinstance(msg, str):
                message_counts[msg] = message_counts.get(msg, 0) + 1

    role_map: Dict[str, str] = {}
    for row in catalog_rows:
        src = (row.get("src") or "").strip()
        role = (row.get("role") or "").strip()
        if src and role:
            role_map[src] = role

    expected_by_src: Dict[str, Dict[str, Any]] = {}
    for s in expected_scripts:
        src = s["src"]
        role = role_map.get(src, "other")
        expected_by_src[src] = {
            "index": s["index"],
            "src": src,
            "role": role,
            "deferred_by_rocketloader": bool(s["deferred_by_rocketloader"]),
            "uses_document_write": bool(s["uses_document_write"]),
            "mentions_jquery": bool(s["mentions_jquery"]),
            "error_count": int(error_counts.get(src, 0)),
        }

    def sort_key(item: Dict[str, Any]) -> Tuple[int, int]:
        severity_order = {
            "payment": 6,
            "critical-library": 5,
            "inline": 4,
            "analytics": 3,
            "chat": 2,
            "other": 1,
        }
        role_priority = severity_order.get(item["role"], 0)
        return (item["error_count"], role_priority)

    expected_sorted = sorted(expected_by_src.values(), key=sort_key, reverse=True)
    expected_top5 = expected_sorted[:5]

    if scripts_csv.exists():
        scores["scripts_csv_exists"] = 1.0
        rows = _load_csv(scripts_csv)
        if rows is not None and len(rows) >= 1:
            headers = list(rows[0].keys())
            required_cols = ["index", "src", "role", "deferred_by_rocketloader", "uses_document_write", "mentions_jquery", "error_count"]
            structure_ok = all(col in headers for col in required_cols)
            if structure_ok:
                scores["scripts_csv_structure"] = 1.0
            if expected_scripts:
                if len(rows) == len(expected_scripts):
                    scores["scripts_csv_rowcount"] = 1.0
            idx_to_row: Dict[int, Dict[str, str]] = {}
            try:
                for r in rows:
                    idx_val = int(str(r.get("index", "")).strip())
                    idx_to_row[idx_val] = r
            except Exception:
                idx_to_row = {}
            if expected_scripts and idx_to_row:
                deferred_ok = True
                errors_ok = True
                mentions_ok = True
                docwrite_ok = True
                roles_ok = True
                for exp in expected_by_src.values():
                    idx = exp["index"]
                    row = idx_to_row.get(idx)
                    if not row:
                        deferred_ok = False
                        errors_ok = False
                        mentions_ok = False
                        docwrite_ok = False
                        roles_ok = False
                        break
                    if (row.get("src") or "").strip() != exp["src"]:
                        deferred_ok = False
                        errors_ok = False
                        mentions_ok = False
                        docwrite_ok = False
                        roles_ok = False
                        break
                    rb = _parse_bool_str(row.get("deferred_by_rocketloader", ""))
                    if rb is None or rb != exp["deferred_by_rocketloader"]:
                        deferred_ok = False
                    udw = _parse_bool_str(row.get("uses_document_write", ""))
                    if udw is None or udw != exp["uses_document_write"]:
                        docwrite_ok = False
                    mj = _parse_bool_str(row.get("mentions_jquery", ""))
                    if mj is None or mj != exp["mentions_jquery"]:
                        mentions_ok = False
                    try:
                        ec = int(str(row.get("error_count", "")).strip())
                    except Exception:
                        ec = None  # type: ignore
                    if ec is None or ec != exp["error_count"]:
                        errors_ok = False
                    role_val = (row.get("role") or "").strip()
                    if role_val != exp["role"]:
                        roles_ok = False
                if deferred_ok:
                    scores["scripts_csv_deferred_logic"] = 1.0
                if errors_ok:
                    scores["scripts_csv_error_counts"] = 1.0
                if mentions_ok:
                    scores["scripts_csv_mentions_jquery"] = 1.0
                if docwrite_ok:
                    scores["scripts_csv_document_write"] = 1.0
                if roles_ok:
                    scores["scripts_csv_roles"] = 1.0

    if top_csv.exists():
        scores["top_issues_exists"] = 1.0
        rows = _load_csv(top_csv)
        if rows is not None and len(rows) >= 1:
            headers = list(rows[0].keys())
            required_cols = ["index", "src", "role", "deferred_by_rocketloader", "uses_document_write", "mentions_jquery", "error_count", "rank"]
            if all(col in headers for col in required_cols):
                scores["top_issues_structure"] = 1.0
            if expected_top5 and len(rows) >= len(expected_top5):
                ranking_ok = True
                try:
                    ranks = [int(str(r.get("rank", "")).strip()) for r in rows[:len(expected_top5)]]
                except Exception:
                    ranks = []
                if ranks != list(range(1, len(expected_top5) + 1)):
                    ranking_ok = False
                for i, exp in enumerate(expected_top5):
                    if i >= len(rows):
                        ranking_ok = False
                        break
                    r = rows[i]
                    src_ok = (r.get("src") or "").strip() == exp["src"]
                    role_ok = (r.get("role") or "").strip() == exp["role"]
                    try:
                        ec = int(str(r.get("error_count", "")).strip())
                    except Exception:
                        ec = None  # type: ignore
                    ec_ok = (ec == exp["error_count"])
                    if not (src_ok and role_ok and ec_ok):
                        ranking_ok = False
                        break
                if ranking_ok:
                    scores["top_issues_ranking"] = 1.0

    if impact_json.exists():
        scores["rocketloader_json_exists"] = 1.0
        data = _load_json(impact_json)
        if isinstance(data, dict) and expected_scripts is not None:
            total_scripts_ok = isinstance(data.get("total_scripts"), int) and data.get("total_scripts") == len(expected_scripts)
            count_deferred_val = data.get("count_deferred")
            count_opted_out_val = data.get("count_opted_out")
            if isinstance(count_deferred_val, int) and isinstance(count_opted_out_val, int):
                exp_count_deferred = sum(1 for s in expected_scripts if s["deferred_by_rocketloader"])
                exp_count_opted_out = len(expected_scripts) - exp_count_deferred
                counts_ok = (count_deferred_val == exp_count_deferred and count_opted_out_val == exp_count_opted_out)
            else:
                counts_ok = False
            total_errors_ok = isinstance(data.get("total_errors"), int) and data.get("total_errors") == sum(error_counts.values())
            if total_scripts_ok and counts_ok and total_errors_ok:
                scores["rocketloader_json_counts"] = 1.0
            tem = data.get("top_error_messages")
            valid_tem = False
            if isinstance(tem, list) and len(tem) <= 3:
                valid_tem = True
                for item in tem:
                    if not isinstance(item, dict):
                        valid_tem = False
                        break
                    msg = item.get("message")
                    cnt = item.get("count")
                    if not isinstance(msg, str) or not isinstance(cnt, int):
                        valid_tem = False
                        break
                    actual_cnt = message_counts.get(msg)
                    if actual_cnt is None or actual_cnt != cnt:
                        valid_tem = False
                        break
            if valid_tem:
                scores["rocketloader_json_top_errors_valid"] = 1.0

    if notes_md.exists():
        scores["meeting_notes_exists"] = 1.0
        notes_text = _read_text(notes_md) or ""
        title_ok = False
        for line in notes_text.splitlines():
            if line.strip() == "":
                continue
            if line.strip() == "# Rocket Loader Triage Notes":
                title_ok = True
            break
        if title_ok:
            scores["meeting_notes_title"] = 1.0

        lines = notes_text.splitlines()
        title_idx = None
        for i, line in enumerate(lines):
            if line.strip() == "# Rocket Loader Triage Notes":
                title_idx = i
                break
        exec_summary_ok = False
        if title_idx is not None:
            para_lines: List[str] = []
            for j in range(title_idx + 1, len(lines)):
                if lines[j].strip() == "":
                    if para_lines:
                        break
                    else:
                        continue
                if para_lines and lines[j].strip().startswith(("#", "##", "###")):
                    break
                para_lines.append(lines[j].strip())
            para_text = " ".join(para_lines).strip()
            if para_text:
                sent_parts = re.split(r'(?<=[\.\!\?])\s+', para_text)
                sent_parts = [s for s in sent_parts if s.strip()]
                if 3 <= len(sent_parts) <= 5 and ("Incompatibilities" in para_text) and ("Rocket Loader" in para_text):
                    exec_summary_ok = True
        if exec_summary_ok:
            scores["meeting_notes_exec_summary"] = 1.0

        findings_ok = False
        if top_csv.exists():
            top_rows = _load_csv(top_csv) or []
            if top_rows:
                bullets = [l for l in lines if l.strip().startswith(("-", "*"))]
                all_present = True
                for tr in top_rows[:len(expected_top5)]:
                    src = (tr.get("src") or "").strip()
                    role = (tr.get("role") or "").strip()
                    try:
                        ec = int(str(tr.get("error_count", "")).strip())
                    except Exception:
                        ec = None
                    match_found = False
                    for b in bullets:
                        if src in b and role in b and (str(ec) if ec is not None else "") in b:
                            match_found = True
                            break
                    if not match_found:
                        all_present = False
                        break
                findings_ok = all_present
        if findings_ok:
            scores["meeting_notes_findings_cover_top"] = 1.0

        mitigations = _parse_doc_mitigations(doc_text) if doc_text else []
        mit_count = 0
        for mit in mitigations:
            if mit and mit in notes_text:
                mit_count += 1
        if mit_count >= 2:
            scores["meeting_notes_mitigation_quotes"] = 1.0

        ai_lines = [l for l in lines if l.strip().startswith(("-", "*"))]
        count_ai = 0
        for l in ai_lines:
            low = l.lower()
            if ("web-dev" in low or "ops" in low) and ("to do" in low):
                count_ai += 1
        if count_ai >= 4:
            scores["meeting_notes_action_items"] = 1.0

        cmd_exact = "python3 scripts/analyze.py --html input/page_snapshot.html --errors input/console_errors.jsonl --catalog input/script_catalog.csv --doc input/rocketloader_doc.md --outdir output"
        if cmd_exact in notes_text:
            scores["meeting_notes_rerun_command"] = 1.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()