import json
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from collections import OrderedDict


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        txt = _read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        txt = _read_text(path)
        if txt is None:
            return None
        lines = [ln for ln in txt.splitlines() if ln.strip() != ""]
        items: List[dict] = []
        for ln in lines:
            try:
                obj = json.loads(ln)
            except Exception:
                return None
            if not isinstance(obj, dict):
                return None
            items.append(obj)
        return items
    except Exception:
        return None


def _parse_date(date_str: str) -> Optional[datetime.date]:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None


def _compute_expected_for_date(tips: List[dict], date_str: str) -> Optional[dict]:
    run_date = _parse_date(date_str)
    if run_date is None:
        return None
    required_fields = [
        "id", "region", "terrain", "risk_score",
        "embargo_until", "window_start", "window_end", "priority_flag"
    ]
    tips_processed = len(tips)
    eligible: List[dict] = []
    exclusions = {"embargo": [], "outside_window": []}
    tip_map: Dict[str, dict] = {}
    for t in tips:
        if not all(k in t for k in required_fields):
            return None
        try:
            tip_id = str(t["id"])
            region = str(t["region"])
            terrain = str(t["terrain"])
            risk_score = int(t["risk_score"])
            priority_flag = bool(t["priority_flag"])
            emb = _parse_date(str(t["embargo_until"]))
            win_s = _parse_date(str(t["window_start"]))
            win_e = _parse_date(str(t["window_end"]))
            if emb is None or win_s is None or win_e is None:
                return None
        except Exception:
            return None

        is_eligible = True
        if emb > run_date:
            exclusions["embargo"].append(tip_id)
            is_eligible = False
        elif not (win_s <= run_date <= win_e):
            exclusions["outside_window"].append(tip_id)
            is_eligible = False

        thrill = risk_score + (2 if priority_flag else 0)
        tip_map[tip_id] = {
            "id": tip_id,
            "region": region,
            "terrain": terrain,
            "risk_score": risk_score,
            "priority_flag": priority_flag,
            "thrill_score": thrill,
            "window_end": win_e,
        }
        if is_eligible:
            eligible.append(tip_map[tip_id])

    eligible_sorted = sorted(
        eligible,
        key=lambda x: (-x["thrill_score"], x["window_end"], x["id"])
    )
    selected_top3 = [e["id"] for e in eligible_sorted[:3]]
    return {
        "run_date": date_str,
        "processed_count": tips_processed,
        "eligible_count": len(eligible_sorted),
        "excluded_count": tips_processed - len(eligible_sorted),
        "exclusions": exclusions,
        "eligible_sorted": eligible_sorted,
        "selected_ids": selected_top3,
        "tip_map": tip_map,
    }


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _find_first_line_containing(text: str, token: str) -> Optional[str]:
    for ln in text.splitlines():
        if token in ln:
            return ln
    return None


def _find_positions_in_text(text: str, tokens: List[str]) -> Optional[List[int]]:
    positions = []
    for tok in tokens:
        idx = text.find(tok)
        if idx == -1:
            return None
        positions.append(idx)
    return positions


