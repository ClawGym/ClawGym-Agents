import json
import csv
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            # Ensure header exists
            if reader.fieldnames is None:
                return None
            return [row for row in reader]
    except Exception:
        return None


def _normalize_writers(value: str) -> str:
    # Normalize semicolon-separated writers: trim spaces around each, single space after semicolon
    parts = [p.strip() for p in value.split(";")]
    # Remove empty parts due to malformed input
    parts = [p for p in parts if p]
    return "; ".join(parts)


class EpisodeGuideParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_episode_div = False
        self.current_episode: Dict[str, any] = {}
        self.current_li_text = ""
        self.in_li = False
        self.in_h2 = False
        self.h2_text = ""
        self.episodes: List[Dict[str, any]] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "div" and ("class" in attrs_dict and "episode" in attrs_dict["class"].split()):
            self.in_episode_div = True
            self.current_episode = {}
            # data-season and data-episode present
            ds = attrs_dict.get("data-season")
            de = attrs_dict.get("data-episode")
            if ds is not None:
                try:
                    self.current_episode["season"] = int(ds)
                except Exception:
                    self.current_episode["season"] = None
            else:
                self.current_episode["season"] = None
            if de is not None:
                try:
                    self.current_episode["episode_number"] = int(de)
                except Exception:
                    self.current_episode["episode_number"] = None
            else:
                self.current_episode["episode_number"] = None
        elif self.in_episode_div and tag == "h2":
            self.in_h2 = True
            self.h2_text = ""
        elif self.in_episode_div and tag == "li":
            self.in_li = True
            self.current_li_text = ""

    def handle_endtag(self, tag):
        if self.in_episode_div and tag == "h2":
            self.in_h2 = False
            # Parse title from h2 text: e.g., "Episode 1 — Something About Detroit"
            # We'll split on em dash or hyphen dash
            text = self.h2_text.strip()
            # Try to extract title after the dash
            title = None
            if "—" in text:
                title = text.split("—", 1)[1].strip()
            elif "-" in text:
                # Use hyphen surrounded by spaces if present
                parts = text.split("-", 1)
                if len(parts) == 2:
                    title = parts[1].strip()
            if title is None:
                # Fallback: whole text if parsing fails
                title = text
            self.current_episode["title"] = title
        elif self.in_episode_div and tag == "li":
            self.in_li = False
            li = self.current_li_text.strip()
            # Parse list items for fields
            low = li.lower()
            if low.startswith("air date:"):
                self.current_episode["air_date"] = li.split(":", 1)[1].strip()
            elif low.startswith("writer(s):"):
                writers = li.split(":", 1)[1].strip()
                self.current_episode["writers"] = _normalize_writers(writers)
            elif low.startswith("director:"):
                director = li.split(":", 1)[1].strip()
                self.current_episode["director"] = director
            elif low.startswith("runtime:"):
                runtime_str = li.split(":", 1)[1].strip()
                # Expect format "NN min"
                m = re.search(r"(\d+)", runtime_str)
                if m:
                    try:
                        self.current_episode["runtime_minutes"] = int(m.group(1))
                    except Exception:
                        self.current_episode["runtime_minutes"] = None
                else:
                    self.current_episode["runtime_minutes"] = None
        elif tag == "div" and self.in_episode_div:
            # Finish episode div
            self.in_episode_div = False
            # Ensure writers normalized even if missing
            if "writers" in self.current_episode and isinstance(self.current_episode["writers"], str):
                self.current_episode["writers"] = _normalize_writers(self.current_episode["writers"])
            self.episodes.append(self.current_episode)
            self.current_episode = {}

    def handle_data(self, data):
        if self.in_h2:
            self.h2_text += data
        elif self.in_li:
            self.current_li_text += data


def _parse_episode_guide(html_text: str, source_basename: str) -> List[Dict[str, any]]:
    parser = EpisodeGuideParser()
    parser.feed(html_text)
    results: List[Dict[str, any]] = []
    for ep in parser.episodes:
        # Add source_file
        item = {
            "season": ep.get("season"),
            "episode_number": ep.get("episode_number"),
            "title": ep.get("title"),
            "air_date": ep.get("air_date"),
            "writers": _normalize_writers(ep.get("writers") or ""),
            "director": ep.get("director"),
            "runtime_minutes": ep.get("runtime_minutes"),
            "source_file": source_basename,
        }
        results.append(item)
    return results


