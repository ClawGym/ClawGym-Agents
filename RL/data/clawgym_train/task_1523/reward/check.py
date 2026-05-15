import json
import sys
import csv
from pathlib import Path
from html.parser import HTMLParser
from datetime import datetime, date


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _parse_tsv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _parse_iso_z(dt_str: str):
    # Expect Zulu time like 2026-04-17T09:00:00Z
    try:
        return datetime.strptime(dt_str.strip(), "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        # attempt non-Z
        try:
            return datetime.fromisoformat(dt_str.strip())
        except Exception:
            return None


class BlogParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_article = False
        self.current_ing = None
        self.capture_p = False
        self.articles = {}  # lowercased ingredient -> first paragraph text
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "article":
            attr_dict = {k.lower(): v for k, v in attrs}
            ing = attr_dict.get("data-ingredient")
            if ing is not None:
                self.in_article = True
                self.current_ing = ing.strip().lower()
                self._buffer = []
        elif tag.lower() == "p" and self.in_article and self.current_ing is not None:
            # Only capture first <p>
            if self.current_ing not in self.articles:
                self.capture_p = True
                self._buffer = []

    def handle_endtag(self, tag):
        if tag.lower() == "article":
            self.in_article = False
            self.current_ing = None
            self.capture_p = False
            self._buffer = []
        elif tag.lower() == "p" and self.capture_p:
            text = "".join(self._buffer).strip()
            if self.current_ing is not None and self.current_ing not in self.articles:
                self.articles[self.current_ing] = " ".join(text.split())
            self.capture_p = False
            self._buffer = []

    def handle_data(self, data):
        if self.capture_p:
            self._buffer.append(data)


def _title_case(s: str) -> str:
    return s.strip().title()


def _trim(s: str) -> str:
    return s.strip()


def _is_number(val) -> bool:
    return isinstance(val, (int, float))


def _float_equal(a, b, eps=1e-9) -> bool:
    try:
        return abs(float(a) - float(b)) <= eps
    except Exception:
        return False


def _compute_expected_ingredients_summary(workspace: Path):
    crop_path = workspace / "input" / "crop_yields.csv"
    seed_path = workspace / "input" / "seed_varieties.json"
    blog_path = workspace / "input" / "heritage_blog.html"
    rows = _parse_csv_rows(crop_path)
    seeds = _safe_load_json(seed_path)
    blog_html = _safe_read_text(blog_path)
    if rows is None or seeds is None or not blog_html:
        return None

    # Parse blog to map ingredient(lower) -> first paragraph text
    parser = BlogParser()
    try:
        parser.feed(blog_html)
    except Exception:
        pass
    blog_map = parser.articles  # lower ingredient -> text

    # Deduplicate by (ingredient, variety) case-insensitive trimmed, keep most recent updated_at
    kept = {}
    for r in rows:
        ing = r.get("ingredient", "")
        var = r.get("variety", "")
        key = (_trim(ing).lower(), _trim(var).lower())
        updated = _parse_iso_z(r.get("updated_at", "") or "")
        if updated is None:
            # If updated_at malformed, treat as very old
            updated = datetime(1900, 1, 1)
        if key not in kept or updated > kept[key][0]:
            kept[key] = (updated, r)

    # Helper to find heritage note from seeds
    def get_seed_note(ingredient_title: str, variety_trim: str) -> str:
        # case-insensitive match on ingredient and variety
        try:
            for seed_ing, arr in seeds.items():
                if seed_ing.strip().lower() == ingredient_title.strip().lower():
                    if isinstance(arr, list):
                        for item in arr:
                            v = str(item.get("variety", ""))
                            note = str(item.get("heritage_note", ""))
                            if v.strip().lower() == variety_trim.strip().lower():
                                if note.strip():
                                    return " ".join(note.strip().split())
        except Exception:
            pass
        return ""

    results = []
    for (ing_lc, var_lc), (_upd, r) in kept.items():
        ing_raw = r.get("ingredient", "")
        var_raw = r.get("variety", "")
        ingredient_title = _title_case(ing_raw)
        variety_trim = _trim(var_raw)
        sow_date = _trim(r.get("sow_date", ""))
        harvest_start = _trim(r.get("harvest_start", ""))
        harvest_end = _trim(r.get("harvest_end", ""))
        y = r.get("yield_kg", "")
        try:
            y_num = int(y)
        except Exception:
            try:
                y_num = float(y)
            except Exception:
                # If cannot parse number, mark invalid by using None
                y_num = None

        # Heritage note selection
        note = get_seed_note(ingredient_title, variety_trim)
        if not note:
            # fallback to blog article first paragraph
            note = blog_map.get(ingredient_title.strip().lower(), "")
            if not isinstance(note, str):
                note = ""
        obj = {
            "ingredient": ingredient_title,
            "variety": variety_trim,
            "sow_date": sow_date,
            "harvest_window": [harvest_start, harvest_end],
            "latest_yield_kg": y_num,
            "heritage_note": note if isinstance(note, str) else "",
        }
        results.append(obj)

    # Sort by ingredient alphabetically
    results.sort(key=lambda x: x["ingredient"])
    return results


def _expected_weekly_stats(expected_summary):
    # Compute from expected summary list of dicts
    if expected_summary is None:
        return None
    # Count unique ingredient–variety pairs
    pair_count = len(expected_summary)
    # Sum latest_yield_kg
    total_yield = 0.0
    for obj in expected_summary:
        y = obj.get("latest_yield_kg")
        if isinstance(y, (int, float)):
            total_yield += float(y)
        else:
            # If missing numeric, treat as 0
            pass
    # Count overlapping harvest windows with 2026-04-19 to 2026-04-25 inclusive
    start_range = date.fromisoformat("2026-04-19")
    end_range = date.fromisoformat("2026-04-25")
    overlap_count = 0
    for obj in expected_summary:
        hw = obj.get("harvest_window", [])
        if isinstance(hw, list) and len(hw) == 2 and hw[0] and hw[1]:
            try:
                h_start = date.fromisoformat(hw[0])
                h_end = date.fromisoformat(hw[1])
                if h_start <= end_range and h_end >= start_range:
                    overlap_count += 1
            except Exception:
                # Skip malformed dates
                pass
    # Top 5 by latest_yield_kg desc; if tied, ingredient asc
    sorted_pairs = sorted(
        expected_summary,
        key=lambda o: (-float(o.get("latest_yield_kg") or 0.0), o.get("ingredient", "")),
    )
    top5 = []
    for o in sorted_pairs[:5]:
        top5.append(
            (
                o.get("ingredient", ""),
                o.get("variety", ""),
                float(o.get("latest_yield_kg") or 0.0),
            )
        )
    # Heritage spotlight: highest yield with non-empty heritage_note
    spotlight = None
    for o in sorted_pairs:
        note = o.get("heritage_note", "")
        if isinstance(note, str) and note.strip():
            spotlight = (o.get("ingredient", ""), o.get("variety", ""), note)
            break
    return {
        "pair_count": pair_count,
        "total_yield": total_yield,
        "overlap_count": overlap_count,
        "top5": top5,
        "spotlight": spotlight,
    }


def _find_line_index_for_row(lines, ingredient, variety, yield_value):
    # Find a line containing ingredient, variety and yield number (int or float) as substrings
    # Accept yield like '125' or '125.0'
    y_str_int = str(int(yield_value)) if abs(yield_value - int(yield_value)) < 1e-9 else None
    y_str_float = f"{yield_value}".rstrip("0").rstrip(".") if isinstance(yield_value, float) else None
    # Build possible yield representations
    y_candidates = set()
    if y_str_int is not None:
        y_candidates.add(y_str_int)
        y_candidates.add(y_str_int + ".0")
    if y_str_float is not None:
        y_candidates.add(y_str_float)
        # common prettier format
        try:
            y_candidates.add(f"{yield_value:.0f}")
        except Exception:
            pass
    # Always include canonical int repr
    y_candidates.add(str(int(round(yield_value))))
    for idx, line in enumerate(lines):
        l = line.strip()
        if ingredient in l and variety in l:
            for y_repr in y_candidates:
                # Ensure numeric token boundary (simple check)
                if y_repr in l:
                    return idx
    return -1


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "ingredients_summary_file_parses": 0.0,
        "ingredients_summary_content_matches": 0.0,
        "ingredients_summary_numeric_types": 0.0,
        "weekly_status_title_correct": 0.0,
        "weekly_status_overview_includes_required_stats": 0.0,
        "weekly_status_harvest_summary_top5": 0.0,
        "weekly_status_spotlight_correct": 0.0,
        "weekly_status_next_week_plan_bullets": 0.0,
        "community_post_word_limit": 0.0,
        "community_post_preserves_event_and_times": 0.0,
        "community_post_mentions_required_items": 0.0,
    }

    # Compute expected summary from inputs
    expected_summary = _compute_expected_ingredients_summary(workspace)
    expected_weekly = _expected_weekly_stats(expected_summary) if expected_summary is not None else None

    # 1) Validate output/ingredients_summary.json
    out_summary_path = workspace / "output" / "ingredients_summary.json"
    user_summary = _safe_load_json(out_summary_path)
    if isinstance(user_summary, list):
        scores["ingredients_summary_file_parses"] = 1.0
        # If we have expected, compare content strictly
        if expected_summary is not None:
            # Length check
            if len(user_summary) == len(expected_summary):
                # Compare each object field by field
                match_all = True
                numeric_types_ok = True
                for uo, eo in zip(user_summary, expected_summary):
                    # Must be dicts
                    if not isinstance(uo, dict):
                        match_all = False
                        break
                    # Expected keys
                    expected_keys = {"ingredient", "variety", "sow_date", "harvest_window", "latest_yield_kg", "heritage_note"}
                    if set(uo.keys()) != expected_keys:
                        match_all = False
                        break
                    # Check ingredient exact
                    if uo.get("ingredient") != eo.get("ingredient"):
                        match_all = False
                        break
                    # variety
                    if uo.get("variety") != eo.get("variety"):
                        match_all = False
                        break
                    # sow_date
                    if uo.get("sow_date") != eo.get("sow_date"):
                        match_all = False
                        break
                    # harvest_window
                    if uo.get("harvest_window") != eo.get("harvest_window"):
                        match_all = False
                        break
                    # latest_yield_kg numeric and value equality
                    ly = uo.get("latest_yield_kg")
                    if not _is_number(ly):
                        numeric_types_ok = False
                        match_all = False
                        break
                    if not _float_equal(ly, eo.get("latest_yield_kg") or 0.0):
                        match_all = False
                        break
                    # heritage_note exact
                    if (uo.get("heritage_note") or "") != (eo.get("heritage_note") or ""):
                        match_all = False
                        break
                if match_all:
                    scores["ingredients_summary_content_matches"] = 1.0
                if numeric_types_ok:
                    scores["ingredients_summary_numeric_types"] = 1.0
            else:
                # Length mismatch -> 0
                pass
        else:
            # Cannot compute expected summary due to missing inputs; only basic type checks
            # Verify entries look structurally correct and latest_yield_kg numeric
            struct_ok = True
            num_ok = True
            for obj in user_summary:
                if not isinstance(obj, dict):
                    struct_ok = False
                    break
                expected_keys = {"ingredient", "variety", "sow_date", "harvest_window", "latest_yield_kg", "heritage_note"}
                if set(obj.keys()) != expected_keys:
                    struct_ok = False
                    break
                if not isinstance(obj.get("harvest_window"), list) or len(obj.get("harvest_window")) != 2:
                    struct_ok = False
                    break
                if not _is_number(obj.get("latest_yield_kg")):
                    num_ok = False
                    struct_ok = False
                    break
            if struct_ok:
                scores["ingredients_summary_content_matches"] = 0.0  # cannot verify content without inputs
                scores["ingredients_summary_numeric_types"] = 1.0 if num_ok else 0.0
    else:
        # file missing or invalid
        pass

    # 2) Validate output/weekly_status.md
    weekly_path = workspace / "output" / "weekly_status.md"
    weekly_text = _safe_read_text(weekly_path)
    if weekly_text:
        lines = [ln.rstrip("\n") for ln in weekly_text.splitlines()]

        # Title check: must be exact
        expected_title = "Weekly Farm Status — Report Date: 2026-04-18"
        if lines and lines[0].strip() == expected_title:
            scores["weekly_status_title_correct"] = 1.0

        # Overview numbers: look within first 20 non-title lines for numbers and context
        overview_lines = []
        for ln in lines[1:]:
            if ln.strip():
                overview_lines.append(ln)
            # heuristically stop after encountering a "Spotlight:" heading or a table header line or a bullet list for next week
            if "Spotlight:" in ln or ("Ingredient" in ln and "Yield_kg" in ln) or ln.strip().startswith("- "):
                break
            if len(overview_lines) >= 12:
                break
        overview_text = " ".join(overview_lines)

        overview_ok = False
        if expected_weekly is not None:
            # Check pair count 9 near 'pair'
            pair_ok = ("pair" in overview_text.lower()) and (" " + str(expected_weekly["pair_count"]) + " " in " " + overview_text + " ")
            # Check total yield near 'yield' or 'kg'
            ty = int(round(expected_weekly["total_yield"]))
            total_ok = ((str(ty) in overview_text) and (("yield" in overview_text.lower()) or ("kg" in overview_text.lower())))
            # Check overlap count 2 with contextual words
            context_words = ["overlap", "overlapping", "harvest", "window", "next 7", "seven", "week", "2026-04-19", "2026-04-25"]
            overlap_num_present = (" " + str(expected_weekly["overlap_count"]) + " " in " " + overview_text + " ")
            overlap_ctx_present = any(w.lower() in overview_text.lower() for w in context_words)
            overlap_ok = overlap_num_present and overlap_ctx_present
            overview_ok = pair_ok and total_ok and overlap_ok
        else:
            # Without expected stats, we cannot strictly validate; require some indicative content
            overview_ok = bool(overview_text.strip())
        scores["weekly_status_overview_includes_required_stats"] = 1.0 if overview_ok else 0.0

        # Harvest Summary: ensure top 5 pairs appear in descending order with yields
        hs_ok = False
        if expected_weekly is not None:
            indices = []
            valid = True
            for ing, var, y in expected_weekly["top5"]:
                idx = _find_line_index_for_row(lines, ing, var, y)
                if idx < 0:
                    valid = False
                    break
                indices.append(idx)
            if valid and indices == sorted(indices):
                hs_ok = True
        scores["weekly_status_harvest_summary_top5"] = 1.0 if hs_ok else 0.0

        # Heritage Spotlight: check heading and note
        sp_ok = False
        if expected_weekly is not None and expected_weekly["spotlight"] is not None:
            sp_ing, sp_var, sp_note = expected_weekly["spotlight"]
            heading = f"Spotlight: {sp_ing} — {sp_var}"
            for i, ln in enumerate(lines):
                if ln.strip() == heading:
                    # Next line should be note verbatim
                    nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
                    if nxt == sp_note:
                        sp_ok = True
                    break
        scores["weekly_status_spotlight_correct"] = 1.0 if sp_ok else 0.0

        # Next Week Plan bullets
        bullets_ok = False
        expected_bullets = [
            "- 2026-04-19: Galway Co-op — Potatoes:40kg, Cabbage:10kg",
            "- 2026-04-25: Dunmore Saturday Market — Potatoes:30kg, Kale:8kg, Carrageen Moss:5kg",
        ]
        present = []
        for b in expected_bullets:
            found = any(b == ln.strip() for ln in lines)
            present.append(found)
        bullets_ok = all(present)
        scores["weekly_status_next_week_plan_bullets"] = 1.0 if bullets_ok else 0.0

    # 3) Validate output/community_post_rewrite.txt
    post_path = workspace / "output" / "community_post_rewrite.txt"
    post_text = _safe_read_text(post_path)
    if post_text:
        # word count <= 120
        words = [w for w in post_text.strip().split()]
        if len(words) <= 120:
            scores["community_post_word_limit"] = 1.0

        # preserve tokens: event name and dates/times
        tokens_ok = True
        required_tokens = [
            "Dunmore Saturday Market",
            "2026-05-02",
            "09:00 to 12:00",
            "10:30ish",
        ]
        for tok in required_tokens:
            if tok not in post_text:
                tokens_ok = False
                break
        scores["community_post_preserves_event_and_times"] = 1.0 if tokens_ok else 0.0

        # mentions "Home Guard new potatoes" and the "Carrageen Moss" pudding demo
        items_ok = True
        if "Home Guard new potatoes" not in post_text:
            items_ok = False
        # Require "Carrageen Moss" and both "pudding" and "demo" anywhere (to allow minor rephrasing)
        lower_post = post_text.lower()
        if ("Carrageen Moss" not in post_text) or ("pudding" not in lower_post) or ("demo" not in lower_post):
            items_ok = False
        scores["community_post_mentions_required_items"] = 1.0 if items_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()