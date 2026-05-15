import json
import csv
import re
from pathlib import Path
from datetime import datetime, timedelta, date
import sys
from typing import List, Dict, Tuple, Optional, Any


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


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _parse_moves_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the given structure.
    Returns dict with keys: planning_window {start_date, end_date}, residences (list),
    and favorites_ordered (list of cuisines in residence order, deduped).
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    start_date = None
    end_date = None
    residences: List[Dict[str, Any]] = []
    in_residences = False
    current_res: Optional[Dict[str, Any]] = None

    def parse_list_from_brackets(s: str) -> List[str]:
        # s expected like: ["A", "B"]
        inside = s.strip()
        if inside.startswith("[") and inside.endswith("]"):
            inside = inside[1:-1].strip()
            if not inside:
                return []
            # split by comma but strip quotes/spaces
            parts = []
            for part in inside.split(","):
                p = part.strip().strip('"').strip("'")
                if p:
                    parts.append(p)
            return parts
        return []

    for line in lines:
        raw = line.rstrip("\n")
        # Normalize indentation
        if raw.strip().startswith("#") or not raw.strip():
            continue
        if raw.strip().startswith("planning_window:"):
            in_residences = False
            current_res = None
            continue
        if "start_date:" in raw and raw.strip().startswith("start_date:"):
            try:
                start_date = raw.split(":", 1)[1].strip()
            except Exception:
                pass
            continue
        if "end_date:" in raw and raw.strip().startswith("end_date:"):
            try:
                end_date = raw.split(":", 1)[1].strip()
            except Exception:
                pass
            continue
        if raw.strip().startswith("residences:"):
            in_residences = True
            current_res = None
            continue
        if in_residences:
            if raw.strip().startswith("- "):
                # start new residence
                if current_res is not None:
                    residences.append(current_res)
                current_res = {}
                # may have " - city: ..." in same line, ignore other keys
                # handled by subsequent lines as well
                if "partner_favorites:" in raw:
                    part = raw.split("partner_favorites:", 1)[1].strip()
                    current_res["partner_favorites"] = parse_list_from_brackets(part)
                continue
            # within a residence block
            if current_res is not None:
                s = raw.strip()
                if s.startswith("partner_favorites:"):
                    part = s.split(":", 1)[1].strip()
                    current_res["partner_favorites"] = parse_list_from_brackets(part)
                # we ignore other fields (city, country, years)
                continue
        # prioritize rules ignored for parsing needs

    if current_res is not None:
        residences.append(current_res)

    if not start_date or not end_date:
        # Invalid planning window parsing
        return None

    favorites_ordered: List[str] = []
    for res in residences:
        favs = res.get("partner_favorites", [])
        for c in favs:
            if c not in favorites_ordered:
                favorites_ordered.append(c)

    return {
        "planning_window": {"start_date": start_date, "end_date": end_date},
        "residences": residences,
        "favorites_ordered": favorites_ordered,
    }


def _parse_blog_posts(path: Path) -> Optional[List[Dict[str, str]]]:
    """
    Returns list of dicts with keys: cuisine, dish, date (YYYY-MM-DD)
    """
    html = _read_text(path)
    if html is None:
        return None
    # Regex to capture data-cuisine, data-dish, and datetime attribute of time tag within the article
    pattern = re.compile(
        r'<article[^>]*class="post"[^>]*data-cuisine="([^"]+)"[^>]*data-dish="([^"]+)"[^>]*>.*?<time[^>]*datetime="(\d{4}-\d{2}-\d{2})"',
        re.DOTALL | re.IGNORECASE,
    )
    posts: List[Dict[str, str]] = []
    for m in pattern.finditer(html):
        cuisine = m.group(1).strip()
        dish = m.group(2).strip()
        d = m.group(3).strip()
        posts.append({"cuisine": cuisine, "dish": dish, "date": d})
    return posts


def _daterange(start: date, end: date) -> List[date]:
    days: List[date] = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur = cur + timedelta(days=1)
    return days


def _weekday_abbrev(d: date) -> str:
    # Monday=0 .. Sunday=6; map to Mon, Tue, Wed, Thu, Fri, Sat, Sun
    mapping = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return mapping[d.weekday()]


def _iso_week_key(d: date) -> Tuple[int, int]:
    iso = d.isocalendar()
    return (iso[0], iso[1])  # (year, week)