def _find_source_html_path(workspace: Path) -> Optional[Path]:
    # Prefer processed path, then incoming
    processed = workspace / "input" / "processed" / "justified_city_primeval_s1_guide.html"
    incoming = workspace / "input" / "incoming" / "justified_city_primeval_s1_guide.html"
    if processed.exists():
        return processed
    if incoming.exists():
        return incoming
    return None


def _load_expected_from_html(workspace: Path) -> Optional[List[Dict[str, any]]]:
    src = _find_source_html_path(workspace)
    if not src:
        return None
    html = _safe_read_text(src)
    if html is None:
        return None
    return _parse_episode_guide(html, source_basename=src.name)


def _canonicalize_csv_rows(rows: List[Dict[str, str]]) -> Tuple[Optional[List[Dict[str, any]]], Optional[str]]:
    """
    Convert CSV dicts to canonical types. Returns (rows, error) where error is None if ok.
    """
    out = []
    for i, r in enumerate(rows):
        try:
            season = int(str(r.get("season", "")).strip())
            episode_number = int(str(r.get("episode_number", "")).strip())
            title = (r.get("title") or "").strip()
            air_date = (r.get("air_date") or "").strip()
            # Validate air_date format
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", air_date):
                return None, f"Row {i+1}: invalid air_date format"
            writers = _normalize_writers((r.get("writers") or "").strip())
            director = (r.get("director") or "").strip()
            runtime_minutes = int(str(r.get("runtime_minutes", "")).strip())
            source_file = (r.get("source_file") or "").strip()
            out.append({
                "season": season,
                "episode_number": episode_number,
                "title": title,
                "air_date": air_date,
                "writers": writers,
                "director": director,
                "runtime_minutes": runtime_minutes,
                "source_file": source_file,
            })
        except Exception as e:
            return None, f"Row {i+1}: {e}"
    return out, None


def _compare_extraction(expected: List[Dict[str, any]], actual: List[Dict[str, any]]) -> Tuple[bool, str]:
    # Ensure same number of rows
    if len(expected) != len(actual):
        return False, f"Row count mismatch: expected {len(expected)} got {len(actual)}"
    # Index by episode_number
    exp_map = {e["episode_number"]: e for e in expected}
    act_map = {e["episode_number"]: e for e in actual}
    if set(exp_map.keys()) != set(act_map.keys()):
        return False, "Episode numbers mismatch"
    # Compare all fields strictly
    for ep_no in sorted(exp_map.keys()):
        e = exp_map[ep_no]
        a = act_map[ep_no]
        for key in ["season", "episode_number", "title", "air_date", "writers", "director", "runtime_minutes", "source_file"]:
            ev = e.get(key)
            av = a.get(key)
            # Normalize writers
            if key == "writers":
                ev = _normalize_writers(str(ev))
                av = _normalize_writers(str(av))
            if ev != av:
                return False, f"Mismatch ep {ep_no} field {key}: expected {ev!r} got {av!r}"
    return True, "match"


def _check_validation_report_minimum(report: dict) -> Dict[str, bool]:
    checks = report.get("checks")
    found = {
        "csv_exists_readable": False,
        "columns_present": False,
        "episode_count_matches_expected": False,
        "runtime_integers": False,
    }
    if not isinstance(checks, list):
        return found
    for item in checks:
        name = str(item.get("name", "")).lower()
        # Exists/readable
        if ("csv" in name) and (("exist" in name) or ("exists" in name) or ("read" in name) or ("readable" in name)):
            found["csv_exists_readable"] = True
        # Columns present
        if "column" in name:
            found["columns_present"] = True
        # Count equals expected
        if (("count" in name) or ("number" in name)) and ("episode" in name) and (("expect" in name) or ("expected" in name) or ("metadata" in name)):
            found["episode_count_matches_expected"] = True
        # Runtime ints
        if ("runtime" in name) and (("int" in name) or ("integer" in name)):
            found["runtime_integers"] = True
    return found


