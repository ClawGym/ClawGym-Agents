import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    items = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                if not isinstance(obj, dict):
                    return None
                items.append(obj)
        return items
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = []
            for row in reader:
                if not isinstance(row, dict):
                    return None
                rows.append(row)
            return rows
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s


def _safe_parse_int(s: Any) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _load_eras_yaml(path: Path) -> Optional[List[Dict[str, Any]]]:
    """
    Minimal YAML parser for the expected eras.yaml structure.
    Returns list of dicts with keys: id, label, start_year, end_year.
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    in_eras = False
    eras: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not in_eras:
            if stripped.startswith("eras:"):
                in_eras = True
            continue
        # In eras section
        if re.match(r"^\s*-\s+\w+\s*:\s*.+$", line):
            # Start new dict with an inline key on this line
            if current is not None:
                eras.append(current)
            current = {}
            m = re.match(r"^\s*-\s+(\w+)\s*:\s*(.+)$", line)
            if not m:
                return None
            key = m.group(1)
            val = _strip_quotes(m.group(2).strip())
            if key in ("start_year", "end_year"):
                iv = _safe_parse_int(val)
                if iv is None:
                    return None
                current[key] = iv
            else:
                current[key] = val
        elif re.match(r"^\s*-\s*$", line):
            # Start a new empty item
            if current is not None:
                eras.append(current)
            current = {}
        elif re.match(r"^\s+\w+\s*:\s*.+$", line):
            # Continuation key-value
            m = re.match(r"^\s+(\w+)\s*:\s*(.+)$", line)
            if not m:
                return None
            key = m.group(1)
            val = _strip_quotes(m.group(2).strip())
            if current is None:
                current = {}
            if key in ("start_year", "end_year"):
                iv = _safe_parse_int(val)
                if iv is None:
                    return None
                current[key] = iv
            else:
                current[key] = val
        else:
            # Possibly end of eras section if a new top-level key encountered
            if re.match(r"^\w+\s*:\s*", line):
                break
            # Otherwise ignore unrecognized formatting
            continue
    if current is not None:
        eras.append(current)
    # Validate structure
    cleaned = []
    for e in eras:
        if not all(k in e for k in ("id", "label", "start_year", "end_year")):
            return None
        # Ensure types
        sid = str(e["id"])
        label = str(e["label"])
        sy = e["start_year"] if isinstance(e["start_year"], int) else _safe_parse_int(e["start_year"])
        ey = e["end_year"] if isinstance(e["end_year"], int) else _safe_parse_int(e["end_year"])
        if sy is None or ey is None:
            return None
        cleaned.append({"id": sid, "label": label, "start_year": sy, "end_year": ey})
    return cleaned


def _list_input_files(workspace: Path) -> List[str]:
    input_dir = workspace / "input"
    if not input_dir.exists():
        return []
    files: List[str] = []
    for p in input_dir.rglob("*"):
        if p.is_file():
            rel = p.relative_to(workspace).as_posix()
            files.append(rel)
    return sorted(files)


def _compute_expected_from_inputs(workspace: Path) -> Optional[Dict[str, Any]]:
    # Load inputs
    artists_path = workspace / "input" / "artists.csv"
    songs_path = workspace / "input" / "songs.csv"
    subgenres_path = workspace / "input" / "subgenres.jsonl"
    eras_path = workspace / "input" / "eras.yaml"

    artists_rows = _safe_read_csv_dicts(artists_path)
    songs_rows = _safe_read_csv_dicts(songs_path)
    subgenres_rows = _safe_read_jsonl(subgenres_path)
    eras_list = _load_eras_yaml(eras_path)

    if any(x is None for x in (artists_rows, songs_rows, subgenres_rows, eras_list)):
        return None

    # Build lookup maps
    artists_by_id: Dict[str, Dict[str, Any]] = {}
    for a in artists_rows:  # type: ignore
        aid = a.get("artist_id", "").strip()
        if not aid:
            continue
        artists_by_id[aid] = {
            "name": a.get("name", "").strip(),
            "country": a.get("country", "").strip(),
            "subgenre_id": a.get("subgenre_id", "").strip(),
        }

    subgenres_by_id: Dict[str, Dict[str, Any]] = {}
    for s in subgenres_rows:  # type: ignore
        sid = str(s.get("subgenre_id", "")).strip()
        if not sid:
            continue
        subgenres_by_id[sid] = {
            "name": str(s.get("name", "")).strip(),
            "start_year": _safe_parse_int(s.get("start_year")),
            "end_year": _safe_parse_int(s.get("end_year")),
        }

    eras: List[Dict[str, Any]] = eras_list  # type: ignore

    def map_year_to_era(y: int) -> List[Dict[str, Any]]:
        matches = []
        for e in eras:
            if e["start_year"] <= y <= e["end_year"]:
                matches.append(e)
        return matches

    missing_artists: List[Dict[str, Any]] = []
    missing_subgenres: List[Dict[str, Any]] = []
    invalid_eras: List[Dict[str, Any]] = []
    expected_records: List[Dict[str, Any]] = []

    for song in songs_rows:  # type: ignore
        sid = song.get("song_id", "").strip()
        title = song.get("title", "").strip()
        artist_id = song.get("artist_id", "").strip()
        ry_str = song.get("release_year", "").strip()
        s_sub = song.get("subgenre_id", "").strip()

        # Artist check
        artist = artists_by_id.get(artist_id)
        if artist is None:
            missing_artists.append({"song_id": sid, "artist_id": artist_id})
            continue

        # Subgenre resolution: song subgenre or fallback to artist
        subgenre_id = s_sub if s_sub else artist.get("subgenre_id", "")
        subgenre = subgenres_by_id.get(subgenre_id)
        if subgenre is None:
            missing_subgenres.append({"song_id": sid, "subgenre_id": subgenre_id})
            continue

        # Release year / era mapping
        ry = _safe_parse_int(ry_str)
        if ry is None:
            invalid_eras.append({"song_id": sid, "release_year": ry_str})
            continue
        era_matches = map_year_to_era(ry)
        if len(era_matches) != 1:
            invalid_eras.append({"song_id": sid, "release_year": ry})
            continue
        era = era_matches[0]

        # Valid record
        expected_records.append({
            "song_id": sid,
            "title": title,
            "artist_id": artist_id,
            "artist_name": artist["name"],
            "artist_country": artist["country"],
            "release_year": ry,
            "era_id": era["id"],
            "era_label": era["label"],
            "subgenre_id": subgenre_id,
            "subgenre_name": subgenre["name"],
        })

    return {
        "missing_artists": missing_artists,
        "missing_subgenres": missing_subgenres,
        "invalid_eras": invalid_eras,
        "expected_records": expected_records,
        "eras": eras,
    }


def _records_to_canonical(records: List[Dict[str, Any]]) -> List[Tuple]:
    canon = []
    for r in records:
        try:
            release_year = r.get("release_year")
            if isinstance(release_year, str):
                ry = _safe_parse_int(release_year)
            else:
                ry = release_year
            canon.append((
                str(r.get("song_id", "")),
                str(r.get("title", "")),
                str(r.get("artist_id", "")),
                str(r.get("artist_name", "")),
                str(r.get("artist_country", "")),
                int(ry) if ry is not None else None,
                str(r.get("era_id", "")),
                str(r.get("era_label", "")),
                str(r.get("subgenre_id", "")),
                str(r.get("subgenre_name", "")),
            ))
        except Exception:
            canon.append(tuple())
    return canon


def _parse_era_counts_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    rows = _safe_read_csv_dicts(path)
    if rows is None:
        return None
    # Validate header columns presence by checking a sample row keys
    # We will normalize keys via DictReader but no direct header.
    # Ensure expected columns exist in at least one row or rows is empty
    expected_cols = {"era_id", "era_label", "total_songs", "unique_artists"}
    if rows and not expected_cols.issubset(set(rows[0].keys())):
        return None
    parsed = []
    for r in rows:
        try:
            era_id = r.get("era_id", "").strip()
            era_label = r.get("era_label", "").strip()
            ts = _safe_parse_int(r.get("total_songs", ""))
            ua = _safe_parse_int(r.get("unique_artists", ""))
            if ts is None or ua is None or not era_id:
                return None
            parsed.append({"era_id": era_id, "era_label": era_label, "total_songs": ts, "unique_artists": ua})
        except Exception:
            return None
    return parsed


def _sum_total_songs(era_counts: List[Dict[str, Any]]) -> int:
    return sum(int(r.get("total_songs", 0)) for r in era_counts)


def _count_jsonl_lines(path: Path) -> Optional[int]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return sum(1 for _ in f if _.strip())
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "diagnostics_observed_files_correct": 0.0,
        "diagnostics_missing_unexpected_correct": 0.0,
        "diagnostics_integrity_lists_correct": 0.0,
        "normalized_records_content_correct": 0.0,
        "era_summary_content_correct": 0.0,
        "diagnostics_counts_check_correct": 0.0,
        "era_counts_match_normalized": 0.0,
        "architecture_yaml_structure_ok": 0.0,
    }

    # Expected input paths
    expected_inputs = {
        "input/artists.csv",
        "input/songs.csv",
        "input/subgenres.jsonl",
        "input/eras.yaml",
    }

    # Paths to expected outputs
    normalized_path = workspace / "out" / "normalized" / "records.jsonl"
    era_counts_path = workspace / "out" / "summary" / "era_counts.csv"
    diagnostics_path = workspace / "out" / "diagnostics" / "integrity_report.json"
    architecture_path = workspace / "out" / "architecture.yaml"

    # Load diagnostics
    diagnostics = _safe_load_json(diagnostics_path)

    # Compute observed input files
    actual_observed = set(_list_input_files(workspace))
    computed_missing = sorted(list(expected_inputs - actual_observed))
    computed_unexpected = sorted(list(actual_observed - expected_inputs))

    # Check diagnostics observed files
    if isinstance(diagnostics, dict) and isinstance(diagnostics.get("observed_input_files"), list):
        diag_observed = set(str(x) for x in diagnostics.get("observed_input_files", []))
        if diag_observed == actual_observed:
            scores["diagnostics_observed_files_correct"] = 1.0

    # Check diagnostics missing/unexpected
    if isinstance(diagnostics, dict):
        diag_missing = diagnostics.get("missing_files")
        diag_unexpected = diagnostics.get("unexpected_files")
        if isinstance(diag_missing, list) and isinstance(diag_unexpected, list):
            if set(str(x) for x in diag_missing) == set(computed_missing) and set(str(x) for x in diag_unexpected) == set(computed_unexpected):
                scores["diagnostics_missing_unexpected_correct"] = 1.0

    # Compute expected integrity lists and normalized records from inputs
    expected = _compute_expected_from_inputs(workspace)

    # Check diagnostics integrity lists
    if isinstance(diagnostics, dict) and expected is not None:
        # Extract lists from diagnostics
        d_ma = diagnostics.get("missing_artists")
        d_ms = diagnostics.get("missing_subgenres")
        d_ie = diagnostics.get("invalid_eras")
        ok = True
        if not (isinstance(d_ma, list) and isinstance(d_ms, list) and isinstance(d_ie, list)):
            ok = False
        else:
            # Compare as sets of tuples
            def to_set(lst: List[Dict[str, Any]], keys: List[str]) -> Optional[set]:
                s = set()
                for item in lst:
                    if not isinstance(item, dict):
                        return None
                    try:
                        s.add(tuple((k, str(item.get(k, ""))) for k in keys))
                    except Exception:
                        return None
                return s

            exp_ma = to_set(expected["missing_artists"], ["song_id", "artist_id"])
            exp_ms = to_set(expected["missing_subgenres"], ["song_id", "subgenre_id"])
            exp_ie = to_set(expected["invalid_eras"], ["song_id", "release_year"])

            got_ma = to_set(d_ma, ["song_id", "artist_id"]) if isinstance(d_ma, list) else None
            got_ms = to_set(d_ms, ["song_id", "subgenre_id"]) if isinstance(d_ms, list) else None
            got_ie = to_set(d_ie, ["song_id", "release_year"]) if isinstance(d_ie, list) else None

            if None in (exp_ma, exp_ms, exp_ie, got_ma, got_ms, got_ie):
                ok = False
            else:
                if not (exp_ma == got_ma and exp_ms == got_ms and exp_ie == got_ie):
                    ok = False
        if ok:
            scores["diagnostics_integrity_lists_correct"] = 1.0

    # Check normalized records content
    got_records = _safe_read_jsonl(normalized_path)
    if expected is not None and isinstance(got_records, list):
        # Verify each record has exactly required keys
        required_keys = {
            "song_id",
            "title",
            "artist_id",
            "artist_name",
            "artist_country",
            "release_year",
            "era_id",
            "era_label",
            "subgenre_id",
            "subgenre_name",
        }
        keys_ok = True
        for r in got_records:
            if not isinstance(r, dict):
                keys_ok = False
                break
            r_keys = set(r.keys())
            if r_keys != required_keys:
                keys_ok = False
                break
        if keys_ok:
            exp_records = expected["expected_records"]
            got_canon = set(_records_to_canonical(got_records))
            exp_canon = set(_records_to_canonical(exp_records))
            if got_canon == exp_canon:
                scores["normalized_records_content_correct"] = 1.0

    # Check era_summary_content_correct
    era_counts = _parse_era_counts_csv(era_counts_path)
    if era_counts is not None and expected is not None:
        # Build expected counts from expected records
        counts_by_era: Dict[str, Dict[str, Any]] = {}
        for rec in expected["expected_records"]:
            eid = rec["era_id"]
            elabel = rec["era_label"]
            aid = rec["artist_id"]
            if eid not in counts_by_era:
                counts_by_era[eid] = {"era_label": elabel, "total_songs": 0, "artists": set()}
            counts_by_era[eid]["total_songs"] += 1
            counts_by_era[eid]["artists"].add(aid)
        expected_counts = {
            eid: {"era_label": v["era_label"], "total_songs": v["total_songs"], "unique_artists": len(v["artists"])}
            for eid, v in counts_by_era.items()
        }
        # Validate header presence and that all non-zero expected eras are present and correct
        ok = True
        file_counts_by_era: Dict[str, Dict[str, Any]] = {}
        for row in era_counts:
            file_counts_by_era[row["era_id"]] = {
                "era_label": row["era_label"],
                "total_songs": row["total_songs"],
                "unique_artists": row["unique_artists"],
            }
        # For each expected era with >0, must be present and match
        for eid, v in expected_counts.items():
            if v["total_songs"] > 0:
                fr = file_counts_by_era.get(eid)
                if fr is None:
                    ok = False
                    break
                if not (fr["total_songs"] == v["total_songs"] and fr["unique_artists"] == v["unique_artists"] and fr["era_label"] == v["era_label"]):
                    ok = False
                    break
        # Additionally, if file reports an era present, it must not contradict expected counts for that era
        if ok:
            for eid, fr in file_counts_by_era.items():
                exp = expected_counts.get(eid)
                if exp is not None:
                    if not (fr["total_songs"] == exp["total_songs"] and fr["unique_artists"] == exp["unique_artists"] and fr["era_label"] == exp["era_label"]):
                        ok = False
                        break
        if ok:
            scores["era_summary_content_correct"] = 1.0

    # Check diagnostics counts_check
    if isinstance(diagnostics, dict):
        cc = diagnostics.get("counts_check")
        if isinstance(cc, dict):
            nr = cc.get("normalized_record_count")
            ect = cc.get("era_counts_total_songs")
            matches = cc.get("matches")
            # Compute actual counts
            actual_nr = _count_jsonl_lines(normalized_path)
            actual_era_counts = _parse_era_counts_csv(era_counts_path)
            if actual_nr is not None and actual_era_counts is not None:
                actual_sum = _sum_total_songs(actual_era_counts)
                try:
                    nr_int = int(nr) if nr is not None else None
                    ect_int = int(ect) if ect is not None else None
                except Exception:
                    nr_int = None
                    ect_int = None
                if nr_int == actual_nr and ect_int == actual_sum and matches is True and (actual_nr == actual_sum):
                    scores["diagnostics_counts_check_correct"] = 1.0

    # Check era_counts_match_normalized (independent of diagnostics)
    actual_nr_lines = _count_jsonl_lines(normalized_path)
    actual_era_counts2 = _parse_era_counts_csv(era_counts_path)
    if actual_nr_lines is not None and actual_era_counts2 is not None:
        if actual_nr_lines == _sum_total_songs(actual_era_counts2):
            scores["era_counts_match_normalized"] = 1.0

    # Check architecture.yaml structure
    arch_text = _read_text(architecture_path)
    if arch_text is not None:
        ok_arch = True

        # Check stages block for exact ordered stages
        stages_expected = ["validate_inputs", "normalize_enrich", "summarize"]

        def extract_list_block(text: str, key: str) -> List[str]:
            lines = text.splitlines()
            block: List[str] = []
            in_block = False
            base_indent = None
            for i, raw in enumerate(lines):
                if not in_block:
                    if re.match(rf"^\s*{re.escape(key)}\s*:\s*$", raw):
                        in_block = True
                        # Determine base indent of following lines
                        base_indent = None
                        continue
                else:
                    # End of block when next top-level key without indent
                    if re.match(r"^\S.*:\s*$", raw):
                        break
                    if raw.strip().startswith("-"):
                        # Extract item after '-'
                        m = re.match(r"^\s*-\s*(.+?)\s*$", raw)
                        if m:
                            item = _strip_quotes(m.group(1).strip())
                            block.append(item)
                    else:
                        # May be continuation or empty
                        continue
            return block

        stages_list = extract_list_block(arch_text, "stages")
        if stages_list != stages_expected:
            ok_arch = False

        # Check inputs contain 4 exact paths
        inputs_list = extract_list_block(arch_text, "inputs")
        exp_inputs_list = sorted([
            "input/artists.csv",
            "input/songs.csv",
            "input/subgenres.jsonl",
            "input/eras.yaml",
        ])
        if sorted(inputs_list) != exp_inputs_list:
            ok_arch = False

        # Check outputs contain 3 exact paths
        outputs_list = extract_list_block(arch_text, "outputs")
        exp_outputs_list = sorted([
            "out/normalized/records.jsonl",
            "out/summary/era_counts.csv",
            "out/diagnostics/integrity_report.json",
        ])
        if sorted(outputs_list) != exp_outputs_list:
            ok_arch = False

        # Check run_command and assumptions keys present
        if not re.search(r"^\s*run_command\s*:\s*.+$", arch_text, re.MULTILINE):
            ok_arch = False
        if not re.search(r"^\s*assumptions\s*:\s*$", arch_text, re.MULTILINE):
            ok_arch = False

        if ok_arch:
            scores["architecture_yaml_structure_ok"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()