def _parse_plan_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    return _load_csv_dicts(path)


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "content_plan_file_exists_and_headers": 0.0,
        "scheduled_dates_within_window": 0.0,
        "scheduled_on_preferred_days_and_weekly_caps": 0.0,
        "scheduled_dishes_valid_assets_and_not_recent": 0.0,
        "scheduled_unique_dishes_and_partner_favorites": 0.0,
        "source_row_and_asset_path_match": 0.0,
        "plan_summary_json_consistency": 0.0,
        "unscheduled_slots_reported_correctly": 0.0,
        "validation_report_missing_assets": 0.0,
        "validation_report_recent_exclusions": 0.0,
        "validation_report_weekly_caps_note": 0.0,
        "fully_utilizes_valid_dishes_when_possible": 0.0,
    }

    # Load inputs
    moves_path = workspace / "input" / "moves.yaml"
    recipes_path = workspace / "input" / "recipes.csv"
    blog_path = workspace / "input" / "blog_posts.html"
    channels_path = workspace / "input" / "channels.json"
    assets_dir = workspace / "input" / "assets"

    moves = _parse_moves_yaml(moves_path)
    recipes = _load_csv_dicts(recipes_path)
    posts = _parse_blog_posts(blog_path)
    channels = _load_json(channels_path)

    # Planning window from moves.yaml
    if moves and "planning_window" in moves:
        try:
            pw_start = datetime.strptime(moves["planning_window"]["start_date"], "%Y-%m-%d").date()
            pw_end = datetime.strptime(moves["planning_window"]["end_date"], "%Y-%m-%d").date()
        except Exception:
            pw_start = None
            pw_end = None
    else:
        pw_start = None
        pw_end = None

    # If missing planning window we cannot proceed with most checks
    # Prepare channel info
    channel_info: Dict[str, Dict[str, Any]] = {}
    if isinstance(channels, list):
        for ch in channels:
            name = ch.get("name")
            pref = ch.get("preferred_days")
            cap = ch.get("max_posts_per_week")
            if isinstance(name, str) and isinstance(pref, list) and isinstance(cap, int):
                channel_info[name] = {"preferred_days": list(pref), "max_posts_per_week": cap}

    # Prepare recipes index and missing assets detection
    recipes_index: Dict[Tuple[str, str], Dict[str, Any]] = {}
    missing_assets: List[str] = []
    if isinstance(recipes, list):
        for idx, row in enumerate(recipes, start=1):
            cuisine = row.get("cuisine", "").strip()
            dish = row.get("dish_name", "").strip()
            asset_path = row.get("asset_path", "").strip()
            recipes_index[(cuisine, dish)] = {
                "row_index": idx,
                "asset_path": asset_path,
                "row": row,
            }
            # Check asset existence
            asset_full = workspace / asset_path
            if not asset_full.exists():
                missing_assets.append(asset_path)

    # Compute partner favorites ordered
    favorites_ordered: List[str] = moves["favorites_ordered"] if moves and "favorites_ordered" in moves else []
    favorites_set = set(favorites_ordered)

    # Parse blog posts for last 30 days window prior to planning window
    recent_exclusions: Dict[Tuple[str, str], str] = {}
    if posts is not None and pw_start is not None:
        # last 30 days defined as 2026-04-01 to 2026-04-30 inclusive per task
        try:
            last30_start = datetime.strptime("2026-04-01", "%Y-%m-%d").date()
            last30_end = datetime.strptime("2026-04-30", "%Y-%m-%d").date()
        except Exception:
            last30_start = None
            last30_end = None
        if last30_start and last30_end:
            for p in posts:
                try:
                    d = datetime.strptime(p.get("date", ""), "%Y-%m-%d").date()
                except Exception:
                    continue
                if last30_start <= d <= last30_end:
                    key = (p.get("cuisine", "").strip(), p.get("dish", "").strip())
                    if key[0] and key[1]:
                        recent_exclusions[key] = p.get("date", "")
    else:
        # cannot parse; leave exclusions empty
        pass

    # Determine valid dishes according to rules:
    # - cuisine in partner favorites
    # - asset exists
    # - not in recent_exclusions
    valid_dishes: List[Tuple[str, str]] = []
    if isinstance(recipes, list) and moves is not None:
        for (cuisine, dish), info in recipes_index.items():
            if favorites_set and cuisine not in favorites_set:
                continue
            asset_path = info["asset_path"]
            if not (workspace / asset_path).exists():
                continue
            if (cuisine, dish) in recent_exclusions:
                continue
            valid_dishes.append((cuisine, dish))

        # Sort valid dishes by cuisine priority according to residences order
        cuisine_priority = {c: i for i, c in enumerate(favorites_ordered)}
        valid_dishes.sort(key=lambda x: cuisine_priority.get(x[0], 10**6))
    else:
        valid_dishes = []

    # Compute channel slots within window
    all_slots: List[Tuple[str, str]] = []
    per_week_slots: Dict[str, Dict[Tuple[int, int], List[date]]] = {}
    if pw_start is not None and pw_end is not None and channel_info:
        for ch_name, info in channel_info.items():
            preferred = set(info["preferred_days"])
            cap = info["max_posts_per_week"]
            per_week_slots[ch_name] = {}
            for d in _daterange(pw_start, pw_end):
                if _weekday_abbrev(d) in preferred:
                    wk = _iso_week_key(d)
                    per_week_slots[ch_name].setdefault(wk, []).append(d)
            # Apply weekly caps deterministically: for each week, select up to cap earliest preferred days
            for wk, days in per_week_slots[ch_name].items():
                days_sorted = sorted(days)
                for selected in days_sorted[:cap]:
                    all_slots.append((ch_name, selected.isoformat()))
    # Determine total slot capacity
    total_slot_capacity = len(all_slots)

    # Load outputs
    content_plan_path = workspace / "output" / "content_plan.csv"
    plan_rows = _parse_plan_csv(content_plan_path)

    summary_path = workspace / "output" / "summary" / "plan_summary.json"
    plan_summary = _load_json(summary_path)

    validation_report_path = workspace / "output" / "validation_report.txt"
    validation_report_text = _read_text(validation_report_path)

    # content_plan_file_exists_and_headers
    expected_headers = ["date", "channel", "cuisine", "dish_name", "asset_path", "source_recipe_row", "rationale"]
    headers_ok = False
    if isinstance(plan_rows, list):
        # Check headers via DictReader fieldnames
        try:
            with content_plan_path.open(newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                first_row = next(reader, None)
                if first_row == expected_headers:
                    headers_ok = True
        except Exception:
            headers_ok = False
    if headers_ok and isinstance(plan_rows, list):
        scores["content_plan_file_exists_and_headers"] = 1.0

    # scheduled_dates_within_window
    dates_ok = False
    if headers_ok and isinstance(plan_rows, list) and pw_start is not None and pw_end is not None:
        try:
            ok = True
            for r in plan_rows:
                ds = r.get("date", "")
                try:
                    d = datetime.strptime(ds, "%Y-%m-%d").date()
                except Exception:
                    ok = False
                    break
                if not (pw_start <= d <= pw_end):
                    ok = False
                    break
            dates_ok = ok
        except Exception:
            dates_ok = False
    if dates_ok:
        scores["scheduled_dates_within_window"] = 1.0

    # scheduled_on_preferred_days_and_weekly_caps
    pref_and_caps_ok = False
    if headers_ok and isinstance(plan_rows, list) and pw_start is not None and pw_end is not None and channel_info:
        try:
            # preferred days check
            ok = True
            # weekly caps check
            per_week_counts: Dict[str, Dict[Tuple[int, int], int]] = {}
            seen_channel_date: set = set()
            for r in plan_rows:
                ch = r.get("channel", "")
                ds = r.get("date", "")
                if not ch or not ds:
                    ok = False
                    break
                if ch not in channel_info:
                    ok = False
                    break
                try:
                    d = datetime.strptime(ds, "%Y-%m-%d").date()
                except Exception:
                    ok = False
                    break
                if _weekday_abbrev(d) not in set(channel_info[ch]["preferred_days"]):
                    ok = False
                    break
                wk = _iso_week_key(d)
                per_week_counts.setdefault(ch, {})
                per_week_counts[ch][wk] = per_week_counts[ch].get(wk, 0) + 1
                if (ch, ds) in seen_channel_date:
                    ok = False
                    break
                seen_channel_date.add((ch, ds))
            if ok:
                for ch, weeks in per_week_counts.items():
                    cap = channel_info[ch]["max_posts_per_week"]
                    for wk, cnt in weeks.items():
                        if cnt > cap:
                            ok = False
                            break
                    if not ok:
                        break
            pref_and_caps_ok = ok
        except Exception:
            pref_and_caps_ok = False
    if pref_and_caps_ok:
        scores["scheduled_on_preferred_days_and_weekly_caps"] = 1.0

    # scheduled_dishes_valid_assets_and_not_recent
    valid_assets_and_not_recent_ok = False
    if headers_ok and isinstance(plan_rows, list) and recipes_index:
        try:
            ok = True
            for r in plan_rows:
                cuisine = r.get("cuisine", "").strip()
                dish = r.get("dish_name", "").strip()
                asset = r.get("asset_path", "").strip()
                key = (cuisine, dish)
                if key not in recipes_index:
                    ok = False
                    break
                # asset must match recipe's asset and exist
                expected_asset = recipes_index[key]["asset_path"]
                if asset != expected_asset:
                    ok = False
                    break
                if not (workspace / asset).exists():
                    ok = False
                    break
                # not recently posted
                if key in recent_exclusions:
                    ok = False
                    break
            valid_assets_and_not_recent_ok = ok
        except Exception:
            valid_assets_and_not_recent_ok = False
    if valid_assets_and_not_recent_ok:
        scores["scheduled_dishes_valid_assets_and_not_recent"] = 1.0

    # scheduled_unique_dishes_and_partner_favorites
    unique_and_favorites_ok = False
    if headers_ok and isinstance(plan_rows, list) and moves is not None:
        try:
            ok = True
            seen_dishes: set = set()
            for r in plan_rows:
                cuisine = r.get("cuisine", "").strip()
                dish = r.get("dish_name", "").strip()
                if (cuisine, dish) in seen_dishes:
                    ok = False
                    break
                seen_dishes.add((cuisine, dish))
                if favorites_set and cuisine not in favorites_set:
                    ok = False
                    break
            unique_and_favorites_ok = ok
        except Exception:
            unique_and_favorites_ok = False
    if unique_and_favorites_ok:
        scores["scheduled_unique_dishes_and_partner_favorites"] = 1.0

    # source_row_and_asset_path_match
    source_row_ok = False
    if headers_ok and isinstance(plan_rows, list) and recipes_index:
        try:
            ok = True
            for r in plan_rows:
                cuisine = r.get("cuisine", "").strip()
                dish = r.get("dish_name", "").strip()
                key = (cuisine, dish)
                if key not in recipes_index:
                    ok = False
                    break
                expected_row = recipes_index[key]["row_index"]
                src = r.get("source_recipe_row", "").strip()
                src_i = _safe_int(src)
                if src_i != expected_row:
                    ok = False
                    break
                expected_asset = recipes_index[key]["asset_path"]
                if r.get("asset_path", "").strip() != expected_asset:
                    ok = False
                    break
                # rationale must be non-empty
                if not r.get("rationale", "").strip():
                    ok = False
                    break
            source_row_ok = ok
        except Exception:
            source_row_ok = False
    if source_row_ok:
        scores["source_row_and_asset_path_match"] = 1.0

    # plan_summary_json_consistency
    summary_ok = False
    if isinstance(plan_rows, list) and isinstance(plan_summary, dict) and pw_start is not None and pw_end is not None:
        try:
            ok = True
            pw = plan_summary.get("planning_window", {})
            if pw.get("start_date") != pw_start.isoformat() or pw.get("end_date") != pw_end.isoformat():
                ok = False
            total_scheduled = plan_summary.get("total_scheduled_posts")
            if total_scheduled != len(plan_rows):
                ok = False
            # by_channel
            by_channel = plan_summary.get("by_channel", {})
            actual_by_channel: Dict[str, int] = {}
            for r in plan_rows:
                ch = r.get("channel", "")
                actual_by_channel[ch] = actual_by_channel.get(ch, 0) + 1
            if by_channel != actual_by_channel:
                ok = False
            # by_cuisine
            by_cuisine = plan_summary.get("by_cuisine", {})
            actual_by_cuisine: Dict[str, int] = {}
            for r in plan_rows:
                cu = r.get("cuisine", "")
                actual_by_cuisine[cu] = actual_by_cuisine.get(cu, 0) + 1
            if by_cuisine != actual_by_cuisine:
                ok = False
            # unscheduled_slots must be an array (checked later in detail)
            if not isinstance(plan_summary.get("unscheduled_slots"), list):
                ok = False
            summary_ok = ok
        except Exception:
            summary_ok = False
    if summary_ok:
        scores["plan_summary_json_consistency"] = 1.0

    # unscheduled_slots_reported_correctly
    unscheduled_ok = False
    if isinstance(plan_rows, list) and isinstance(plan_summary, dict) and pw_start is not None and pw_end is not None and channel_info:
        try:
            # Build scheduled set
            scheduled_set = set()
            for r in plan_rows:
                ch = r.get("channel", "").strip()
                ds = r.get("date", "").strip()
                if ch and ds:
                    scheduled_set.add((ch, ds))
            expected_unscheduled = sorted(list(set(all_slots) - scheduled_set))
            reported_unscheduled = plan_summary.get("unscheduled_slots", [])
            reported_list = []
            ok = True
            if isinstance(reported_unscheduled, list):
                for it in reported_unscheduled:
                    if not isinstance(it, dict):
                        ok = False
                        break
                    ch = it.get("channel")
                    ds = it.get("date")
                    if not isinstance(ch, str) or not isinstance(ds, str):
                        ok = False
                        break
                    # Validate ISO date and preferred day for the channel
                    try:
                        d = datetime.strptime(ds, "%Y-%m-%d").date()
                    except Exception:
                        ok = False
                        break
                    if ch not in channel_info:
                        ok = False
                        break
                    if _weekday_abbrev(d) not in set(channel_info[ch]["preferred_days"]):
                        ok = False
                        break
                    reported_list.append((ch, ds))
                if ok:
                    if sorted(reported_list) != expected_unscheduled:
                        ok = False
            else:
                ok = False
            unscheduled_ok = ok
        except Exception:
            unscheduled_ok = False
    if unscheduled_ok:
        scores["unscheduled_slots_reported_correctly"] = 1.0

    # validation_report_missing_assets
    missing_assets_ok = False
    if validation_report_text is not None and isinstance(recipes, list):
        try:
            ok = True
            # For each missing asset path, ensure it is mentioned in the report
            for ap in missing_assets:
                if ap not in validation_report_text:
                    ok = False
                    break
            missing_assets_ok = ok
        except Exception:
            missing_assets_ok = False
    if missing_assets_ok:
        scores["validation_report_missing_assets"] = 1.0

    # validation_report_recent_exclusions
    recent_excl_ok = False
    if validation_report_text is not None and recent_exclusions:
        try:
            ok = True
            # Ensure both dish name and the date appears in the report
            for (cuisine, dish), d in recent_exclusions.items():
                if dish not in validation_report_text or d not in validation_report_text:
                    ok = False
                    break
            recent_excl_ok = ok
        except Exception:
            recent_excl_ok = False
    # If there are no recent exclusions detected from inputs, consider this check indeterminate; score 1 if no exclusions expected
    if recent_exclusions and recent_excl_ok:
        scores["validation_report_recent_exclusions"] = 1.0
    elif not recent_exclusions and validation_report_text is not None:
        # No exclusions expected, allow passing
        scores["validation_report_recent_exclusions"] = 1.0

    # validation_report_weekly_caps_note
    weekly_caps_note_ok = False
    if validation_report_text is not None:
        try:
            text_lower = validation_report_text.lower()
            # Look for confirmation phrase about weekly caps respected
            has_note = ("weekly" in text_lower and "cap" in text_lower and "respect" in text_lower)
            # Also ensure the plan itself respects caps (already checked)
            weekly_caps_note_ok = bool(has_note and pref_and_caps_ok)
        except Exception:
            weekly_caps_note_ok = False
    if weekly_caps_note_ok:
        scores["validation_report_weekly_caps_note"] = 1.0

    # fully_utilizes_valid_dishes_when_possible
    # If there are fewer valid dishes than total slot capacity, planner should schedule all valid dishes (without repeats)
    full_util_ok = False
    if isinstance(plan_rows, list):
        try:
            scheduled_unique_dishes = set((r.get("cuisine", "").strip(), r.get("dish_name", "").strip()) for r in plan_rows)
            # Filter out empty keys
            scheduled_unique_dishes = set(k for k in scheduled_unique_dishes if k[0] and k[1])
            if total_slot_capacity > 0 and len(valid_dishes) > 0 and len(valid_dishes) <= total_slot_capacity:
                # All valid dishes should be scheduled exactly once
                # Given cross-channel constraint (no repeat across channels), the count should equal number of valid dishes
                # Allow equality on sets (order doesn't matter)
                full_util_ok = (len(scheduled_unique_dishes) == len(valid_dishes)) and all(v in scheduled_unique_dishes for v in valid_dishes)
            else:
                # If there are more valid dishes than slots, cannot require full utilization; treat as pass if plan rows do not exceed slots and do not repeat dishes
                if total_slot_capacity >= 0:
                    full_util_ok = len(plan_rows) <= total_slot_capacity
                else:
                    full_util_ok = False
        except Exception:
            full_util_ok = False
    if full_util_ok:
        scores["fully_utilizes_valid_dishes_when_possible"] = 1.0

    return scores


def main() -> None:
        workspace = sys.argv[1] if len(sys.argv) > 1 else "."
        result = grade([], workspace)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()