def _find_files_with_content(root: Path, exts: Tuple[str, ...], substrings: List[str], max_files: int = 500) -> List[Path]:
    results: List[Path] = []
    count = 0
    for p in root.rglob("*"):
        if count >= max_files:
            break
        if p.is_file() and p.suffix in exts:
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if all(sub in text for sub in substrings):
                results.append(p)
            count += 1
    return results


def _find_processor_script(workspace: Path) -> bool:
    # Evidence of a watcher/processor script runnable from root:
    # Search for .py or .sh files that reference both input/incoming and output/episodes
    candidates = _find_files_with_content(workspace, (".py", ".sh", ".cmd", ".bat"), ["input/incoming", "output/episodes"])
    # Exclude this grader file if present
    return len(candidates) > 0


def _find_validation_command_evidence(workspace: Path) -> bool:
    # Evidence of a separate validation command/script: search for files that mention output/validation and report.json
    candidates = _find_files_with_content(workspace, (".py", ".sh", ".cmd", ".bat"), ["output/validation", "report.json"])
    if candidates:
        return True
    # Alternatively, file with "validate" in filename
    for p in workspace.rglob("*"):
        name = p.name.lower()
        if p.is_file() and (name.startswith("validate") or "validate" in name) and p.suffix in (".py", ".sh", ".cmd", ".bat"):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "episodes_csv_exists_readable": 0.0,
        "episodes_csv_required_columns_present": 0.0,
        "episodes_extraction_matches_html": 0.0,
        "episode_count_matches_metadata": 0.0,
        "validation_report_exists_and_schema": 0.0,
        "validation_report_minimum_checks_present": 0.0,
        "email_generated_conditionally": 0.0,
        "email_content_correct": 0.0,
        "log_line_appended": 0.0,
        "processed_html_moved": 0.0,
        "source_file_field_correct": 0.0,
        "watcher_script_present": 0.0,
        "validation_via_command_evidence": 0.0,
    }

    # Paths
    csv_path = workspace / "output" / "episodes" / "justified_city_primeval_s1.csv"
    report_path = workspace / "output" / "validation" / "report.json"
    email_path = workspace / "output" / "email" / "justified_city_primeval_s1_update.md"
    log_path = workspace / "output" / "logs" / "run.log"
    processed_html = workspace / "input" / "processed" / "justified_city_primeval_s1_guide.html"
    meta_path = workspace / "input" / "reference" / "series_metadata.json"

    # Load CSV
    rows_raw = _safe_read_csv_dicts(csv_path)
    if rows_raw is not None:
        scores["episodes_csv_exists_readable"] = 1.0
    else:
        rows_raw = None

    required_columns = {"season", "episode_number", "title", "air_date", "writers", "director", "runtime_minutes", "source_file"}
    if rows_raw is not None:
        columns = set(rows_raw[0].keys()) if rows_raw else set()
        if required_columns.issubset(columns):
            scores["episodes_csv_required_columns_present"] = 1.0

    # Canonicalize CSV rows
    rows_canon: Optional[List[Dict[str, any]]] = None
    canonicalize_error = None
    if rows_raw is not None:
        rows_canon, canonicalize_error = _canonicalize_csv_rows(rows_raw)

    # Expected from HTML
    expected = _load_expected_from_html(workspace)

    # Compare extraction with HTML
    if rows_canon is not None and expected is not None:
        ok, msg = _compare_extraction(expected, rows_canon)
        if ok:
            scores["episodes_extraction_matches_html"] = 1.0

    # Episode count matches metadata
    meta = _safe_load_json(meta_path)
    if meta is not None and isinstance(meta.get("expected_episode_count"), int) and rows_raw is not None:
        exp_count = int(meta["expected_episode_count"])
        if len(rows_raw) == exp_count:
            scores["episode_count_matches_metadata"] = 1.0

    # Validation report schema
    report = _safe_load_json(report_path)
    if report is not None and isinstance(report, dict):
        has_passed = isinstance(report.get("passed"), bool)
        has_checks = isinstance(report.get("checks"), list)
        has_total = isinstance(report.get("total_episodes"), int)
        if has_passed and has_checks and has_total:
            scores["validation_report_exists_and_schema"] = 1.0

    # Validation report minimum checks present
    if report is not None and isinstance(report, dict):
        found = _check_validation_report_minimum(report)
        if all(found.values()):
            scores["validation_report_minimum_checks_present"] = 1.0

    # Email generated conditionally
    # If report passed True -> email must exist; if False -> email must NOT exist
    if report is not None and isinstance(report.get("passed"), bool):
        passed = report["passed"]
        if passed and email_path.exists():
            scores["email_generated_conditionally"] = 1.0
        elif (not passed) and (not email_path.exists()):
            scores["email_generated_conditionally"] = 1.0

    # Email content correctness (only if email exists and validation passed)
    if email_path.exists() and report is not None and report.get("passed") is True and rows_canon is not None and meta is not None:
        content = _safe_read_text(email_path) or ""
        # Subject line exact match per template
        series_title = meta.get("series_title")
        season = meta.get("season")
        if isinstance(series_title, str) and isinstance(season, int):
            expected_subject = f"Subject: Seminar update — {series_title} S{season} data processed"
            # Validate placeholder substitution: no {{...}} remaining
            no_placeholders = ("{{" not in content) and ("}}" not in content)
            subject_ok = expected_subject in content
            # Validate episode_count substitution line
            episode_count = len(rows_canon)
            expected_line = f"The latest episode guide for {series_title} Season {season} has been processed. {episode_count} episode(s) are included."
            ep_count_ok = expected_line in content
            # Validate bullets
            # Build expected bullets from CSV rows sorted by episode_number
            ok_bullets = True
            rows_sorted = sorted(rows_canon, key=lambda r: r["episode_number"])
            lines = [ln.strip() for ln in content.splitlines()]
            for r in rows_sorted:
                # Accept either em dash or hyphen
                bullet_core_em = f"S{r['season']}E{r['episode_number']}: {r['title']} — {r['air_date']}; Writers: {_normalize_writers(r['writers'])}; Director: {r['director']}; Runtime: {r['runtime_minutes']} min"
                bullet_core_hy = f"S{r['season']}E{r['episode_number']}: {r['title']} - {r['air_date']}; Writers: {_normalize_writers(r['writers'])}; Director: {r['director']}; Runtime: {r['runtime_minutes']} min"
                # Each bullet should be listed, possibly prefixed by "-" or "*"
                candidates = [f"- {bullet_core_em}", f"* {bullet_core_em}", f"- {bullet_core_hy}", f"* {bullet_core_hy}"]
                if not any(cand in lines for cand in candidates):
                    ok_bullets = False
                    break
            if subject_ok and no_placeholders and ep_count_ok and ok_bullets:
                scores["email_content_correct"] = 1.0

    # Log line appended
    if log_path.exists():
        log_text = _safe_read_text(log_path) or ""
        # Find the last line containing the input filename
        basename = "justified_city_primeval_s1_guide.html"
        lines = [ln.strip() for ln in log_text.strip().splitlines() if ln.strip()]
        relevant_lines = [ln for ln in lines if basename in ln]
        if relevant_lines:
            last = relevant_lines[-1]
            # Must contain 'pass' or 'fail' substring
            status_ok = ("pass" in last.lower()) or ("fail" in last.lower())
            # Must contain episode count number (from CSV if available, else from metadata)
            expected_count = None
            if rows_raw is not None:
                expected_count = len(rows_raw)
            elif isinstance(meta, dict) and isinstance(meta.get("expected_episode_count"), int):
                expected_count = int(meta["expected_episode_count"])
            count_ok = True
            if expected_count is not None:
                count_ok = re.search(rf"\b{expected_count}\b", last) is not None
            # Timestamp presence at start (loosely match YYYY-MM-DD)
            ts_ok = re.match(r"\d{4}-\d{2}-\d{2}", last) is not None
            if status_ok and count_ok and ts_ok:
                scores["log_line_appended"] = 1.0

    # Processed HTML moved
    if processed_html.exists():
        scores["processed_html_moved"] = 1.0

    # source_file field correct
    if rows_canon is not None:
        all_source_ok = all(row.get("source_file") == "justified_city_primeval_s1_guide.html" for row in rows_canon)
        if all_source_ok:
            scores["source_file_field_correct"] = 1.0

    # Watcher/processor script presence
    if _find_processor_script(workspace):
        scores["watcher_script_present"] = 1.0

    # Validation via command evidence
    if _find_validation_command_evidence(workspace):
        scores["validation_via_command_evidence"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()