import json
import sys
import csv
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                return None, None
            rows = [dict(row) for row in reader]
            return fieldnames, rows
    except Exception:
        return None, None


def _parse_utc(ts: str) -> Optional[datetime]:
    try:
        return datetime.strptime(ts.strip(), "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _compute_expected_from_input(input_csv_path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]], Optional[List[str]], Optional[List[Dict[str, str]]]]:
    # Returns (expected_ranked_header, expected_ranked_rows, expected_themes_header, expected_themes_rows)
    header, rows = _safe_load_csv(input_csv_path)
    if header is None or rows is None:
        return None, None, None, None

    # Required fields in input
    required_fields = [
        "id", "received_utc", "from_email", "city", "subject", "body",
        "rating_helpful", "rating_energy", "contains_suggestion", "tags"
    ]
    for rf in required_fields:
        if rf not in header:
            return None, None, None, None

    # Filter: rating_helpful >= 4 AND contains_suggestion == "yes"
    filtered = []
    for r in rows:
        try:
            helpful = int(str(r.get("rating_helpful", "")).strip())
            contains = str(r.get("contains_suggestion", "")).strip().lower()
        except Exception:
            continue
        if helpful >= 4 and contains == "yes":
            # ensure required values present
            if r.get("body") is None or r.get("received_utc") is None:
                continue
            if _parse_utc(str(r["received_utc"])) is None:
                continue
            filtered.append(r)

    # Deduplicate by body (trim+lower), keep earliest received_utc
    # Sort by received_utc ascending to keep earliest when taking first occurrence
    filtered_sorted_by_time = sorted(
        filtered,
        key=lambda r: (_parse_utc(str(r["received_utc"])) or datetime.min)
    )
    seen_bodies = set()
    deduped = []
    for r in filtered_sorted_by_time:
        body_norm = str(r.get("body", "")).strip().lower()
        if body_norm in seen_bodies:
            continue
        seen_bodies.add(body_norm)
        deduped.append(r)

    # Rank by: rating_helpful desc, rating_energy desc, received_utc desc
    def sort_key(r: Dict[str, str]):
        try:
            helpful = int(str(r.get("rating_helpful", "")).strip())
        except Exception:
            helpful = -10**9
        try:
            energy = int(str(r.get("rating_energy", "")).strip())
        except Exception:
            energy = -10**9
        ts = _parse_utc(str(r.get("received_utc", "")).strip()) or datetime.min
        return (-helpful, -energy, -int(ts.timestamp()))
    # Actually to sort received_utc descending, we can sort by ts descending; using negative timestamp works
    ranked = sorted(deduped, key=lambda r: (
        -int(str(r.get("rating_helpful", "0")).strip() or "0"),
        -int(str(r.get("rating_energy", "0")).strip() or "0"),
        # received_utc desc: later timestamps first
        -int((_parse_utc(str(r.get("received_utc", "")).strip()) or datetime.min).timestamp())
    ))

    # Build expected feedback_ranked.csv rows with a 1-based rank and top 10
    ranked_top = ranked[:10]
    feedback_header = [
        "id", "received_utc", "from_email", "city", "subject", "body",
        "rating_helpful", "rating_energy", "contains_suggestion", "tags", "rank"
    ]
    feedback_rows: List[Dict[str, str]] = []
    for i, r in enumerate(ranked_top, start=1):
        out_row = {
            "id": str(r.get("id", "")),
            "received_utc": str(r.get("received_utc", "")),
            "from_email": str(r.get("from_email", "")),
            "city": str(r.get("city", "")),
            "subject": str(r.get("subject", "")),
            "body": str(r.get("body", "")),
            "rating_helpful": str(r.get("rating_helpful", "")),
            "rating_energy": str(r.get("rating_energy", "")),
            "contains_suggestion": str(r.get("contains_suggestion", "")),
            "tags": str(r.get("tags", "")),
            "rank": str(i),
        }
        feedback_rows.append(out_row)

    # Compute top themes from same filtered+deduped set
    tag_counts: Dict[str, int] = {}
    for r in deduped:
        tags_field = str(r.get("tags", ""))
        parts = [t.strip() for t in tags_field.split(";")] if tags_field != "" else []
        for t in parts:
            if t == "":
                continue
            tag_counts[t] = tag_counts.get(t, 0) + 1
    # Sort by count desc, tag asc
    sorted_tags = sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    themes_header = ["tag", "count"]
    themes_rows: List[Dict[str, str]] = [{"tag": k, "count": str(v)} for k, v in sorted_tags]

    return feedback_header, feedback_rows, themes_header, themes_rows


def _build_expected_email(draft_text: str, expected_themes_rows: List[Dict[str, str]], expected_feedback_rows: List[Dict[str, str]]) -> str:
    # Build top themes bullets from top 3 tags
    top3 = expected_themes_rows[:3]
    themes_bullets_lines = [f"- {row['tag']} ({row['count']})" for row in top3]
    themes_block = "\n".join(themes_bullets_lines)

    # Build top quotes bullets from top 5 feedback rows (body snippet and city)
    top5 = expected_feedback_rows[:5]
    def snippet(s: str) -> str:
        if len(s) <= 120:
            return s
        return s[:120] + "…"
    quotes_lines = [f"- \"{snippet(row['body'])}\" — {row['city']}" for row in top5]
    quotes_block = "\n".join(quotes_lines)

    expected = draft_text.replace("[TOP_THEMES]", themes_block).replace("[TOP_QUOTES]", quotes_block)
    return expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_present": 0.0,
        "feedback_ranked_exists": 0.0,
        "feedback_ranked_columns_correct": 0.0,
        "feedback_ranked_values_correct": 0.0,
        "top_themes_exists": 0.0,
        "top_themes_columns_correct": 0.0,
        "top_themes_values_correct": 0.0,
        "followup_email_exists": 0.0,
        "followup_email_top_themes_bullets_correct": 0.0,
        "followup_email_top_quotes_bullets_correct": 0.0,
        "followup_email_other_text_unchanged": 0.0,
    }

    # Check script presence
    scripts_dir = workspace / "scripts"
    script_matches = []
    if scripts_dir.exists() and scripts_dir.is_dir():
        script_matches = list(scripts_dir.glob("analyze_feedback.*"))
    if any(p.is_file() for p in script_matches):
        scores["script_present"] = 1.0

    input_csv_path = workspace / "input" / "fan_inbox.csv"
    draft_md_path = workspace / "input" / "draft_followup_email.md"
    ranked_csv_path = workspace / "output" / "feedback_ranked.csv"
    themes_csv_path = workspace / "output" / "top_themes.csv"
    followup_md_path = workspace / "output" / "followup_email.md"

    # Compute expected outputs from input
    exp_ranked_header, exp_ranked_rows, exp_themes_header, exp_themes_rows = _compute_expected_from_input(input_csv_path)

    # feedback_ranked.csv checks
    if ranked_csv_path.exists():
        scores["feedback_ranked_exists"] = 1.0
        prod_header, prod_rows = _safe_load_csv(ranked_csv_path)
        if prod_header is not None and prod_rows is not None:
            # Columns check
            expected_header_list = [
                "id", "received_utc", "from_email", "city", "subject", "body",
                "rating_helpful", "rating_energy", "contains_suggestion", "tags", "rank"
            ]
            if prod_header == expected_header_list:
                scores["feedback_ranked_columns_correct"] = 1.0
            # Values check only if we have expected computed
            if exp_ranked_rows is not None:
                # Compare length
                try:
                    # Convert both to list of ordered dicts by expected header
                    def norm_rows(rows: List[Dict[str, str]], header: List[str]) -> List[List[str]]:
                        out = []
                        for r in rows:
                            out.append([str(r.get(h, "")) for h in header])
                        return out
                    prod_norm = norm_rows(prod_rows, expected_header_list)
                    exp_norm = norm_rows(exp_ranked_rows, expected_header_list)
                    if prod_norm == exp_norm:
                        scores["feedback_ranked_values_correct"] = 1.0
                except Exception:
                    pass
        # else malformed: leave zeros
    # else missing: leave zeros

    # top_themes.csv checks
    if themes_csv_path.exists():
        scores["top_themes_exists"] = 1.0
        prod_header, prod_rows = _safe_load_csv(themes_csv_path)
        if prod_header is not None and prod_rows is not None:
            expected_themes_header = ["tag", "count"]
            if prod_header == expected_themes_header:
                scores["top_themes_columns_correct"] = 1.0
            if exp_themes_rows is not None:
                # Normalize counts to ints for comparison then back to strings
                try:
                    def norm_theme_rows(rows: List[Dict[str, str]]) -> List[Tuple[str, int]]:
                        out_list: List[Tuple[str, int]] = []
                        for r in rows:
                            tag = str(r.get("tag", ""))
                            try:
                                cnt = int(str(r.get("count", "")).strip())
                            except Exception:
                                return []
                            out_list.append((tag, cnt))
                        return out_list
                    prod_norm = norm_theme_rows(prod_rows)
                    exp_norm = [(r["tag"], int(r["count"])) for r in exp_themes_rows]
                    if prod_norm == exp_norm:
                        scores["top_themes_values_correct"] = 1.0
                except Exception:
                    pass

    # followup_email.md checks
    if followup_md_path.exists():
        scores["followup_email_exists"] = 1.0
        actual_email = _read_text(followup_md_path)
        draft_email = _read_text(draft_md_path)
        if actual_email is not None and draft_email is not None and exp_ranked_rows is not None and exp_themes_rows is not None:
            expected_email = _build_expected_email(draft_email, exp_themes_rows, exp_ranked_rows)
            # Exact content check for "other text unchanged"
            if actual_email == expected_email:
                scores["followup_email_other_text_unchanged"] = 1.0
                scores["followup_email_top_themes_bullets_correct"] = 1.0
                scores["followup_email_top_quotes_bullets_correct"] = 1.0
            else:
                # Partial checks: build expected blocks and see if present
                top3 = exp_themes_rows[:3]
                themes_bullets_lines = [f"- {row['tag']} ({row['count']})" for row in top3]
                themes_block = "\n".join(themes_bullets_lines)
                if themes_block in actual_email and "[TOP_THEMES]" not in actual_email:
                    scores["followup_email_top_themes_bullets_correct"] = 1.0
                # Quotes block
                def snippet(s: str) -> str:
                    return s if len(s) <= 120 else s[:120] + "…"
                top5 = exp_ranked_rows[:5]
                quotes_lines = [f"- \"{snippet(row['body'])}\" — {row['city']}" for row in top5]
                quotes_block = "\n".join(quotes_lines)
                if quotes_block in actual_email and "[TOP_QUOTES]" not in actual_email:
                    scores["followup_email_top_quotes_bullets_correct"] = 1.0
        else:
            # If we cannot compute expected email due to missing draft or expected rows, leave zeros
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()