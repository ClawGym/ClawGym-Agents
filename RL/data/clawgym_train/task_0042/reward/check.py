import json
import re
import sys
from pathlib import Path
from html.parser import HTMLParser


def _read_text_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_file(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _validate_date_yyyy_mm_dd(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return False
    try:
        year, month, day = map(int, s.split("-"))
        if not (1 <= month <= 12):
            return False
        if not (1 <= day <= 31):
            return False
    except Exception:
        return False
    return True


class _GigsHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.gigs: list[dict] = []
        self._in_gig = False
        self._gig_div_depth = 0
        self._current: dict | None = None
        self._current_field: str | None = None
        self._in_songs_ul = False
        self._songs_ul_depth = 0

    @staticmethod
    def _class_contains(attrs: dict, cls: str) -> bool:
        classes = attrs.get("class", "")
        if isinstance(classes, list):
            return cls in classes
        return cls in str(classes).split()

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "div" and self._class_contains(attrs_dict, "gig"):
            self._in_gig = True
            self._gig_div_depth = 1
            self._current = {"date": "", "venue": "", "city": "", "songs_count": 0}
            self._current_field = None
            self._in_songs_ul = False
            self._songs_ul_depth = 0
            return
        if self._in_gig and tag == "div":
            self._gig_div_depth += 1

        if self._in_gig and tag == "span":
            if self._class_contains(attrs_dict, "date"):
                self._current_field = "date"
            elif self._class_contains(attrs_dict, "venue"):
                self._current_field = "venue"
            elif self._class_contains(attrs_dict, "city"):
                self._current_field = "city"

        if self._in_gig and tag == "ul" and self._class_contains(attrs_dict, "songs"):
            self._in_songs_ul = True
            self._songs_ul_depth = 1
        elif self._in_songs_ul and tag == "ul":
            self._songs_ul_depth += 1

        if self._in_songs_ul and tag == "li" and self._current is not None:
            self._current["songs_count"] += 1

    def handle_endtag(self, tag):
        if self._in_gig and tag == "span":
            self._current_field = None

        if self._in_songs_ul and tag == "ul":
            self._songs_ul_depth -= 1
            if self._songs_ul_depth <= 0:
                self._in_songs_ul = False

        if self._in_gig and tag == "div":
            self._gig_div_depth -= 1
            if self._gig_div_depth <= 0:
                if self._current is not None:
                    for k in ("date", "venue", "city"):
                        if isinstance(self._current.get(k), str):
                            self._current[k] = self._current[k].strip()
                    self.gigs.append(self._current)
                self._in_gig = False
                self._current = None
                self._current_field = None
                self._in_songs_ul = False
                self._songs_ul_depth = 0

    def handle_data(self, data):
        if self._in_gig and self._current_field and self._current is not None:
            existing = self._current.get(self._current_field, "")
            if not isinstance(existing, str):
                existing = ""
            self._current[self._current_field] = existing + data


def _parse_gigs_html(path: Path) -> list[dict] | None:
    text = _read_text_file(path)
    if text is None:
        return None
    parser = _GigsHTMLParser()
    try:
        parser.feed(text)
        parser.close()
        return parser.gigs
    except Exception:
        return None


def _normalize_gigs_list(gigs: list[dict]) -> list[tuple]:
    norm = []
    for g in gigs:
        date = g.get("date", "")
        venue = g.get("venue", "")
        city = g.get("city", "")
        songs_count = g.get("songs_count", None)
        if not isinstance(date, str) or not isinstance(venue, str) or not isinstance(city, str):
            return []
        if not isinstance(songs_count, int):
            return []
        norm.append((date.strip(), venue.strip(), city.strip(), songs_count))
    # Sort for deterministic comparison ignoring original ordering
    return sorted(norm)


def _parse_env_file(path: Path) -> dict:
    env = {}
    text = _read_text_file(path)
    if text is None:
        return env
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "gigs_json_exists_and_valid": 0.0,
        "gigs_json_matches_html": 0.0,
        "sample_output_shape_and_matches_gigs_json": 0.0,
        "tests_results_all_passed": 0.0,
        "logs_show_startup_and_successful_request": 0.0,
        "env_file_configured_for_container": 0.0,
    }

    html_path = workspace / "data" / "gigs.html"
    gigs_json_path = workspace / "data" / "gigs.json"
    sample_output_path = workspace / "outputs" / "gigs_sample.json"
    test_results_path = workspace / "reports" / "test_results.txt"
    logs_path = workspace / "logs" / "service.log"
    env_path = workspace / ".env"

    # Parse HTML source
    html_gigs = _parse_gigs_html(html_path)

    # Validate gigs.json
    gigs_json = _load_json_file(gigs_json_path)
    valid_gigs_json = True
    if isinstance(gigs_json, list):
        for item in gigs_json:
            if not isinstance(item, dict):
                valid_gigs_json = False
                break
            required = {"date", "venue", "city", "songs_count"}
            if not required.issubset(item.keys()):
                valid_gigs_json = False
                break
            if not _validate_date_yyyy_mm_dd(item.get("date")):
                valid_gigs_json = False
                break
            if not isinstance(item.get("venue"), str) or not isinstance(item.get("city"), str):
                valid_gigs_json = False
                break
            if not isinstance(item.get("songs_count"), int) or item.get("songs_count") < 0:
                valid_gigs_json = False
                break
    else:
        valid_gigs_json = False

    if valid_gigs_json:
        scores["gigs_json_exists_and_valid"] = 1.0

    # Compare gigs.json to HTML extraction (content-level, order-insensitive)
    if html_gigs is not None and valid_gigs_json:
        html_norm = _normalize_gigs_list(html_gigs)
        json_norm = _normalize_gigs_list(gigs_json) if isinstance(gigs_json, list) else []
        if html_norm and json_norm and len(html_norm) == len(json_norm):
            # Also ensure counts equality and total songs_count equality
            if html_norm == json_norm:
                scores["gigs_json_matches_html"] = 1.0

    # Validate sample output file
    sample = _load_json_file(sample_output_path)
    sample_ok = False
    if isinstance(sample, dict):
        count = sample.get("count")
        gigs_list = sample.get("gigs")
        if isinstance(count, int) and isinstance(gigs_list, list) and count == len(gigs_list):
            # Ensure gigs_list has required fields and types
            required = {"date", "venue", "city", "songs_count"}
            types_ok = True
            for it in gigs_list:
                if not isinstance(it, dict) or not required.issubset(it.keys()):
                    types_ok = False
                    break
                if not isinstance(it.get("songs_count"), int):
                    types_ok = False
                    break
                if not _validate_date_yyyy_mm_dd(it.get("date")):
                    types_ok = False
                    break
            if types_ok and isinstance(gigs_json, list):
                # Compare content with gigs.json, order-insensitive
                json_norm = _normalize_gigs_list(gigs_json)
                sample_norm = _normalize_gigs_list(gigs_list)
                if json_norm and sample_norm and json_norm == sample_norm:
                    sample_ok = True
    if sample_ok:
        scores["sample_output_shape_and_matches_gigs_json"] = 1.0

    # Parse test results
    test_text = _read_text_file(test_results_path)
    if isinstance(test_text, str):
        lowered = test_text.lower()
        # Expect exactly 2 passed (based on provided tests)
        passed_pattern = re.search(r"\b2\s+passed\b", lowered)
        no_fail = ("failed" not in lowered) and ("error" not in lowered)
        if passed_pattern and no_fail:
            scores["tests_results_all_passed"] = 1.0

    # Logs: startup and first successful /gigs request
    logs_text = _read_text_file(logs_path)
    if isinstance(logs_text, str):
        has_startup = any(
            s in logs_text
            for s in (
                "Uvicorn running on",
                "Application startup complete",
                "Started server process",
            )
        )
        has_success_req = False
        for line in logs_text.splitlines():
            l = line.strip()
            # Typical uvicorn access log includes path and status code 200
            if "/gigs" in l and (" 200 " in l or l.endswith(" 200") or " 200 OK" in l or '" 200' in l):
                has_success_req = True
                break
        if has_startup and has_success_req:
            scores["logs_show_startup_and_successful_request"] = 1.0

    # .env configuration for container to find gigs json
    env = _parse_env_file(env_path)
    gigs_file_env = env.get("GIGS_FILE")
    if isinstance(gigs_file_env, str) and gigs_file_env.strip() == "/data/gigs.json":
        scores["env_file_configured_for_container"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()