import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple


ORIGINAL_RESEARCH_PLAN = """# Research Plan: Multicultural Legal Systems
Author: Law Student

## Overview
I am researching the practical challenges and benefits of multicultural or plural legal systems, focusing on how customary, religious, and state legal orders interact across jurisdictions.

## Weekly Summary (auto-updated)
<!-- WEEKLY-SUMMARY:START -->
This block is maintained by the weekly summary task. Do not edit manually.
<!-- WEEKLY-SUMMARY:END -->

## Milestones
- Literature review outline by end of January.
- Draft comparative matrix by mid-February.
"""


def _read_text(path: Path) -> Optional[str]:
    try:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        required = {"date", "jurisdiction", "legal_system", "topic", "type", "note", "source_id", "tags"}
        if not required.issubset(set(reader.fieldnames or [])):
            return None
        return rows
    except Exception:
        return None


def _load_jsonl_dicts(path: Path) -> Optional[List[Dict]]:
    try:
        if not path.exists():
            return None
        rows = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    return None
                if not all(k in obj for k in ["jurisdiction", "theme", "quote", "sentiment", "weight"]):
                    return None
                if not isinstance(obj.get("weight"), int):
                    return None
                if obj.get("sentiment") not in ("challenge", "benefit"):
                    return None
                rows.append(obj)
        return rows
    except Exception:
        return None


def _compute_expected_metrics(
    notes_rows: List[Dict[str, str]],
    interview_rows: List[Dict],
) -> Optional[Dict]:
    try:
        dates = [row["date"] for row in notes_rows if isinstance(row.get("date"), str) and row["date"]]
        if not dates:
            return None
        as_of = max(dates)  # YYYY-MM-DD lexicographic max works
        total_notes = len(notes_rows)
        total_interviews = len(interview_rows)

        rn_challenges = sum(1 for r in notes_rows if r.get("type") == "challenge")
        rn_benefits = sum(1 for r in notes_rows if r.get("type") == "benefit")
        iv_challenges = sum(r.get("weight", 0) for r in interview_rows if r.get("sentiment") == "challenge")
        iv_benefits = sum(r.get("weight", 0) for r in interview_rows if r.get("sentiment") == "benefit")
        challenges_count = rn_challenges + iv_challenges
        benefits_count = rn_benefits + iv_benefits

        jurisdictions = set()
        for r in notes_rows:
            jurisdictions.add(r.get("jurisdiction"))
        for r in interview_rows:
            jurisdictions.add(r.get("jurisdiction"))

        counts_by_jurisdiction: Dict[str, Dict[str, int]] = {j: {"challenges": 0, "benefits": 0} for j in jurisdictions}

        for r in notes_rows:
            j = r.get("jurisdiction")
            if j not in counts_by_jurisdiction:
                counts_by_jurisdiction[j] = {"challenges": 0, "benefits": 0}
            if r.get("type") == "challenge":
                counts_by_jurisdiction[j]["challenges"] += 1
            elif r.get("type") == "benefit":
                counts_by_jurisdiction[j]["benefits"] += 1

        for r in interview_rows:
            j = r.get("jurisdiction")
            if j not in counts_by_jurisdiction:
                counts_by_jurisdiction[j] = {"challenges": 0, "benefits": 0}
            w = r.get("weight", 0)
            if r.get("sentiment") == "challenge":
                counts_by_jurisdiction[j]["challenges"] += w
            elif r.get("sentiment") == "benefit":
                counts_by_jurisdiction[j]["benefits"] += w

        theme_counts: Dict[str, int] = {}
        for r in notes_rows:
            t = r.get("topic")
            if isinstance(t, str) and t:
                theme_counts[t] = theme_counts.get(t, 0) + 1
        for r in interview_rows:
            t = r.get("theme")
            w = r.get("weight", 0)
            if isinstance(t, str) and t:
                theme_counts[t] = theme_counts.get(t, 0) + int(w)

        sorted_themes = sorted(theme_counts.items(), key=lambda x: (-x[1], x[0]))
        top3 = [{"theme": t, "count": c} for t, c in sorted_themes[:3]]

        metrics = {
            "as_of": as_of,
            "total_notes": total_notes,
            "total_interviews": total_interviews,
            "challenges_count": challenges_count,
            "benefits_count": benefits_count,
            "counts_by_jurisdiction": counts_by_jurisdiction,
            "top_themes": top3,
        }
        return metrics
    except Exception:
        return None