def _extract_output_drafts(md_text: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    current_num: Optional[str] = None
    current_lines: List[str] = []
    for line in md_text.splitlines():
        m = re.match(r"^\s*#\s*Draft\s*(\d+)", line, flags=re.IGNORECASE)
        if m:
            if current_num is not None:
                sections[current_num] = "\n".join(current_lines).strip()
            current_num = m.group(1)
            current_lines = []
        else:
            if current_num is not None:
                current_lines.append(line)
    if current_num is not None:
        sections[current_num] = "\n".join(current_lines).strip()
    return sections


def _collect_preserve_tokens(md_text: str) -> Dict[str, List[str]]:
    tokens_per_draft: Dict[str, List[str]] = {}
    sections = _extract_output_drafts(md_text)
    for num, content in sections.items():
        tokens: List[str] = []
        tokens += re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", content)
        tokens += re.findall(r"@[A-Za-z0-9_\.]+", content)
        tokens += re.findall(r"https?://\S+", content)
        tokens_per_draft[num] = tokens
    return tokens_per_draft


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "daily_plan_json_present": 0.0,
        "daily_plan_run_date_correct": 0.0,
        "daily_plan_selected_ids_correct": 0.0,
        "daily_plan_items_order_and_count": 0.0,
        "daily_plan_items_fields_and_scores_correct": 0.0,
        "daily_plan_pitches_comply": 0.0,
        "status_report_present": 0.0,
        "status_totals_correct": 0.0,
        "status_exclusion_breakdown_correct": 0.0,
        "status_shortlist_order_and_scores": 0.0,
        "status_next_steps_bullets_present": 0.0,
        "outreach_polished_present": 0.0,
        "outreach_drafts_count_and_structure": 0.0,
        "outreach_preserved_tokens": 0.0,
        "outreach_each_draft_under_100_words": 0.0,
        "cron_example_present_single_line": 0.0,
        "cron_has_0700_and_date_flag_and_output": 0.0,
        "helper_script_present": 0.0,
    }

    tips_path = workspace / "input" / "tips.jsonl"
    tips = _load_jsonl(tips_path)
    expected = None
    if tips is not None:
        expected = _compute_expected_for_date(tips, "2026-04-16")

    # Daily plan JSON checks
    daily_plan_path = workspace / "output" / "daily_plan_2026-04-16.json"
    daily_plan = _load_json(daily_plan_path)
    if daily_plan is not None and isinstance(daily_plan, dict):
        scores["daily_plan_json_present"] = 1.0
        if daily_plan.get("run_date") == "2026-04-16":
            scores["daily_plan_run_date_correct"] = 1.0
        if expected is not None:
            exp_selected = expected["selected_ids"]
            if isinstance(daily_plan.get("selected_ids"), list) and [str(x) for x in daily_plan.get("selected_ids")] == exp_selected:
                scores["daily_plan_selected_ids_correct"] = 1.0
        items = daily_plan.get("items")
        if isinstance(items, list):
            if expected is not None:
                if len(items) == min(3, len(expected["eligible_sorted"])):
                    ids_in_items = [str(it.get("id")) for it in items]
                    if ids_in_items == expected["selected_ids"][:len(items)]:
                        scores["daily_plan_items_order_and_count"] = 1.0
            if expected is not None and isinstance(items, list) and len(items) >= 1:
                fields_ok = True
                for it in items:
                    if not isinstance(it, dict):
                        fields_ok = False
                        break
                    if not all(k in it for k in ("id", "region", "terrain", "thrill_score", "pitch")):
                        fields_ok = False
                        break
                    tip_id = str(it["id"])
                    exp = expected["tip_map"].get(tip_id)
                    if exp is None:
                        fields_ok = False
                        break
                    if str(it.get("region")) != exp["region"]:
                        fields_ok = False
                        break
                    if str(it.get("terrain")) != exp["terrain"]:
                        fields_ok = False
                        break
                    try:
                        if int(it.get("thrill_score")) != int(exp["thrill_score"]):
                            fields_ok = False
                            break
                    except Exception:
                        fields_ok = False
                        break
                if fields_ok:
                    scores["daily_plan_items_fields_and_scores_correct"] = 1.0
                pitches_ok = True
                for it in items:
                    pitch = str(it.get("pitch", ""))
                    if pitch.strip() == "":
                        pitches_ok = False
                        break
                    if _word_count(pitch) > 50:
                        pitches_ok = False
                        break
                    region = str(it.get("region", ""))
                    terrain = str(it.get("terrain", ""))
                    p_low = pitch.lower()
                    if region.strip() == "" or terrain.strip() == "":
                        pitches_ok = False
                        break
                    if region.lower() not in p_low or terrain.lower() not in p_low:
                        pitches_ok = False
                        break
                if pitches_ok:
                    scores["daily_plan_pitches_comply"] = 1.0

    # Status report checks
    status_path = workspace / "output" / "status_report_2026-04-16.md"
    status_text = _read_text(status_path)
    if status_text is not None:
        scores["status_report_present"] = 1.0
        if expected is not None:
            def _find_count(keyword: str) -> Optional[int]:
                m = re.search(rf"{keyword}\D+(\d+)", status_text, flags=re.IGNORECASE)
                if m:
                    try:
                        return int(m.group(1))
                    except Exception:
                        return None
                return None

            processed_ok = (_find_count("processed") == expected["processed_count"])
            eligible_ok = (_find_count("eligible") == expected["eligible_count"])
            excluded_ok = (_find_count("excluded") == expected["excluded_count"])
            if processed_ok and eligible_ok and excluded_ok:
                scores["status_totals_correct"] = 1.0

            excl_ok = True
            emb_ids = expected["exclusions"].get("embargo", [])
            out_ids = expected["exclusions"].get("outside_window", [])
            for tid in emb_ids:
                found_line = False
                for ln in status_text.splitlines():
                    if re.search(r"embargo", ln, flags=re.IGNORECASE) and tid in ln:
                        found_line = True
                        break
                if not found_line:
                    excl_ok = False
                    break
            if excl_ok:
                for tid in out_ids:
                    found_line = False
                    for ln in status_text.splitlines():
                        if re.search(r"outside[_\s-]*window", ln, flags=re.IGNORECASE) and tid in ln:
                            found_line = True
                            break
                    if not found_line:
                        excl_ok = False
                        break
            if excl_ok:
                scores["status_exclusion_breakdown_correct"] = 1.0

            ids_order = expected["selected_ids"]
            order_positions = _find_positions_in_text(status_text, ids_order)
            if order_positions is not None and order_positions == sorted(order_positions):
                lines_map: Dict[str, Optional[str]] = {}
                for tid in ids_order:
                    ln = _find_first_line_containing(status_text, tid)
                    lines_map[tid] = ln
                scores_present = True
                for e in expected["eligible_sorted"][:3]:
                    tid = e["id"]
                    ln = lines_map.get(tid)
                    if ln is None:
                        scores_present = False
                        break
                    if str(e["thrill_score"]) not in ln:
                        scores_present = False
                        break
                    cleaned = re.sub(re.escape(tid), "", ln)
                    cleaned = re.sub(r"\d+", "", cleaned)
                    cleaned = re.sub(r"[^\w\s]", "", cleaned)
                    if len(cleaned.strip()) < 3:
                        scores_present = False
                        break
                if scores_present:
                    scores["status_shortlist_order_and_scores"] = 1.0

            lines = status_text.splitlines()
            idx_next = None
            for i, ln in enumerate(lines):
                if re.search(r"next\s*-?\s*steps", ln, flags=re.IGNORECASE):
                    idx_next = i
                    break
            has_next_section = False
            if idx_next is not None:
                bullets = 0
                for j in range(idx_next + 1, len(lines)):
                    if lines[j].strip() == "":
                        continue
                    if re.match(r"^\s*[-*]\s+", lines[j]):
                        bullets += 1
                if bullets >= 1:
                    has_next_section = True
            else:
                any_bullets = any(re.match(r"^\s*[-*]\s+", ln) for ln in lines)
                mentions_next = re.search(r"next\s*-?\s*steps", status_text, flags=re.IGNORECASE) is not None
                if any_bullets and mentions_next:
                    has_next_section = True
            if has_next_section:
                scores["status_next_steps_bullets_present"] = 1.0

    # Outreach polished checks
    outreach_path = workspace / "output" / "outreach_polished_2026-04-16.md"
    outreach_text = _read_text(outreach_path)
    if outreach_text is not None:
        scores["outreach_polished_present"] = 1.0
        output_sections = _extract_output_drafts(outreach_text)
        if all(k in output_sections for k in ("1", "2", "3")):
            scores["outreach_drafts_count_and_structure"] = 1.0
            wc_ok = True
            for k in ("1", "2", "3"):
                if _word_count(output_sections[k]) > 100:
                    wc_ok = False
                    break
            if wc_ok:
                scores["outreach_each_draft_under_100_words"] = 1.0
            input_drafts_text = _read_text(workspace / "input" / "outreach_drafts.md") or ""
            input_tokens = _collect_preserve_tokens(input_drafts_text)
            preserve_ok = True
            for k in ("1", "2", "3"):
                tokens = input_tokens.get(k, [])
                content = output_sections.get(k, "")
                for tok in tokens:
                    if tok not in content:
                        preserve_ok = False
                        break
                if not preserve_ok:
                    break
            if preserve_ok:
                scores["outreach_preserved_tokens"] = 1.0

    # Cron checks
    cron_path = workspace / "output" / "cron_example.txt"
    cron_text = _read_text(cron_path)
    if cron_text is not None:
        non_empty_lines = [ln for ln in cron_text.splitlines() if ln.strip() != ""]
        if len(non_empty_lines) == 1:
            scores["cron_example_present_single_line"] = 1.0
            line = non_empty_lines[0]
            has_time = bool(re.match(r"^\s*0\s+7\s+\*\s+\*\s+\*", line))
            has_date_flag = bool(re.search(r"--date\s+\$\(\s*(?:/usr/bin/|/bin/)?date\s+\+\%F\s*\)", line))
            has_output = "output/" in line
            if has_time and has_date_flag and has_output:
                scores["cron_has_0700_and_date_flag_and_output"] = 1.0

    # Helper script presence
    helper_found = False
    for dname in ("tools", "scripts"):
        dpath = workspace / dname
        if dpath.exists() and dpath.is_dir():
            for p in dpath.rglob("*"):
                if p.is_file():
                    helper_found = True
                    break
        if helper_found:
            break
    if helper_found:
        scores["helper_script_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    key_order = [
        "daily_plan_json_present",
        "daily_plan_run_date_correct",
        "daily_plan_selected_ids_correct",
        "daily_plan_items_order_and_count",
        "daily_plan_items_fields_and_scores_correct",
        "daily_plan_pitches_comply",
        "status_report_present",
        "status_totals_correct",
        "status_exclusion_breakdown_correct",
        "status_shortlist_order_and_scores",
        "status_next_steps_bullets_present",
        "outreach_polished_present",
        "outreach_drafts_count_and_structure",
        "outreach_preserved_tokens",
        "outreach_each_draft_under_100_words",
        "cron_example_present_single_line",
        "cron_has_0700_and_date_flag_and_output",
        "helper_script_present",
    ]
    ordered = OrderedDict()
    for k in key_order:
        ordered[k] = float(result.get(k, 0.0))
    print(json.dumps(ordered, indent=2))


if __name__ == "__main__":
    main()