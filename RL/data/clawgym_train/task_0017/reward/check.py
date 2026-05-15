import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


START_MARKER = "<!-- START TRIVIA -->"
END_MARKER = "<!-- END TRIVIA -->"


def safe_read_text(path: Path) -> Tuple[bool, str]:
    try:
        return True, path.read_text(encoding="utf-8")
    except Exception:
        return False, ""


def safe_load_csv(path: Path) -> Tuple[bool, List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        return True, rows
    except Exception:
        return False, []


def normalize_bullet(text: str) -> str:
    t = text.strip()
    if t.startswith("- "):
        t = t[2:]
    t = re.sub(r"\[A\d+\]", "", t)
    t = re.sub(r"\s+", " ", t)
    t = t.strip().lower()
    t = t.rstrip(" .;:!?")
    return t


def parse_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def compute_expected_ranking(workspace: Path) -> Optional[List[Dict[str, object]]]:
    agenda_path = workspace / "input" / "agenda_items.csv"
    notes_paths = [workspace / "input" / "notes_2024-03.md", workspace / "input" / "notes_2024-04.md"]

    ok_agenda, agenda_rows = safe_load_csv(agenda_path)
    if not ok_agenda or not agenda_rows:
        return None

    filtered = []
    for row in agenda_rows:
        try:
            if row.get("topic") == "political_trivia" and row.get("scope") == "Montreal":
                pr = parse_int(str(row.get("priority", "")).strip())
                if pr is None:
                    return None
                filtered.append({
                    "id": row.get("id"),
                    "title": row.get("title"),
                    "priority": pr
                })
        except Exception:
            return None

    notes_texts = []
    for p in notes_paths:
        ok, txt = safe_read_text(p)
        if not ok:
            return None
        notes_texts.append(txt)

    all_text = "\n".join(notes_texts)
    expected = []
    for item in filtered:
        id_ = item["id"]
        token = f"[{id_}]"
        mentions = all_text.count(token)
        score = (mentions * 2) + (6 - int(item["priority"]))
        expected.append({
            "id": id_,
            "title": item["title"],
            "priority": int(item["priority"]),
            "mentions": int(mentions),
            "score": int(score),
        })

    expected.sort(key=lambda r: (-r["score"], -r["mentions"], r["title"] if r["title"] is not None else ""))
    return expected


def extract_expected_bullets_for_item(workspace: Path, item_id: str) -> List[str]:
    notes_paths = [workspace / "input" / "notes_2024-03.md", workspace / "input" / "notes_2024-04.md"]
    bullets: List[str] = []
    token = f"[{item_id}]"
    for path in notes_paths:
        ok, text = safe_read_text(path)
        if not ok:
            continue
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.strip().startswith("#") and token in line:
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if nxt.strip().startswith("#"):
                        break
                    if nxt.startswith("- "):
                        bullets.append(nxt)
                        if len(bullets) >= 2:
                            return bullets[:2]
                    j += 1
                i = j
                continue
            i += 1
        if len(bullets) >= 2:
            break
    return bullets[:2]


def find_markers_indices(text: str) -> Optional[Tuple[int, int]]:
    start_idx = text.find(START_MARKER)
    if start_idx == -1:
        return None
    end_idx = text.find(END_MARKER, start_idx + len(START_MARKER))
    if end_idx == -1:
        return None
    return start_idx, end_idx


def parse_replaced_section(body: str, expected_items: List[Dict[str, object]]) -> Dict[str, object]:
    lines = body.splitlines()
    title_line = ""
    for ln in lines:
        if ln.strip():
            title_line = ln.strip()
            break

    item_to_header = {it["id"]: f'{it["title"]} ({it["id"]})' for it in expected_items}
    header_positions: Dict[str, int] = {}
    for idx, ln in enumerate(lines):
        for it in expected_items:
            hdr = item_to_header[it["id"]]
            if hdr in ln:
                if it["id"] not in header_positions:
                    header_positions[it["id"]] = idx

    items_info = []
    for it in expected_items:
        itid = it["id"]
        pos = header_positions.get(itid, -1)
        bullets = []
        if pos != -1:
            next_header_pos_candidates = [p for k, p in header_positions.items() if p > pos]
            next_header_pos = min(next_header_pos_candidates) if next_header_pos_candidates else len(lines)
            j = pos + 1
            while j < next_header_pos:
                line = lines[j]
                if line.startswith("- "):
                    bullets.append(line.strip())
                elif line.strip() == "":
                    pass
                else:
                    break
                j += 1
        items_info.append({"id": itid, "title": it["title"], "index": pos, "bullets": bullets})

    last_nonempty = ""
    for ln in reversed(lines):
        if ln.strip():
            last_nonempty = ln.strip()
            break

    return {"title_line": title_line, "items_info": items_info, "last_nonempty": last_nonempty}


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "ranked_csv_exists": 0.0,
        "ranked_csv_header_correct": 0.0,
        "ranked_csv_row_count_correct": 0.0,
        "ranked_csv_ids_filtered_correct": 0.0,
        "ranked_csv_mentions_correct": 0.0,
        "ranked_csv_scores_correct": 0.0,
        "ranked_csv_sorting_correct": 0.0,
        "summary_exists": 0.0,
        "summary_markers_preserved": 0.0,
        "summary_title_present": 0.0,
        "summary_title_exact_match": 0.0,
        "summary_top3_items_present_and_ordered": 0.0,
        "summary_item_bullet_limits_valid": 0.0,
        "summary_bullets_content_matches_notes": 0.0,
        "summary_sources_line_correct": 0.0,
    }

    expected_ranking = compute_expected_ranking(workspace)
    top3_expected = expected_ranking[:3] if expected_ranking else None

    ranked_path = workspace / "outputs" / "trivia_ranked.csv"
    if ranked_path.exists():
        scores["ranked_csv_exists"] = 1.0
        ok_csv, rows = safe_load_csv(ranked_path)
        if ok_csv and rows is not None:
            try:
                with ranked_path.open("r", encoding="utf-8", newline="") as f:
                    first_line = f.readline().strip()
                expected_header = "id,title,priority,mentions,score"
                if first_line == expected_header:
                    scores["ranked_csv_header_correct"] = 1.0
            except Exception:
                pass

            actual_ids = [row.get("id") for row in rows if "id" in row]
            if expected_ranking is not None:
                expected_ids = [r["id"] for r in expected_ranking]
                if len(rows) == len(expected_ranking):
                    scores["ranked_csv_row_count_correct"] = 1.0
                if actual_ids and set(actual_ids) == set(expected_ids):
                    scores["ranked_csv_ids_filtered_correct"] = 1.0

                mentions_ok = True
                scores_ok = True
                priority_ok = True
                id_to_expected = {r["id"]: r for r in expected_ranking}
                for row in rows:
                    rid = row.get("id", "")
                    exp = id_to_expected.get(rid)
                    if not exp:
                        mentions_ok = False
                        scores_ok = False
                        priority_ok = False
                        continue
                    m = parse_int(str(row.get("mentions", "")).strip())
                    s = parse_int(str(row.get("score", "")).strip())
                    p = parse_int(str(row.get("priority", "")).strip())
                    if m is None or m != int(exp["mentions"]):
                        mentions_ok = False
                    if s is None or s != int(exp["score"]):
                        scores_ok = False
                    if p is None or p != int(exp["priority"]):
                        priority_ok = False
                if mentions_ok:
                    scores["ranked_csv_mentions_correct"] = 1.0
                if scores_ok and priority_ok:
                    scores["ranked_csv_scores_correct"] = 1.0

                if actual_ids == expected_ids:
                    scores["ranked_csv_sorting_correct"] = 1.0

    summary_in_path = workspace / "input" / "existing_summary.md"
    summary_out_path = workspace / "outputs" / "meeting_summary_updated.md"

    ok_in, summary_in = safe_read_text(summary_in_path)
    ok_out, summary_out = safe_read_text(summary_out_path)

    if ok_out:
        scores["summary_exists"] = 1.0

    if ok_in and ok_out:
        markers_in = find_markers_indices(summary_in)
        markers_out = find_markers_indices(summary_out)
        if markers_in and markers_out:
            in_start, in_end = markers_in
            out_start, out_end = markers_out
            in_prefix = summary_in[:in_start + len(START_MARKER)]
            out_prefix = summary_out[:out_start + len(START_MARKER)]
            in_suffix = summary_in[in_end:]
            out_suffix = summary_out[out_end:]
            if in_prefix == out_prefix and in_suffix == out_suffix:
                scores["summary_markers_preserved"] = 1.0

            body = summary_out[out_start + len(START_MARKER):out_end]
            parsed = {"title_line": "", "items_info": [], "last_nonempty": ""}
            if top3_expected is not None:
                parsed = parse_replaced_section(body, top3_expected)
            else:
                lines = body.splitlines()
                title_line = ""
                for ln in lines:
                    if ln.strip():
                        title_line = ln.strip()
                        break
                parsed["title_line"] = title_line
                last_nonempty = ""
                for ln in reversed(lines):
                    if ln.strip():
                        last_nonempty = ln.strip()
                        break
                parsed["last_nonempty"] = last_nonempty

            title_line = parsed.get("title_line", "").strip()
            if title_line and ("Top 3" in title_line) and ("Montreal" in title_line) and ("Political Trivia" in title_line) and ("2024" in title_line):
                scores["summary_title_present"] = 1.0
            if title_line == "Top 3 Montreal Political Trivia (Mar–Apr 2024)":
                scores["summary_title_exact_match"] = 1.0

            last_nonempty = parsed.get("last_nonempty", "").strip()
            if last_nonempty == "Sources: notes_2024-03.md, notes_2024-04.md; ranked via agenda_items.csv.":
                scores["summary_sources_line_correct"] = 1.0

            if top3_expected is not None:
                items_info = parsed.get("items_info", [])
                indices = [info.get("index", -1) for info in items_info]
                present_and_ordered = all(idx >= 0 for idx in indices) and all(indices[i] < indices[i+1] for i in range(len(indices)-1))
                if present_and_ordered:
                    scores["summary_top3_items_present_and_ordered"] = 1.0

                limit_valid_count = 0
                content_match_scores: List[float] = []
                for it in top3_expected:
                    itid = it["id"]
                    info = next((x for x in items_info if x.get("id") == itid), None)
                    actual_bullets = info.get("bullets", []) if info else []
                    if 1 <= len(actual_bullets) <= 2:
                        limit_valid_count += 1
                    exp_bullets = extract_expected_bullets_for_item(workspace, itid)
                    exp_norm = [normalize_bullet(b) for b in exp_bullets]
                    act_norm = [normalize_bullet(b) for b in actual_bullets[:2]]
                    if len(act_norm) == 0 or len(act_norm) > 2:
                        content_match_scores.append(0.0)
                    else:
                        remaining = exp_norm.copy()
                        matches = 0
                        for ab in act_norm:
                            matched = False
                            for i_en, en in enumerate(remaining):
                                if ab == en or (ab in en) or (en in ab):
                                    matches += 1
                                    remaining.pop(i_en)
                                    matched = True
                                    break
                            if not matched:
                                pass
                        if matches == len(act_norm):
                            content_match_scores.append(1.0)
                        elif matches > 0:
                            content_match_scores.append(0.5)
                        else:
                            content_match_scores.append(0.0)

                if len(top3_expected) > 0:
                    scores["summary_item_bullet_limits_valid"] = float(limit_valid_count) / float(len(top3_expected))
                    scores["summary_bullets_content_matches_notes"] = sum(content_match_scores) / float(len(top3_expected))

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()