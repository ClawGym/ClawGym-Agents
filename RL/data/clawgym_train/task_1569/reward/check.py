import json
import csv
import re
import sys
import unicodedata
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_simple_yaml_lists(path: Path) -> Optional[Dict[str, List[str]]]:
    """
    Parse a very small subset of YAML sufficient for:
    key:
      - value
      - value2
    and
    key: []
    Returns dict of key -> list of strings. Returns None on failure.
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    result: Dict[str, List[str]] = {}
    current_key: Optional[str] = None
    in_list = False
    try:
        for raw_line in lines:
            line = raw_line.rstrip("\n")
            if not line.strip():
                continue
            if not line.startswith(" ") and ":" in line:
                key, rest = line.split(":", 1)
                key = key.strip()
                rest = rest.strip()
                current_key = key
                if rest == "[]":
                    result[current_key] = []
                    in_list = False
                elif rest == "":
                    result[current_key] = []
                    in_list = True
                else:
                    return None
                continue
            if in_list and current_key is not None:
                stripped = line.lstrip()
                if stripped.startswith("- "):
                    value = stripped[2:].strip()
                    result[current_key].append(value)
                else:
                    return None
        return result
    except Exception:
        return None


def _strip_accents_lower(s: str) -> str:
    if s is None:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    only_ascii = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return only_ascii.lower()


def _parse_roster_csv(path: Path) -> Optional[Dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            # Strict header expectation
            expected_headers = ["name", "pseudonym"]
            if [h.strip() for h in reader.fieldnames] != expected_headers:
                return None
            mapping: Dict[str, str] = {}
            for row in reader:
                if "name" not in row or "pseudonym" not in row:
                    return None
                name = row["name"]
                pseudonym = row["pseudonym"]
                if name is None or pseudonym is None:
                    return None
                key = _strip_accents_lower(name.strip())
                mapping[key] = pseudonym.strip()
            return mapping
    except Exception:
        return None


def _find_note_files(base: Path) -> List[Path]:
    notes_dir = base / "input" / "notes"
    if not notes_dir.exists():
        return []
    files = sorted([p for p in notes_dir.rglob("*.md") if p.is_file()])
    return files


def _parse_storyteller(raw: str, ignore_terms: List[str]) -> str:
    s = raw
    s = re.sub(r"\([^)]*\)", "", s)
    s = s.strip()
    # Remove trailing clan/affiliation terms and dangling connector "of"
    for term in ignore_terms:
        term = term.strip()
        if not term:
            continue
        if s.endswith(term):
            s = s[: len(s) - len(term)].rstrip()
            # Remove trailing connector like "of" if left dangling
            s = re.sub(r"\bof$", "", s, flags=re.IGNORECASE).rstrip()
            break
    s = s.strip()
    return s


def _extract_stories_and_quotes(notes_files: List[Path], ignore_terms: List[str]) -> Tuple[List[Dict], List[Dict]]:
    stories: List[Dict] = []
    quotes: List[Dict] = []
    for nf in notes_files:
        text = _read_text(nf)
        if text is None:
            continue
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            heading = None
            title = None
            if line.startswith("### Story:"):
                heading = "Story"
                title = line.split("### Story:", 1)[1].strip()
            elif line.startswith("### Origin Story:"):
                heading = "Origin Story"
                title = line.split("### Origin Story:", 1)[1].strip()
            if heading is not None:
                if i + 1 < len(lines) and lines[i + 1].lstrip().startswith("Storyteller:"):
                    storyteller_line = lines[i + 1].lstrip()
                    storyteller_raw = storyteller_line.split("Storyteller:", 1)[1].strip()
                    storyteller_name = _parse_storyteller(storyteller_raw, ignore_terms)
                    body_start = i + 2
                    body_end = body_start
                    for j in range(body_start, len(lines)):
                        if lines[j].startswith("### "):
                            body_end = j
                            break
                    else:
                        body_end = len(lines)
                    body_lines = lines[body_start:body_end]
                    story_quotes: List[str] = []
                    for bl in body_lines:
                        for m in re.finditer(r'"([^"]+)"', bl):
                            story_quotes.append(m.group(1))
                    story = {
                        "note_file": nf.as_posix(),
                        "story_title": title,
                        "storyteller_name": storyteller_name,
                        "quotes": story_quotes,
                    }
                    stories.append(story)
                    for qt in story_quotes:
                        quotes.append({
                            "note_file": nf.as_posix(),
                            "story_title": title,
                            "storyteller_name": storyteller_name,
                            "quote_text": qt,
                        })
                    i = body_end
                    continue
            i += 1
    return stories, quotes


def _compute_expected(workspace: Path) -> Optional[Dict]:
    config_path = workspace / "config" / "anonymizer.yaml"
    config = _parse_simple_yaml_lists(config_path)
    if config is None:
        return None
    ignore_terms = config.get("ignore_clan_terms", [])
    roster_path = workspace / "input" / "roster.csv"
    roster = _parse_roster_csv(roster_path)
    if roster is None:
        return None
    notes_files = _find_note_files(workspace)
    stories, quotes = _extract_stories_and_quotes(notes_files, ignore_terms)
    expected_story_rows: List[Tuple[str, str, str, int]] = []
    expected_quotes_rows: List[Tuple[str, str, str, str]] = []
    pending_names_set = set()

    for story in stories:
        name_canonical = story["storyteller_name"]
        name_key = _strip_accents_lower(name_canonical)
        pseudonym = roster.get(name_key)
        if pseudonym is None:
            pseudonym = "PENDING"
            if name_canonical:
                pending_names_set.add(name_canonical)
        expected_story_rows.append((
            story["note_file"],
            story["story_title"],
            pseudonym,
            len(story["quotes"]),
        ))
        for qt in story["quotes"]:
            expected_quotes_rows.append((
                story["note_file"],
                story["story_title"],
                pseudonym,
                qt,
            ))
    pending_names_sorted = sorted(pending_names_set, key=lambda x: x.lower())
    return {
        "ignore_terms": ignore_terms,
        "expected_story_rows": expected_story_rows,
        "expected_quotes_rows": expected_quotes_rows,
        "expected_pending_names": pending_names_sorted,
        "total_stories": len(stories),
        "total_quotes": len(expected_quotes_rows),
    }


def _read_csv_rows(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            headers = [h for h in reader.fieldnames]
            rows = [row for row in reader]
            return headers, rows
    except Exception:
        return None


def _read_jsonl(path: Path) -> Optional[List[Dict]]:
    try:
        items: List[Dict] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                obj = json.loads(s)
                if not isinstance(obj, dict):
                    return None
                items.append(obj)
        return items
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "story_index_file_and_schema": 0.0,
        "story_index_content_correct": 0.0,
        "quotes_jsonl_file_and_schema": 0.0,
        "quotes_jsonl_content_correct": 0.0,
        "yaml_pending_names_updated": 0.0,
        "yaml_ignore_clan_terms_intact": 0.0,
        "yaml_only_expected_keys": 0.0,
        "email_headers_correct": 0.0,
        "email_body_includes_stats": 0.0,
        "email_body_lists_pending_names": 0.0,
        "email_body_mentions_paths": 0.0,
        "email_body_coordination_language": 0.0,
    }

    expected = _compute_expected(workspace)

    # Check out/story_index.csv
    story_index_path = workspace / "out" / "story_index.csv"
    headers_rows = _read_csv_rows(story_index_path) if story_index_path.exists() else None
    expected_headers = ["note_file", "story_title", "storyteller_pseudonym", "quote_count"]
    if headers_rows is not None:
        headers, rows = headers_rows
        if headers == expected_headers:
            scores["story_index_file_and_schema"] = 1.0
        if expected is not None and headers == expected_headers:
            got_tuples = []
            valid = True
            for r in rows:
                try:
                    qcount = int(str(r["quote_count"]).strip())
                except Exception:
                    valid = False
                    break
                got_tuples.append((r["note_file"], r["story_title"], r["storyteller_pseudonym"], qcount))
            if valid:
                exp_set = set(expected["expected_story_rows"])
                got_set = set(got_tuples)
                if got_set == exp_set:
                    scores["story_index_content_correct"] = 1.0

    # Check out/quotes.jsonl
    quotes_path = workspace / "out" / "quotes.jsonl"
    items = _read_jsonl(quotes_path) if quotes_path.exists() else None
    if items is not None:
        keys_ok = True
        seen_tuples = []
        for obj in items:
            if set(obj.keys()) != {"note_file", "story_title", "storyteller_pseudonym", "quote_text"}:
                keys_ok = False
                break
            seen_tuples.append((obj["note_file"], obj["story_title"], obj["storyteller_pseudonym"], obj["quote_text"]))
        if keys_ok:
            scores["quotes_jsonl_file_and_schema"] = 1.0
        if expected is not None and keys_ok:
            exp_set = set(expected["expected_quotes_rows"])
            got_set = set(seen_tuples)
            if got_set == exp_set:
                scores["quotes_jsonl_content_correct"] = 1.0

    # Check config/anonymizer.yaml updates
    config_path = workspace / "config" / "anonymizer.yaml"
    config = _parse_simple_yaml_lists(config_path) if config_path.exists() else None
    pending_ok = False
    if config is not None and expected is not None:
        pending_list = config.get("pending_names", None)
        if isinstance(pending_list, list):
            unique = len(pending_list) == len(set(pending_list))
            sorted_ci = pending_list == sorted(pending_list, key=lambda x: x.lower())
            equals_expected = pending_list == expected["expected_pending_names"]
            if unique and sorted_ci and equals_expected:
                scores["yaml_pending_names_updated"] = 1.0
                pending_ok = True
        # Only award these if pending_names is correctly updated
        if pending_ok:
            if set(config.keys()) == {"ignore_clan_terms", "pending_names"}:
                scores["yaml_only_expected_keys"] = 1.0
            if config.get("ignore_clan_terms", []) == expected["ignore_terms"]:
                scores["yaml_ignore_clan_terms_intact"] = 1.0

    # Check out/email_to_maya.txt
    email_path = workspace / "out" / "email_to_maya.txt"
    email_text = _read_text(email_path) if email_path.exists() else None
    if email_text is not None and expected is not None:
        lines = email_text.splitlines()
        if len(lines) >= 2:
            if lines[0].strip() == "To: maya@example.com" and lines[1].strip() == "Subject: Extracted stories and anonymization status":
                scores["email_headers_correct"] = 1.0
        body = "\n".join(lines[2:]) if len(lines) > 2 else ""
        if re.search(r"\b" + str(expected["total_stories"]) + r"\b", body) and re.search(r"\b" + str(expected["total_quotes"]) + r"\b", body):
            scores["email_body_includes_stats"] = 1.0
        names_ok = True
        for nm in expected["expected_pending_names"]:
            if nm not in body:
                names_ok = False
                break
        if names_ok and (len(expected["expected_pending_names"]) == 0 or any(nm in body for nm in expected["expected_pending_names"])):
            scores["email_body_lists_pending_names"] = 1.0
        if "out/story_index.csv" in body and "out/quotes.jsonl" in body:
            scores["email_body_mentions_paths"] = 1.0
        lower_body = body.lower()
        if ("anonymization" in lower_body) and (("coordinate" in lower_body) or ("coordination" in lower_body)) and ("research" in lower_body):
            scores["email_body_coordination_language"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()