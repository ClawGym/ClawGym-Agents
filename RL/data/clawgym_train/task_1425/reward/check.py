import json
import sys
import re
import csv
from pathlib import Path
from html.parser import HTMLParser
from collections import Counter, defaultdict


def _safe_read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _safe_json_load(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _safe_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows, None
    except Exception as e:
        return None, str(e)


def _is_executable_or_shebang(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
        if mode & 0o111:
            return True
    except Exception:
        pass
    # Check shebang
    try:
        with path.open("r", encoding="utf-8") as f:
            first = f.readline()
            if first.startswith("#!"):
                return True
    except Exception:
        pass
    return False


class EpisodeHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.episode_id = None
        self.title = None
        self.air_date = None
        self._in_characters = False
        self._in_quotes = False
        self._in_li = False
        self._current_li_text = []
        self.characters = []
        self.quotes_raw = []  # list of raw li text for quotes

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag.lower() == "article":
            if "data-episode" in attrs_dict:
                self.episode_id = attrs_dict.get("data-episode")
            if "data-title" in attrs_dict:
                self.title = attrs_dict.get("data-title")
        elif tag.lower() == "meta":
            name = attrs_dict.get("name")
            if name and name.lower() == "air_date":
                self.air_date = attrs_dict.get("content")
        elif tag.lower() == "section":
            sec_id = attrs_dict.get("id", "")
            if sec_id == "characters":
                self._in_characters = True
            elif sec_id == "quotes":
                self._in_quotes = True
        elif tag.lower() == "li":
            if self._in_characters or self._in_quotes:
                self._in_li = True
                self._current_li_text = []

    def handle_endtag(self, tag):
        if tag.lower() == "section":
            # Reset flags when leaving a section
            if self._in_characters:
                self._in_characters = False
            if self._in_quotes:
                self._in_quotes = False
        elif tag.lower() == "li":
            if self._in_li:
                text = "".join(self._current_li_text).strip()
                if self._in_characters:
                    if text:
                        self.characters.append(text)
                elif self._in_quotes:
                    if text:
                        self.quotes_raw.append(text)
                self._in_li = False
                self._current_li_text = []

    def handle_data(self, data):
        if self._in_li and (self._in_characters or self._in_quotes):
            self._current_li_text.append(data)


def _load_alias_mapping(workspace: Path):
    aliases_path = workspace / "input" / "character_aliases.csv"
    rows, err = _safe_csv_rows(aliases_path)
    if rows is None or len(rows) == 0:
        return {}, {}, "missing_or_invalid_aliases"
    header = rows[0]
    try:
        alias_idx = header.index("alias")
        canonical_idx = header.index("canonical")
    except ValueError:
        return {}, {}, "missing_columns"
    alias_map = {}
    canonical_lookup = {}
    for r in rows[1:]:
        if len(r) <= max(alias_idx, canonical_idx):
            return {}, {}, "row_too_short"
        alias = r[alias_idx].strip()
        canonical = r[canonical_idx].strip()
        if alias == "" or canonical == "":
            # Malformed row
            return {}, {}, "empty_values"
        alias_map[alias.lower()] = canonical
        canonical_lookup[canonical.lower()] = canonical
    return alias_map, canonical_lookup, None


def _parse_episode_file(path: Path):
    text, err = _safe_read_text(path)
    if text is None:
        return None
    parser = EpisodeHTMLParser()
    try:
        parser.feed(text)
    except Exception:
        return None
    result = {
        "episode_id": parser.episode_id,
        "title": parser.title,
        "air_date": parser.air_date,
        "characters": parser.characters,
        "quotes_raw": parser.quotes_raw,
    }
    # Basic required fields must be present
    if not result["episode_id"] or not result["title"] or not result["air_date"]:
        return None
    return result


def _collect_expected_from_inputs(workspace: Path):
    # Load alias map
    alias_map, canonical_lookup, err = _load_alias_mapping(workspace)
    # It's okay if alias mapping is missing/malformed; we'll compute expected with what we have
    # But if malformed, canonical_lookup may be empty; then only aliases mapping would help; if missing, both empty
    episodes_dir = workspace / "input" / "episodes"
    expected_by_id = {}
    warnings_unrec_speakers = defaultdict(int)  # key: (episode_id, name) -> lines
    warnings_unrec_characters = set()  # (episode_id, name)
    canonical_line_counts = defaultdict(lambda: {"total": 0, "episodes": set()})
    if episodes_dir.exists() and episodes_dir.is_dir():
        for f in sorted(episodes_dir.glob("*.html")):
            ep = _parse_episode_file(f)
            if not ep:
                continue
            ep_id = ep["episode_id"]
            title = ep["title"]
            air_date = ep["air_date"]
            # Normalize characters
            canon_chars_set = set()
            for name in ep["characters"]:
                name_stripped = name.strip()
                lc = name_stripped.lower()
                if lc in alias_map:
                    canon_chars_set.add(alias_map[lc])
                elif lc in canonical_lookup:
                    canon_chars_set.add(canonical_lookup[lc])
                else:
                    warnings_unrec_characters.add((ep_id, name_stripped))
            canon_chars = sorted(canon_chars_set)
            # Process quotes
            quotes = []
            for qline in ep["quotes_raw"]:
                # Split by first colon
                if ":" in qline:
                    speaker_raw, text = qline.split(":", 1)
                    speaker_raw = speaker_raw.strip()
                    text = text.strip()
                else:
                    speaker_raw = ""
                    text = qline.strip()
                # Normalize speaker
                lc = speaker_raw.lower()
                canonical_speaker = None
                if lc in alias_map:
                    canonical_speaker = alias_map[lc]
                elif lc in canonical_lookup:
                    canonical_speaker = canonical_lookup[lc]
                # Prepare quote entry
                if canonical_speaker:
                    speaker_out = canonical_speaker
                    canonical_line_counts[canonical_speaker]["total"] += 1
                    canonical_line_counts[canonical_speaker]["episodes"].add(ep_id)
                else:
                    speaker_out = speaker_raw
                    if speaker_raw != "":
                        warnings_unrec_speakers[(ep_id, speaker_raw)] += 1
                quotes.append({"speaker": speaker_out, "text": text})
            expected_by_id[ep_id] = {
                "episode_id": ep_id,
                "title": title,
                "air_date": air_date,
                "characters": canon_chars,
                "quotes": quotes,
            }
    # Prepare expected warnings
    expected_unrec_speakers = [{"episode_id": k[0], "name": k[1], "lines": v}
                               for k, v in warnings_unrec_speakers.items()]
    expected_unrec_characters = [{"episode_id": eid, "name": nm}
                                 for (eid, nm) in warnings_unrec_characters]
    # Prepare expected line counts
    expected_line_counts = []
    for char, info in canonical_line_counts.items():
        expected_line_counts.append({
            "canonical_character": char,
            "total_quote_lines": info["total"],
            "distinct_episodes": len(info["episodes"]),
        })
    return expected_by_id, expected_unrec_speakers, expected_unrec_characters, expected_line_counts


def _is_sorted_unique(strings):
    if not strings:
        return True
    return all(strings[i] < strings[i+1] for i in range(len(strings)-1))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_present": 0.0,
        "script_executable_or_shebang": 0.0,
        "episodes_json_exists": 0.0,
        "episodes_json_valid_structure": 0.0,
        "episodes_json_content_correct": 0.0,
        "characters_lists_sorted_unique": 0.0,
        "character_line_counts_csv_exists": 0.0,
        "character_line_counts_csv_valid_structure": 0.0,
        "character_line_counts_content_correct": 0.0,
        "warnings_json_exists": 0.0,
        "warnings_json_valid_structure": 0.0,
        "warnings_content_correct": 0.0,
        "build_log_exists_nonempty": 0.0,
    }

    # Check script presence and executability/shebang
    script_path = workspace / "scripts" / "build_episode_index.sh"
    if script_path.exists() and script_path.is_file():
        scores["script_present"] = 1.0
        if _is_executable_or_shebang(script_path):
            scores["script_executable_or_shebang"] = 1.0

    # Compute expected from inputs
    expected_by_id, exp_unrec_speakers, exp_unrec_characters, exp_line_counts = _collect_expected_from_inputs(workspace)

    # Episodes JSON checks
    out_dir = workspace / "out"
    episodes_json_path = out_dir / "episodes.json"
    episodes_data, episodes_err = _safe_json_load(episodes_json_path)
    if episodes_data is not None:
        scores["episodes_json_exists"] = 1.0
        valid_structure = True
        # Must be a list
        if not isinstance(episodes_data, list):
            valid_structure = False
        else:
            # Validate each episode object
            for item in episodes_data:
                if not isinstance(item, dict):
                    valid_structure = False
                    break
                required_keys = {"episode_id", "title", "air_date", "characters", "quotes"}
                if not required_keys.issubset(set(item.keys())):
                    valid_structure = False
                    break
                if not isinstance(item.get("episode_id"), str):
                    valid_structure = False
                    break
                if not isinstance(item.get("title"), str):
                    valid_structure = False
                    break
                if not isinstance(item.get("air_date"), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", item.get("air_date")):
                    valid_structure = False
                    break
                if not isinstance(item.get("characters"), list) or any(not isinstance(x, str) for x in item.get("characters")):
                    valid_structure = False
                    break
                if not isinstance(item.get("quotes"), list):
                    valid_structure = False
                    break
                for q in item.get("quotes"):
                    if not isinstance(q, dict):
                        valid_structure = False
                        break
                    if "speaker" not in q or "text" not in q:
                        valid_structure = False
                        break
                    if not isinstance(q["speaker"], str) or not isinstance(q["text"], str):
                        valid_structure = False
                        break
                if not valid_structure:
                    break
        if valid_structure:
            scores["episodes_json_valid_structure"] = 1.0

        # Characters lists sorted and unique check
        chars_sorted_unique_ok = False
        if isinstance(episodes_data, list):
            chars_sorted_unique_ok = True
            for item in episodes_data:
                if not isinstance(item, dict):
                    chars_sorted_unique_ok = False
                    break
                chars = item.get("characters")
                if not isinstance(chars, list):
                    chars_sorted_unique_ok = False
                    break
                # Must be sorted and unique alphabetically
                if not _is_sorted_unique(chars):
                    chars_sorted_unique_ok = False
                    break
        if chars_sorted_unique_ok:
            scores["characters_lists_sorted_unique"] = 1.0

        # Content correctness against expected
        content_ok = False
        if isinstance(episodes_data, list):
            try:
                # Build map by episode_id
                cand_by_id = {}
                for item in episodes_data:
                    if isinstance(item, dict) and "episode_id" in item:
                        cand_by_id[item["episode_id"]] = item
                exp_ids = set(expected_by_id.keys())
                cand_ids = set(cand_by_id.keys())
                # Strictly require equality of episode id sets
                if exp_ids == cand_ids:
                    # Compare fields
                    all_match = True
                    for eid in exp_ids:
                        exp = expected_by_id[eid]
                        cand = cand_by_id[eid]
                        # title
                        if cand.get("title") != exp["title"]:
                            all_match = False
                            break
                        # air_date
                        if cand.get("air_date") != exp["air_date"]:
                            all_match = False
                            break
                        # characters exact equality of sorted lists
                        if cand.get("characters") != exp["characters"]:
                            all_match = False
                            break
                        # quotes: compare as multiset of (speaker, text)
                        exp_counter = Counter((q["speaker"], q["text"]) for q in exp["quotes"])
                        try:
                            cand_counter = Counter((q["speaker"], q["text"]) for q in cand.get("quotes", []))
                        except Exception:
                            all_match = False
                            break
                        if exp_counter != cand_counter:
                            all_match = False
                            break
                    content_ok = all_match
                else:
                    content_ok = False
            except Exception:
                content_ok = False
        if content_ok:
            scores["episodes_json_content_correct"] = 1.0

    # Character line counts CSV checks
    line_counts_path = out_dir / "character_line_counts.csv"
    rows, rows_err = _safe_csv_rows(line_counts_path)
    if rows is not None:
        scores["character_line_counts_csv_exists"] = 1.0
        valid_structure = True
        if len(rows) >= 1:
            header = rows[0]
            if header != ["canonical_character", "total_quote_lines", "distinct_episodes"]:
                valid_structure = False
            else:
                # Verify rows have correct types (ints for counts)
                for r in rows[1:]:
                    if len(r) != 3:
                        valid_structure = False
                        break
                    # canonical_character as non-empty string
                    if not isinstance(r[0], str) or r[0].strip() == "":
                        valid_structure = False
                        break
                    # counts as integers
                    try:
                        int(r[1])
                        int(r[2])
                    except Exception:
                        valid_structure = False
                        break
        else:
            valid_structure = False
        if valid_structure:
            scores["character_line_counts_csv_valid_structure"] = 1.0

        # Content correctness
        content_ok = False
        try:
            cand_map = {}
            for r in rows[1:]:
                name = r[0]
                total = int(r[1])
                distinct = int(r[2])
                if name in cand_map:
                    # duplicate row for same character is not allowed; aggregate would be ambiguous
                    cand_map[name] = (cand_map[name][0] + total, cand_map[name][1] + distinct)
                else:
                    cand_map[name] = (total, distinct)
            exp_map = {e["canonical_character"]: (e["total_quote_lines"], e["distinct_episodes"]) for e in exp_line_counts}
            content_ok = cand_map == exp_map
        except Exception:
            content_ok = False
        if content_ok:
            scores["character_line_counts_content_correct"] = 1.0

    # Warnings JSON checks
    warnings_path = out_dir / "warnings.json"
    warnings_data, warnings_err = _safe_json_load(warnings_path)
    if warnings_data is not None:
        scores["warnings_json_exists"] = 1.0
        valid_structure = True
        if not isinstance(warnings_data, dict):
            valid_structure = False
        else:
            if "unrecognized_speakers" not in warnings_data or "unrecognized_characters" not in warnings_data:
                valid_structure = False
            else:
                us = warnings_data.get("unrecognized_speakers")
                uc = warnings_data.get("unrecognized_characters")
                if not isinstance(us, list) or not isinstance(uc, list):
                    valid_structure = False
                else:
                    for item in us:
                        if not isinstance(item, dict):
                            valid_structure = False
                            break
                        if not {"episode_id", "name", "lines"}.issubset(item.keys()):
                            valid_structure = False
                            break
                        if not isinstance(item["episode_id"], str) or not isinstance(item["name"], str):
                            valid_structure = False
                            break
                        try:
                            lines_val = int(item["lines"])
                            if lines_val < 1:
                                valid_structure = False
                                break
                        except Exception:
                            valid_structure = False
                            break
                    if valid_structure:
                        for item in uc:
                            if not isinstance(item, dict):
                                valid_structure = False
                                break
                            if not {"episode_id", "name"}.issubset(item.keys()):
                                valid_structure = False
                                break
                            if not isinstance(item["episode_id"], str) or not isinstance(item["name"], str):
                                valid_structure = False
                                break
        if valid_structure:
            scores["warnings_json_valid_structure"] = 1.0

        # Content correctness
        content_ok = False
        try:
            cand_us_list = warnings_data.get("unrecognized_speakers", []) if isinstance(warnings_data, dict) else []
            cand_uc_list = warnings_data.get("unrecognized_characters", []) if isinstance(warnings_data, dict) else []
            # Build maps/sets for comparison
            cand_us_map = {}
            dup_flag = False
            for item in cand_us_list:
                key = (item.get("episode_id"), item.get("name"))
                if key in cand_us_map:
                    dup_flag = True
                    cand_us_map[key] += int(item.get("lines"))
                else:
                    cand_us_map[key] = int(item.get("lines"))
            # Duplicates are considered incorrect; we require unique entries
            if dup_flag:
                content_ok = False
            else:
                exp_us_map = {}
                for obj in exp_unrec_speakers:
                    exp_us_map[(obj["episode_id"], obj["name"])] = int(obj["lines"])
                # Compare maps
                if cand_us_map == exp_us_map:
                    # Compare unrecognized_characters as set of tuples
                    cand_uc_set = set()
                    for item in cand_uc_list:
                        cand_uc_set.add((item.get("episode_id"), item.get("name")))
                    exp_uc_set = set((obj["episode_id"], obj["name"]) for obj in exp_unrec_characters)
                    content_ok = cand_uc_set == exp_uc_set
                else:
                    content_ok = False
        except Exception:
            content_ok = False
        if content_ok:
            scores["warnings_content_correct"] = 1.0

    # Build log check
    build_log_path = out_dir / "build.log"
    try:
        if build_log_path.exists() and build_log_path.is_file():
            content = build_log_path.read_text(encoding="utf-8")
            if content.strip() != "":
                scores["build_log_exists_nonempty"] = 1.0
    except Exception:
        pass

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()