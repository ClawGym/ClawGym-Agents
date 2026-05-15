import json
import re
import sys
from pathlib import Path


def read_text_safe(path: Path) -> tuple[str | None, Exception | None]:
    try:
        return path.read_text(encoding="utf-8", errors="strict"), None
    except Exception as e:
        return None, e


def load_json_safe(path: Path) -> tuple[dict | list | None, Exception | None]:
    text, err = read_text_safe(path)
    if err or text is None:
        return None, err
    try:
        return json.loads(text), None
    except Exception as e:
        return None, e


def is_iso_date(s: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s))


def count_words(text: str) -> int:
    tokens = re.findall(r"\b\w+\b", text)
    return len(tokens)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "baseline_log_exists_and_shows_failure": 0.0,
        "refactored_script_uses_html_parser_stdlib": 0.0,
        "episodes_json_schema_and_count": 0.0,
        "episodes_content_ep1_correct": 0.0,
        "episodes_content_ep2_correct": 0.0,
        "episodes_sorted_by_number": 0.0,
        "run_after_log_shows_success": 0.0,
        "review_md_present_and_concise": 0.0,
        "review_md_covers_points": 0.0,
    }

    # 1) Baseline log check
    run_before_path = workspace / "output" / "run_before.txt"
    rb_text, rb_err = read_text_safe(run_before_path)
    if rb_err is None and isinstance(rb_text, str):
        # Expect evidence of a failure from brittle regex:
        # Look for parsing attempt, traceback, and AttributeError markers.
        has_parsing_line = "Parsing input/pages/island_s01e01.html" in rb_text
        has_traceback = "Traceback" in rb_text
        has_attr_error = "AttributeError" in rb_text
        if has_parsing_line and has_traceback and has_attr_error:
            scores["baseline_log_exists_and_shows_failure"] = 1.0

    # 2) Refactored script uses stdlib HTML parser
    script_path = workspace / "scripts" / "extract_episodes.py"
    script_text, st_err = read_text_safe(script_path)
    if st_err is None and isinstance(script_text, str):
        # Check for html.parser/HTMLParser usage and stdlib-only hint
        uses_htmlparser = ("from html.parser import HTMLParser" in script_text) or ("html.parser" in script_text) or ("HTMLParser(" in script_text)
        # Keep CLI unchanged: check usage string and argv handling
        keeps_cli = ("Usage: extract_episodes.py <input_dir> <output_json>" in script_text) and ("sys.argv" in script_text)
        if uses_htmlparser and keeps_cli:
            scores["refactored_script_uses_html_parser_stdlib"] = 1.0

    # 3) episodes.json checks
    episodes_path = workspace / "output" / "episodes.json"
    data, ej_err = load_json_safe(episodes_path)
    schema_ok = False
    episodes = []
    if ej_err is None and isinstance(data, dict) and "episodes" in data and isinstance(data["episodes"], list):
        episodes = data["episodes"]
        # Expect exactly 2 episodes from provided inputs
        if len(episodes) == 2:
            # Validate fields and types for all
            required_fields = {
                "episode_number": int,
                "episode_title": str,
                "air_date": (str, type(None)),
                "contestants_eliminated": list,
                "standout_quote": (str, type(None)),
                "source_file": str,
            }
            all_ok = True
            for ep in episodes:
                if not isinstance(ep, dict):
                    all_ok = False
                    break
                for k, t in required_fields.items():
                    if k not in ep:
                        all_ok = False
                        break
                    # type check
                    if isinstance(t, tuple):
                        if not isinstance(ep[k], t):
                            all_ok = False
                            break
                    else:
                        if not isinstance(ep[k], t):
                            all_ok = False
                            break
                if not all_ok:
                    break
                # validate air_date format if present
                if ep["air_date"] is not None and not is_iso_date(ep["air_date"]):
                    all_ok = False
                    break
                # validate contestants_eliminated entries are strings
                if not all(isinstance(x, str) for x in ep["contestants_eliminated"]):
                    all_ok = False
                    break
            if all_ok:
                schema_ok = True
    if schema_ok:
        scores["episodes_json_schema_and_count"] = 1.0

    # 4) Content checks per episode
    # Build lookup by episode_number
    ep_map = {}
    for ep in episodes:
        num = ep.get("episode_number")
        ep_map.setdefault(num, []).append(ep)

    # Episode 1 expected
    ep1_ok = False
    if 1 in ep_map:
        for ep in ep_map[1]:
            title_ok = ep.get("episode_title") == "First Night Nerves"
            date_ok = ep.get("air_date") == "2020-01-05"
            quote_ok = ep.get("standout_quote") == "I didn't come here to make friends."
            elim_ok = ep.get("contestants_eliminated") == ["Dana"]
            src_ok = ep.get("source_file") == "island_s01e01.html"
            if title_ok and date_ok and quote_ok and elim_ok and src_ok:
                ep1_ok = True
                break
    if ep1_ok:
        scores["episodes_content_ep1_correct"] = 1.0

    # Episode 2 expected
    ep2_ok = False
    if 2 in ep_map:
        for ep in ep_map[2]:
            title_ok = ep.get("episode_title") == "Alliances Form"
            date_ok = ep.get("air_date") == "2020-01-12"
            quote_ok = ep.get("standout_quote") == "Trust is a currency."
            elim_ok = ep.get("contestants_eliminated") == []
            src_ok = ep.get("source_file") == "island_s01e02.html"
            if title_ok and date_ok and quote_ok and elim_ok and src_ok:
                ep2_ok = True
                break
    if ep2_ok:
        scores["episodes_content_ep2_correct"] = 1.0

    # 5) Sorting check
    sorted_ok = False
    if schema_ok and isinstance(episodes, list) and len(episodes) >= 2:
        # Check ascending by episode_number, then by source_file
        def key(ep):
            return (ep.get("episode_number"), ep.get("source_file"))
        sorted_expected = sorted(episodes, key=key)
        sorted_ok = episodes == sorted_expected
    if sorted_ok:
        scores["episodes_sorted_by_number"] = 1.0

    # 6) After-run log
    run_after_path = workspace / "output" / "run_after.txt"
    ra_text, ra_err = read_text_safe(run_after_path)
    if ra_err is None and isinstance(ra_text, str):
        has_parse1 = "Parsing input/pages/island_s01e01.html" in ra_text
        has_parse2 = "Parsing input/pages/island_s01e02.html" in ra_text
        wrote = "Wrote output/episodes.json" in ra_text
        no_traceback = "Traceback" not in ra_text
        if has_parse1 and has_parse2 and wrote and no_traceback:
            scores["run_after_log_shows_success"] = 1.0

    # 7) REVIEW.md checks
    review_path = workspace / "output" / "REVIEW.md"
    review_text, rv_err = read_text_safe(review_path)
    if rv_err is None and isinstance(review_text, str):
        # concise: <= 300 words
        if count_words(review_text) <= 300 and len(review_text.strip()) > 0:
            scores["review_md_present_and_concise"] = 1.0
        # coverage: mention baseline failure, refactor decision, and extraction notes
        mentions_failure = ("AttributeError" in review_text) or ("Traceback" in review_text) or ("NoneType" in review_text) or ("baseline" in review_text)
        mentions_regex = ("regex" in review_text.lower()) or ("regular expression" in review_text.lower())
        mentions_parser = ("html.parser" in review_text.lower()) or ("htmlparser" in review_text.lower()) or ("html parser" in review_text.lower()) or ("HTMLParser" in review_text)
        mentions_fields = any(k in review_text for k in ["Air date", "air date", "time", "Standout quote", "standout quote", "Eliminations", "eliminations", "None"])
        if mentions_failure and mentions_regex and mentions_parser and mentions_fields:
            scores["review_md_covers_points"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()