import json
import sys
import csv
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            headers = reader.fieldnames if reader.fieldnames is not None else []
            return rows, headers
    except Exception:
        return None, None


def _parse_int_maybe_commas(val: str) -> Optional[int]:
    if val is None:
        return 0
    s = str(val).strip()
    if s == "":
        return 0
    s = s.replace(",", "")
    # allow possible float-like entries that are integers (e.g., "123.0")
    try:
        if "." in s:
            f = float(s)
            return int(round(f))
        return int(s)
    except Exception:
        return None


def _format_int_with_commas(n: int) -> str:
    return f"{n:,}"


def _format_float_4(f: float) -> str:
    return f"{f:.4f}"


def _compute_expected_from_input(input_csv: Path) -> Optional[Dict]:
    rows, headers = _safe_read_csv_dicts(input_csv)
    if rows is None:
        return None
    expected_posts = []
    for row in rows:
        try:
            views = _parse_int_maybe_commas(row.get("views", ""))
            likes = _parse_int_maybe_commas(row.get("likes", ""))
            comments = _parse_int_maybe_commas(row.get("comments", ""))
            if views is None or likes is None or comments is None or views == 0:
                # If views is zero or unparseable, engagement_rate may be undefined; treat as 0 if views==0 else fail
                if views is None:
                    return None
                engagement_rate = 0.0 if views == 0 else None
                if engagement_rate is None:
                    return None
            else:
                engagement_rate = (likes + comments) / views
            post = {
                "post_id": row.get("post_id", "").strip(),
                "title": row.get("title", "").strip(),
                "recipe_type": row.get("recipe_type", "").strip(),
                "views": views,
                "likes": likes,
                "comments": comments,
                "engagement_rate": engagement_rate,
                "engagement_rate_str": _format_float_4(engagement_rate),
            }
            expected_posts.append(post)
        except Exception:
            return None

    # Weekly summary by recipe_type
    summary = {}
    for p in expected_posts:
        rt = p["recipe_type"]
        if rt not in summary:
            summary[rt] = {
                "recipe_type": rt,
                "total_views": 0,
                "total_likes": 0,
                "total_comments": 0,
                "rates": [],
            }
        summary[rt]["total_views"] += p["views"]
        summary[rt]["total_likes"] += p["likes"]
        summary[rt]["total_comments"] += p["comments"]
        summary[rt]["rates"].append(p["engagement_rate"])
    weekly_summary = []
    for rt, agg in summary.items():
        rates = agg["rates"]
        avg_rate = sum(rates) / len(rates) if rates else 0.0
        weekly_summary.append({
            "recipe_type": rt,
            "total_views": agg["total_views"],
            "total_likes": agg["total_likes"],
            "total_comments": agg["total_comments"],
            "avg_engagement_rate": avg_rate,
            "avg_engagement_rate_str": _format_float_4(avg_rate),
        })

    # Top posts by engagement_rate descending, take top 3
    top_sorted = sorted(expected_posts, key=lambda d: d["engagement_rate"], reverse=True)
    top3 = top_sorted[:3]

    # Best-performing recipe_type by avg_engagement_rate
    best_group = None
    if weekly_summary:
        best_group = max(weekly_summary, key=lambda d: d["avg_engagement_rate"])

    total_views_all = sum(p["views"] for p in expected_posts)

    return {
        "posts": expected_posts,
        "weekly_summary": weekly_summary,
        "top3": top3,
        "best_group": best_group,
        "total_views_all": total_views_all,
    }