def _extract_marked_block(content: str, start_marker: str, end_marker: str) -> Optional[Tuple[str, str, str]]:
    try:
        start_idx = content.find(start_marker)
        end_idx = content.find(end_marker)
        if start_idx == -1 or end_idx == -1:
            return None
        start_end = start_idx + len(start_marker)
        if end_idx < start_end:
            return None
        pre = content[:start_end]
        block = content[start_end:end_idx]
        post = content[end_idx:]
        return pre, block, post
    except Exception:
        return None


def _paragraphs(md_text: str) -> List[str]:
    try:
        blocks = re.split(r"\n\s*\n", md_text.strip(), flags=re.MULTILINE)
        paras = [b.strip() for b in blocks if b.strip()]
        return paras
    except Exception:
        return []


def _validate_cron_line(line: str) -> bool:
    try:
        s = line.strip()
        if not s:
            return False
        parts = s.split()
        if len(parts) < 8:
            return False
        if not (parts[0] == "0" and parts[1] == "8" and parts[2] == "*" and parts[3] == "*" and parts[4].upper() == "MON"):
            return False
        if ">>" not in s or "logs/run.log" not in s or "2>&1" not in s:
            return False
        if "scripts/build_weekly_summary.py" not in s:
            return False
        if "/scripts/build_weekly_summary.py" in s:
            return False
        return True
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "script_present": 0.0,
        "outputs_named_by_as_of_date": 0.0,
        "metrics_json_correct": 0.0,
        "summary_has_as_of_date": 0.0,
        "summary_paragraph_count_valid": 0.0,
        "summary_mentions_themes_with_counts": 0.0,
        "summary_includes_quote": 0.0,
        "summary_sources_line_correct": 0.0,
        "summary_mentions_jurisdictions": 0.0,
        "email_greeting_to_supervisor": 0.0,
        "email_top_themes_bulleted": 0.0,
        "email_attachments_links": 0.0,
        "plan_markers_update_only": 0.0,
        "plan_status_block_content": 0.0,
        "cron_line_valid": 0.0,
        "first_run_log_present": 0.0,
    }

    # Check script presence
    script_path = workspace / "scripts" / "build_weekly_summary.py"
    if script_path.exists():
        scores["script_present"] = 1.0

    # Load inputs
    notes_path = workspace / "input" / "reading_notes.csv"
    iv_path = workspace / "input" / "interview_excerpts.jsonl"
    notes_rows = _load_csv_dicts(notes_path)
    iv_rows = _load_jsonl_dicts(iv_path)

    expected_metrics = None
    if notes_rows is not None and iv_rows is not None:
        expected_metrics = _compute_expected_metrics(notes_rows, iv_rows)

    expected_date = None
    if expected_metrics:
        expected_date = expected_metrics["as_of"]

    # Expected output paths
    metrics_file = None
    summary_file = None
    email_file = None
    if expected_date:
        metrics_file = workspace / "output" / f"weekly_metrics_{expected_date}.json"
        summary_file = workspace / "output" / f"weekly_summary_{expected_date}.md"
        email_file = workspace / "output" / f"email_draft_{expected_date}.md"

        if metrics_file.exists() and summary_file.exists() and email_file.exists():
            scores["outputs_named_by_as_of_date"] = 1.0

    # Validate metrics JSON content
    if expected_metrics and metrics_file and metrics_file.exists():
        try:
            actual = json.loads(metrics_file.read_text(encoding="utf-8"))
            ok = True
            required_keys = {
                "as_of",
                "total_notes",
                "total_interviews",
                "challenges_count",
                "benefits_count",
                "counts_by_jurisdiction",
                "top_themes",
            }
            if not required_keys.issubset(set(actual.keys())):
                ok = False
            if actual.get("as_of") != expected_metrics["as_of"]:
                ok = False
            if actual.get("total_notes") != expected_metrics["total_notes"]:
                ok = False
            if actual.get("total_interviews") != expected_metrics["total_interviews"]:
                ok = False
            if actual.get("challenges_count") != expected_metrics["challenges_count"]:
                ok = False
            if actual.get("benefits_count") != expected_metrics["benefits_count"]:
                ok = False
            exp_cbj = expected_metrics["counts_by_jurisdiction"]
            act_cbj = actual.get("counts_by_jurisdiction", {})
            if set(act_cbj.keys()) != set(exp_cbj.keys()):
                ok = False
            else:
                for j in exp_cbj:
                    exp_j = exp_cbj[j]
                    act_j = act_cbj.get(j, {})
                    if not isinstance(act_j, dict):
                        ok = False
                        break
                    if act_j.get("challenges") != exp_j["challenges"] or act_j.get("benefits") != exp_j["benefits"]:
                        ok = False
                        break
            act_tt = actual.get("top_themes", [])
            exp_tt = expected_metrics["top_themes"]
            if not isinstance(act_tt, list):
                ok = False
            else:
                if act_tt != exp_tt:
                    ok = False
            scores["metrics_json_correct"] = 1.0 if ok else 0.0
        except Exception:
            scores["metrics_json_correct"] = 0.0

    # Summary checks
    if summary_file and summary_file.exists() and expected_metrics:
        txt = _read_text(summary_file) or ""
        if expected_metrics["as_of"] in txt:
            scores["summary_has_as_of_date"] = 1.0
        paras = _paragraphs(txt)
        if 2 <= len(paras) <= 4:
            scores["summary_paragraph_count_valid"] = 1.0
        top3 = expected_metrics["top_themes"]
        lines = [ln.strip() for ln in txt.splitlines()]
        theme_ok = True
        for item in top3:
            theme = item["theme"]
            count = item["count"]
            found = False
            for ln in lines:
                if theme in ln and re.search(rf"\b{count}\b", ln):
                    found = True
                    break
            if not found:
                theme_ok = False
                break
        if theme_ok:
            scores["summary_mentions_themes_with_counts"] = 1.0
        quotes = [r.get("quote") for r in (iv_rows or []) if isinstance(r.get("quote"), str)]
        quote_found = False
        for q in quotes:
            if q and q in txt:
                quote_found = True
                break
        if quote_found:
            scores["summary_includes_quote"] = 1.0
        non_empty_lines = [l.strip() for l in lines if l.strip()]
        last_line = non_empty_lines[-1] if non_empty_lines else ""
        if last_line and "Sources considered" in last_line:
            tn = expected_metrics["total_notes"]
            ti = expected_metrics["total_interviews"]
            if re.search(rf"\b{tn}\b", last_line) and re.search(rf"\b{ti}\b", last_line):
                scores["summary_sources_line_correct"] = 1.0
        jurisdictions = set(expected_metrics["counts_by_jurisdiction"].keys())
        mentioned = set()
        for j in jurisdictions:
            if j and j in txt:
                mentioned.add(j)
        if len(mentioned) >= 2:
            scores["summary_mentions_jurisdictions"] = 1.0

    # Email checks
    if email_file and email_file.exists() and expected_metrics:
        etxt = _read_text(email_file) or ""
        elines = [ln.rstrip() for ln in etxt.splitlines()]
        name = None
        sup_path = workspace / "config" / "supervisor.json"
        sup = None
        try:
            if sup_path.exists():
                sup = json.loads(_read_text(sup_path) or "{}")
        except Exception:
            sup = None
        if sup and isinstance(sup, dict):
            name = sup.get("name")
        greeting_ok = False
        if name:
            non_empty = [l for l in elines if l.strip()]
            head = non_empty[:5]
            for l in head:
                if name in l and (re.search(r"\bDear\b", l) or re.search(r"\bHello\b", l) or re.search(r"\bHi\b", l)):
                    greeting_ok = True
                    break
            if not greeting_ok and name in etxt:
                greeting_ok = True
        if greeting_ok:
            scores["email_greeting_to_supervisor"] = 1.0

        bullets = [l.strip() for l in elines if l.strip().startswith(("-", "*"))]
        bullets_ok = True
        for item in expected_metrics["top_themes"]:
            theme = item["theme"]
            count = item["count"]
            found = False
            for b in bullets:
                if theme in b and re.search(rf"\b{count}\b", b):
                    found = True
                    break
            if not found:
                bullets_ok = False
                break
        if bullets_ok:
            scores["email_top_themes_bulleted"] = 1.0

        attachments_ok = False
        if metrics_file and summary_file:
            if ("Attachments" in etxt or "Attachments/Links" in etxt) and (
                str(metrics_file.relative_to(workspace)) in etxt and str(summary_file.relative_to(workspace)) in etxt
            ):
                attachments_ok = True
        if attachments_ok:
            scores["email_attachments_links"] = 1.0

    # Research plan update checks
    plan_path = workspace / "docs" / "research_plan.md"
    plan_txt = _read_text(plan_path) or ""
    start_marker = "<!-- WEEKLY-SUMMARY:START -->"
    end_marker = "<!-- WEEKLY-SUMMARY:END -->"
    current = plan_txt
    orig = ORIGINAL_RESEARCH_PLAN
    extract_current = _extract_marked_block(current, start_marker, end_marker)
    extract_orig = _extract_marked_block(orig, start_marker, end_marker)
    if extract_current and extract_orig:
        pre_cur, block_cur, post_cur = extract_current
        pre_orig, block_orig, post_orig = extract_orig
        if pre_cur == pre_orig and post_cur == post_orig and block_cur != block_orig:
            scores["plan_markers_update_only"] = 1.0
        block = block_cur.strip("\n")
        lines = [ln for ln in block.splitlines() if ln.strip()]
        block_ok = True
        if not (3 <= len(lines) <= 6):
            block_ok = False
        if expected_metrics:
            as_of = expected_metrics["as_of"]
            if as_of not in block:
                block_ok = False
            if summary_file:
                try:
                    rel = str(summary_file.relative_to(workspace))
                except Exception:
                    rel = f"output/weekly_summary_{as_of}.md"
                if rel not in block:
                    block_ok = False
            tn = expected_metrics["total_notes"]
            ti = expected_metrics["total_interviews"]
            cc = expected_metrics["challenges_count"]
            bc = expected_metrics["benefits_count"]
            tokens = re.findall(r"\b\d+\b", block)
            def count_token(val: int) -> int:
                return sum(1 for t in tokens if t == str(val))
            if count_token(tn) < 1 or count_token(ti) < 1 or count_token(cc) < 1 or count_token(bc) < 1:
                block_ok = False
        else:
            block_ok = False
        if block_ok:
            scores["plan_status_block_content"] = 1.0

    # Cron line check
    cron_path = workspace / "schedule" / "cron_preview.txt"
    cron_txt = _read_text(cron_path)
    if cron_txt is not None:
        lines = [ln for ln in cron_txt.splitlines() if ln.strip()]
        if len(lines) == 1 and _validate_cron_line(lines[0]):
            scores["cron_line_valid"] = 1.0

    # First run log presence
    first_run_log = workspace / "logs" / "first_run.log"
    fr_txt = _read_text(first_run_log)
    if fr_txt is not None and fr_txt.strip():
        scores["first_run_log_present"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()