def _read_weekly_summary(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    return _safe_read_csv_dicts(path)


def _read_top_posts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    return _safe_read_csv_dicts(path)


def _check_weekly_summary_columns(headers: Optional[List[str]]) -> bool:
    if headers is None:
        return False
    expected = ["recipe_type", "total_views", "total_likes", "total_comments", "avg_engagement_rate"]
    return headers == expected


def _parse_int_field_from_csv(row: Dict[str, str], key: str) -> Optional[int]:
    val = row.get(key, "")
    return _parse_int_maybe_commas(val)


def _get_stripped(row: Dict[str, str], key: str) -> str:
    val = row.get(key, "")
    return "" if val is None else str(val).strip()


def _check_weekly_summary_values(rows: Optional[List[Dict[str, str]]], expected: Dict) -> bool:
    if rows is None or expected is None:
        return False
    # Build a mapping from recipe_type to row
    actual_map = {}
    for r in rows:
        rt = _get_stripped(r, "recipe_type")
        if rt in actual_map:
            # Duplicate group
            return False
        actual_map[rt] = r
    exp_items = expected["weekly_summary"]
    # Ensure exact set of recipe_types matches
    exp_rts = {e["recipe_type"] for e in exp_items}
    act_rts = set(actual_map.keys())
    if exp_rts != act_rts:
        return False
    # Validate each group's totals and avg rate
    for e in exp_items:
        rt = e["recipe_type"]
        ar = actual_map.get(rt)
        if ar is None:
            return False
        tv = _parse_int_field_from_csv(ar, "total_views")
        tl = _parse_int_field_from_csv(ar, "total_likes")
        tc = _parse_int_field_from_csv(ar, "total_comments")
        aer_str = _get_stripped(ar, "avg_engagement_rate")
        if tv is None or tl is None or tc is None:
            return False
        if tv != e["total_views"] or tl != e["total_likes"] or tc != e["total_comments"]:
            return False
        # Check engagement rate numeric and formatting (4 decimals)
        # Must be exactly the 4-decimal string
        if aer_str != e["avg_engagement_rate_str"]:
            return False
        # Also ensure it parses to float close to expected
        try:
            aer_val = float(aer_str)
        except Exception:
            return False
        # Allow tiny float formatting tolerance around 1e-6
        if abs(aer_val - e["avg_engagement_rate"]) > 1e-6:
            return False
    return True


def _check_top_posts_columns(headers: Optional[List[str]]) -> bool:
    if headers is None:
        return False
    expected = ["post_id", "title", "recipe_type", "engagement_rate", "views", "likes", "comments"]
    return headers == expected


def _check_top_posts_values(rows: Optional[List[Dict[str, str]]], expected: Dict) -> bool:
    if rows is None or expected is None:
        return False
    # Must be exactly 3 rows
    if len(rows) != 3:
        return False
    exp_top = expected["top3"]
    # Check order and values strictly
    for i, ar in enumerate(rows):
        er = exp_top[i]
        # Compare fields
        if _get_stripped(ar, "post_id") != er["post_id"]:
            return False
        if _get_stripped(ar, "title") != er["title"]:
            return False
        if _get_stripped(ar, "recipe_type") != er["recipe_type"]:
            return False
        # Engagement format and value
        eng_str = _get_stripped(ar, "engagement_rate")
        if eng_str != er["engagement_rate_str"]:
            return False
        try:
            eng_val = float(eng_str)
        except Exception:
            return False
        if abs(eng_val - er["engagement_rate"]) > 1e-6:
            return False
        # Views/likes/comments ints
        v = _parse_int_field_from_csv(ar, "views")
        l = _parse_int_field_from_csv(ar, "likes")
        c = _parse_int_field_from_csv(ar, "comments")
        if v is None or l is None or c is None:
            return False
        if v != er["views"] or l != er["likes"] or c != er["comments"]:
            return False
    # Additionally ensure engagement rates are in descending order
    engs = [float(_get_stripped(r, "engagement_rate")) for r in rows]
    if not all(engs[i] >= engs[i + 1] - 1e-12 for i in range(len(engs) - 1)):
        return False
    return True


def _find_first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _contains_number_variants(text: str, number: int) -> bool:
    # Check both plain and comma-formatted occurrences
    plain = str(number)
    commas = _format_int_with_commas(number)
    return (plain in text) or (commas in text)


def _brand_update_checks(path: Path, expected: Dict) -> Dict[str, float]:
    scores = {
        "brand_update_file_exists": 0.0,
        "brand_update_greeting_and_paths": 0.0,
        "brand_update_total_views_correct": 0.0,
        "brand_update_best_recipe_type_and_rate": 0.0,
        "brand_update_top_posts_bullets": 0.0,
    }
    content = _safe_read_text(path)
    if content is None:
        return scores
    scores["brand_update_file_exists"] = 1.0

    # Greeting and paths
    first_line = _find_first_nonempty_line(content)
    greeting_ok = False
    if first_line.startswith("Hi") or first_line.startswith("hi"):
        # require a comma somewhere in the greeting line
        if "," in first_line:
            greeting_ok = True
    paths_ok = ("output/weekly_summary.csv" in content) and ("output/top_posts.csv" in content)
    if greeting_ok and paths_ok:
        scores["brand_update_greeting_and_paths"] = 1.0

    # Total views
    total_views = expected.get("total_views_all", None)
    if total_views is not None and _contains_number_variants(content, total_views):
        scores["brand_update_total_views_correct"] = 1.0

    # Best-performing recipe_type by avg_engagement_rate
    best = expected.get("best_group")
    if best is not None:
        rt = best["recipe_type"]
        rate_str = best["avg_engagement_rate_str"]
        if (rt.lower() in content.lower()) and (rate_str in content):
            scores["brand_update_best_recipe_type_and_rate"] = 1.0

    # Bulleted top 3 posts (title and engagement rate)
    bullet_lines = []
    for line in content.splitlines():
        ls = line.lstrip()
        if ls.startswith("- ") or ls.startswith("* ") or ls.startswith("•"):
            bullet_lines.append(ls)
    top3 = expected.get("top3", [])
    bullets_ok = True
    for post in top3:
        title = post["title"]
        rate_str = post["engagement_rate_str"]
        found = False
        for bl in bullet_lines:
            if (title.lower() in bl.lower()) and (rate_str in bl):
                found = True
                break
        if not found:
            bullets_ok = False
            break
    if bullets_ok and len(bullet_lines) >= 3:
        scores["brand_update_top_posts_bullets"] = 1.0

    return scores


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "weekly_summary_file_exists": 0.0,
        "weekly_summary_columns_correct": 0.0,
        "weekly_summary_values_correct": 0.0,
        "top_posts_file_exists": 0.0,
        "top_posts_columns_correct": 0.0,
        "top_posts_values_and_order_correct": 0.0,
        "brand_update_file_exists": 0.0,
        "brand_update_greeting_and_paths": 0.0,
        "brand_update_total_views_correct": 0.0,
        "brand_update_best_recipe_type_and_rate": 0.0,
        "brand_update_top_posts_bullets": 0.0,
    }

    input_csv = workspace / "data" / "metrics.csv"
    expected = _compute_expected_from_input(input_csv) if input_csv.exists() else None

    # Weekly summary checks
    weekly_summary_path = workspace / "output" / "weekly_summary.csv"
    if weekly_summary_path.exists():
        scores["weekly_summary_file_exists"] = 1.0
        ws_rows, ws_headers = _read_weekly_summary(weekly_summary_path)
        if _check_weekly_summary_columns(ws_headers):
            scores["weekly_summary_columns_correct"] = 1.0
        if expected is not None and ws_rows is not None and _check_weekly_summary_values(ws_rows, expected):
            scores["weekly_summary_values_correct"] = 1.0

    # Top posts checks
    top_posts_path = workspace / "output" / "top_posts.csv"
    if top_posts_path.exists():
        scores["top_posts_file_exists"] = 1.0
        tp_rows, tp_headers = _read_top_posts(top_posts_path)
        if _check_top_posts_columns(tp_headers):
            scores["top_posts_columns_correct"] = 1.0
        if expected is not None and tp_rows is not None and _check_top_posts_values(tp_rows, expected):
            scores["top_posts_values_and_order_correct"] = 1.0

    # Brand update checks
    brand_update_path = workspace / "drafts" / "brand_update_email.txt"
    if expected is not None:
        bu_scores = _brand_update_checks(brand_update_path, expected)
    else:
        bu_scores = {
            "brand_update_file_exists": 0.0,
            "brand_update_greeting_and_paths": 0.0,
            "brand_update_total_views_correct": 0.0,
            "brand_update_best_recipe_type_and_rate": 0.0,
            "brand_update_top_posts_bullets": 0.0,
        }
    scores.update(bu_scores)

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()