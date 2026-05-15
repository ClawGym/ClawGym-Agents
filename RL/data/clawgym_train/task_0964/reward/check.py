import json
import re
import sys
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None, "missing"
        return json.loads(text), None
    except Exception as e:
        return None, str(e)


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_yaml_config(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    """
    Minimal YAML parser tailored to the provided config format.

    Expected structure:
    watch_dirs: [list]
    file_patterns: [list]
    marker_prefixes: {map of str->str}
    outputs: {map of str->str}
    """
    text = _safe_read_text(path)
    if text is None:
        return None, "missing"
    lines = text.splitlines()
    config: Dict[str, Any] = {}
    current_key: Optional[str] = None
    context_type: Optional[str] = None  # 'list' or 'map'

    top_level_list_keys = {"watch_dirs", "file_patterns"}
    top_level_map_keys = {"marker_prefixes", "outputs"}

    for raw_line in lines:
        # Remove comments
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        leading_spaces = len(line) - len(line.lstrip(" "))
        line_stripped = line.lstrip(" ")

        # Top-level section start
        if leading_spaces == 0 and line_stripped.endswith(":") and ":" not in line_stripped[:-1]:
            key = line_stripped[:-1].strip()
            if key in top_level_list_keys:
                config[key] = []
                current_key = key
                context_type = "list"
            elif key in top_level_map_keys:
                config[key] = {}
                current_key = key
                context_type = "map"
            else:
                config[key] = {}
                current_key = key
                context_type = "map"
            continue

        # Top-level "key: value"
        if leading_spaces == 0 and ":" in line_stripped and not line_stripped.endswith(":"):
            k, v = [x.strip() for x in line_stripped.split(":", 1)]
            config[k] = _strip_quotes(v)
            current_key = None
            context_type = None
            continue

        # Nested content for current section
        if current_key is None:
            continue

        # List item
        if context_type == "list" and line_stripped.startswith("-"):
            item = line_stripped[1:].strip()
            item = _strip_quotes(item)
            config[current_key].append(item)
            continue

        # Map entry
        if context_type == "map" and ":" in line_stripped:
            mk, mv = [x.strip() for x in line_stripped.split(":", 1)]
            config[current_key][mk] = _strip_quotes(mv)
            continue

    # Basic validation
    if "watch_dirs" not in config or "file_patterns" not in config or "marker_prefixes" not in config or "outputs" not in config:
        return None, "incomplete"
    # Ensure types
    if not isinstance(config["watch_dirs"], list) or not isinstance(config["file_patterns"], list):
        return None, "bad_types"
    if not isinstance(config["marker_prefixes"], dict) or not isinstance(config["outputs"], dict):
        return None, "bad_types"

    return config, None


def _sha256_of_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _find_matching_files(workspace: Path, watch_dirs: List[str], patterns: List[str]) -> List[Path]:
    files: List[Path] = []
    seen = set()
    for d in watch_dirs:
        base = workspace / d
        if not base.exists():
            continue
        for pat in patterns:
            for p in base.glob(pat):
                if p.is_file():
                    rp = p.relative_to(workspace)
                    if rp.as_posix() not in seen:
                        seen.add(rp.as_posix())
                        files.append(rp)
    files.sort()
    return files


def _extract_markers(file_path: Path, prefixes: Dict[str, str]) -> Dict[str, List[str]]:
    result = {k: [] for k in prefixes.keys()}
    text = _safe_read_text(file_path)
    if text is None:
        return result
    for line in text.splitlines():
        for cat, pref in prefixes.items():
            if line.startswith(pref):
                result[cat].append(line.strip("\n"))
    return result


def _is_iso8601_timestamp(s: str) -> bool:
    # Accept 'YYYY-MM-DDTHH:MM:SSZ' or with fractional seconds and timezone offsets
    pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}|[+-]\d{4})?$"
    return bool(re.match(pattern, s))


def _compute_current_state(workspace: Path, files: List[Path], prefixes: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    state: Dict[str, Dict[str, Any]] = {}
    for rp in files:
        fp = workspace / rp
        sha = _sha256_of_file(fp) or ""
        markers = _extract_markers(fp, prefixes)
        state[rp.as_posix()] = {"sha256": sha, "markers": markers}
    return state


def _load_previous_snapshot(workspace: Path) -> Tuple[Optional[dict], Optional[str]]:
    prev_path = workspace / "input" / "state" / "last_snapshot.json"
    return _safe_load_json(prev_path)


def _diff_states(prev: Dict[str, Any], curr: Dict[str, Any], categories: List[str]) -> List[Dict[str, Any]]:
    changed: List[Dict[str, Any]] = []
    prev_files = set(prev.get("files", {}).keys()) if isinstance(prev, dict) else set()
    curr_files = set(curr.keys())

    # Added
    for path in sorted(curr_files - prev_files):
        added_markers = {cat: curr[path]["markers"].get(cat, [])[:] for cat in categories}
        removed_markers = {cat: [] for cat in categories}
        changed.append({
            "path": path,
            "change_type": "added",
            "added_markers": added_markers,
            "removed_markers": removed_markers
        })

    # Removed
    for path in sorted(prev_files - curr_files):
        prev_markers = prev["files"][path]["markers"]
        removed_markers = {cat: prev_markers.get(cat, [])[:] for cat in categories}
        added_markers = {cat: [] for cat in categories}
        changed.append({
            "path": path,
            "change_type": "removed",
            "added_markers": added_markers,
            "removed_markers": removed_markers
        })

    # Modified
    for path in sorted(prev_files & curr_files):
        prev_entry = prev["files"][path]
        curr_entry = curr[path]
        sha_diff = prev_entry.get("sha256") != curr_entry.get("sha256")
        markers_diff = False
        added_markers_map = {}
        removed_markers_map = {}
        for cat in categories:
            prev_list = prev_entry.get("markers", {}).get(cat, []) or []
            curr_list = curr_entry.get("markers", {}).get(cat, []) or []
            added = [m for m in curr_list if m not in prev_list]
            removed = [m for m in prev_list if m not in curr_list]
            if added or removed:
                markers_diff = True
            added_markers_map[cat] = added
            removed_markers_map[cat] = removed
        if sha_diff or markers_diff:
            changed.append({
                "path": path,
                "change_type": "modified",
                "added_markers": added_markers_map,
                "removed_markers": removed_markers_map
            })

    return changed


def _compute_totals(curr_state: Dict[str, Any], categories: List[str]) -> Dict[str, int]:
    totals = {"files_scanned": len(curr_state)}
    for cat in categories:
        totals_key = f"total_{cat}"
        count = 0
        for _, entry in curr_state.items():
            count += len(entry.get("markers", {}).get(cat, []))
        totals[totals_key] = count
    return totals


def _parse_summary_for_section(text: str, heading_substr: str) -> str:
    # Return text after line containing heading_substr (case-insensitive) until next blank line or end
    lines = text.splitlines()
    idx = None
    for i, ln in enumerate(lines):
        if heading_substr.lower() in ln.lower():
            idx = i
            break
    if idx is None:
        return ""
    collected: List[str] = []
    for j in range(idx + 1, len(lines)):
        ln = lines[j]
        if ln.strip() == "":
            break
        collected.append(ln)
    return "\n".join(collected).strip()


def _first_header_line(text: str) -> str:
    for ln in text.splitlines():
        if ln.strip().startswith("#"):
            return ln.strip()
    return ""


def _count_sentences(paragraph: str) -> int:
    # Split on sentence-ending punctuation
    parts = re.split(r"(?<=[.!?])\s+", paragraph.strip())
    parts = [p for p in parts if p.strip()]
    return len(parts)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "event_json_exists": 0.0,
        "event_schema_conformance": 0.0,
        "event_type_and_timestamp_valid": 0.0,
        "event_changed_files_nonempty": 0.0,
        "event_changed_files_correct": 0.0,
        "event_summary_totals_correct": 0.0,
        "summary_md_exists": 0.0,
        "summary_header_with_timestamp_and_count": 0.0,
        "summary_totals_present": 0.0,
        "summary_changed_files_section_valid": 0.0,
        "status_update_paragraph_quality": 0.0,
        "snapshot_json_exists": 0.0,
        "snapshot_matches_current_state": 0.0,
        "cross_consistency_event_snapshot": 0.0,
    }

    # Parse config
    config_path = workspace / "config" / "watch_config.yaml"
    config, cerr = _parse_yaml_config(config_path)
    if config is None:
        return scores  # Cannot proceed without config

    watch_dirs: List[str] = config.get("watch_dirs", [])
    file_patterns: List[str] = config.get("file_patterns", [])
    marker_prefixes: Dict[str, str] = config.get("marker_prefixes", {})
    outputs: Dict[str, str] = config.get("outputs", {})

    categories = list(marker_prefixes.keys())

    # Find files and compute current state
    matched_files = _find_matching_files(workspace, watch_dirs, file_patterns)
    curr_state = _compute_current_state(workspace, matched_files, marker_prefixes)

    # Load previous snapshot
    prev_snapshot, prev_err = _load_previous_snapshot(workspace)
    prev_ok = isinstance(prev_snapshot, dict) and "files" in prev_snapshot and isinstance(prev_snapshot["files"], dict)

    # Compute expected diffs and totals
    expected_changed = _diff_states(prev_snapshot if prev_ok else {"files": {}}, curr_state, categories)
    expected_totals = _compute_totals(curr_state, categories)

    # Event JSON path
    event_path_str = outputs.get("event_path", "")
    summary_path_str = outputs.get("summary_path", "")
    snapshot_path_str = outputs.get("snapshot_path", "")

    event_path = workspace / event_path_str if event_path_str else workspace / "out" / "events" / "event.json"
    summary_path = workspace / summary_path_str if summary_path_str else workspace / "out" / "status" / "summary.md"
    snapshot_path = workspace / snapshot_path_str if snapshot_path_str else workspace / "out" / "state" / "current_snapshot.json"

    # Validate event.json
    event_json, e_err = _safe_load_json(event_path)
    if event_json is not None:
        scores["event_json_exists"] = 1.0

        # Schema conformance
        schema_ok = True
        if not isinstance(event_json, dict):
            schema_ok = False
        else:
            required_keys = {"event_type", "timestamp", "changed_files", "summary"}
            if not required_keys.issubset(set(event_json.keys())):
                schema_ok = False
            if schema_ok and not isinstance(event_json.get("event_type"), str):
                schema_ok = False
            if schema_ok and not isinstance(event_json.get("timestamp"), str):
                schema_ok = False
            if schema_ok and not isinstance(event_json.get("changed_files"), list):
                schema_ok = False
            if schema_ok and not isinstance(event_json.get("summary"), dict):
                schema_ok = False

            # Validate changed_files entries
            if schema_ok:
                for cf in event_json.get("changed_files", []):
                    if not isinstance(cf, dict):
                        schema_ok = False
                        break
                    # Required fields for ChangedFile
                    cf_req = {"path", "change_type", "added_markers", "removed_markers"}
                    if not cf_req.issubset(set(cf.keys())):
                        schema_ok = False
                        break
                    if cf.get("change_type") not in {"modified", "added", "removed"}:
                        schema_ok = False
                        break
                    if not isinstance(cf.get("path"), str):
                        schema_ok = False
                        break
                    if not isinstance(cf.get("added_markers"), dict) or not isinstance(cf.get("removed_markers"), dict):
                        schema_ok = False
                        break
                    # Ensure categories present as per config
                    for cat in categories:
                        if cat not in cf["added_markers"] or cat not in cf["removed_markers"]:
                            schema_ok = False
                            break
                        if not isinstance(cf["added_markers"][cat], list) or not isinstance(cf["removed_markers"][cat], list):
                            schema_ok = False
                            break
                    if not schema_ok:
                        break
            # Validate summary keys
            if schema_ok:
                summary_keys_ok = True
                for cat in categories:
                    k = f"total_{cat}"
                    if k not in event_json["summary"]:
                        summary_keys_ok = False
                        break
                if "files_scanned" not in event_json["summary"]:
                    summary_keys_ok = False
                if not summary_keys_ok:
                    schema_ok = False

        if schema_ok:
            scores["event_schema_conformance"] = 1.0

        # event_type and timestamp
        et_ok = event_json.get("event_type") == "file_change" and isinstance(event_json.get("timestamp"), str) and _is_iso8601_timestamp(event_json.get("timestamp", ""))
        if et_ok:
            scores["event_type_and_timestamp_valid"] = 1.0

        # event should include nonempty changed_files if changes expected
        if isinstance(event_json.get("changed_files"), list) and len(event_json.get("changed_files")) > 0:
            scores["event_changed_files_nonempty"] = 1.0

        # event changed files correctness (only if prev snapshot ok)
        if prev_ok and schema_ok:
            # Build maps by path for comparison
            expected_by_path = {c["path"]: c for c in expected_changed}
            actual_by_path = {c.get("path"): c for c in event_json.get("changed_files", []) if isinstance(c, dict) and "path" in c}
            # Paths sets must match
            if set(expected_by_path.keys()) == set(actual_by_path.keys()) and len(expected_by_path) > 0:
                all_ok = True
                for p, exp in expected_by_path.items():
                    act = actual_by_path.get(p)
                    if act is None:
                        all_ok = False
                        break
                    if act.get("change_type") != exp.get("change_type"):
                        all_ok = False
                        break
                    for cat in categories:
                        # Compare lists exactly
                        if act.get("added_markers", {}).get(cat) != exp.get("added_markers", {}).get(cat):
                            all_ok = False
                            break
                        if act.get("removed_markers", {}).get(cat) != exp.get("removed_markers", {}).get(cat):
                            all_ok = False
                            break
                    if not all_ok:
                        break
                if all_ok:
                    scores["event_changed_files_correct"] = 1.0

        # event summary totals correctness
        if schema_ok:
            summ = event_json.get("summary", {})
            totals_ok = True
            for cat in categories:
                key = f"total_{cat}"
                if summ.get(key) != expected_totals.get(key):
                    totals_ok = False
                    break
            if totals_ok and summ.get("files_scanned") == expected_totals.get("files_scanned"):
                scores["event_summary_totals_correct"] = 1.0

    # Validate summary.md
    summary_text = _safe_read_text(summary_path)
    if summary_text is not None:
        scores["summary_md_exists"] = 1.0

        # Header with timestamp and files_scanned count
        header = _first_header_line(summary_text)
        header_ok = False
        if header:
            # Must include an ISO8601-like timestamp somewhere
            has_ts = bool(re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", header))
            has_count = str(expected_totals.get("files_scanned", 0)) in header
            if has_ts and has_count:
                header_ok = True
        if header_ok:
            scores["summary_header_with_timestamp_and_count"] = 1.0

        # Totals presence (total_scenes and total_beats) based on configured categories
        totals_present = True
        for cat in categories:
            key = f"total_{cat}"
            pattern = re.compile(rf"(?i)total[\s_-]*{re.escape(cat)}[^0-9]*([0-9]+)")
            match = pattern.search(summary_text)
            if not match or int(match.group(1)) != expected_totals.get(key, -1):
                totals_present = False
                break
        if totals_present:
            scores["summary_totals_present"] = 1.0

        # Changed files section validation
        changed_section = _parse_summary_for_section(summary_text, "Changed files")
        cf_ok = False
        if changed_section:
            if prev_ok:
                all_files_ok = True
                # Each changed file listed and markers included
                for cf in expected_changed:
                    p = cf["path"]
                    if p not in changed_section:
                        all_files_ok = False
                        break
                    for cat in categories:
                        for m in cf.get("added_markers", {}).get(cat, []):
                            if m not in changed_section:
                                all_files_ok = False
                                break
                        for m in cf.get("removed_markers", {}).get(cat, []):
                            if m not in changed_section:
                                all_files_ok = False
                                break
                        if not all_files_ok:
                            break
                    if not all_files_ok:
                        break
                if all_files_ok:
                    cf_ok = True
            else:
                # If we cannot compute expected changes, at least require non-empty section
                cf_ok = True
        if cf_ok:
            scores["summary_changed_files_section_valid"] = 1.0

        # Status update paragraph quality
        status_text = _parse_summary_for_section(summary_text, "Status update")
        if not status_text:
            paras = [p.strip() for p in summary_text.split("\n\n") if p.strip()]
            status_text = paras[-1] if paras else ""
        su_ok = False
        if status_text:
            sentences_count = _count_sentences(status_text)
            mentions_file = any((cf.get("path") in status_text) for cf in expected_changed) if prev_ok else False
            has_totals_ref = False
            digits = re.findall(r"\d+", status_text)
            if str(expected_totals.get("total_scenes", -1)) in digits and str(expected_totals.get("total_beats", -1)) in digits:
                has_totals_ref = True
            else:
                if re.search(r"(?i)scene", status_text) and re.search(r"(?i)beat", status_text):
                    has_totals_ref = True
            if 2 <= sentences_count <= 3 and mentions_file and has_totals_ref:
                su_ok = True
        if su_ok:
            scores["status_update_paragraph_quality"] = 1.0

    # Validate snapshot
    snapshot_json, s_err = _safe_load_json(snapshot_path)
    if snapshot_json is not None and isinstance(snapshot_json, dict):
        scores["snapshot_json_exists"] = 1.0
        files_map = snapshot_json.get("files")
        if isinstance(files_map, dict):
            curr_keys = set(curr_state.keys())
            snap_keys = set(files_map.keys())
            if curr_keys == snap_keys and len(curr_keys) > 0:
                all_match = True
                for p in curr_keys:
                    snap_entry = files_map.get(p, {})
                    sha_ok = snap_entry.get("sha256") == curr_state[p]["sha256"]
                    markers_ok = isinstance(snap_entry.get("markers"), dict)
                    if markers_ok:
                        for cat in categories:
                            if snap_entry["markers"].get(cat) != curr_state[p]["markers"].get(cat):
                                markers_ok = False
                                break
                    if not (sha_ok and markers_ok):
                        all_match = False
                        break
                if all_match:
                    scores["snapshot_matches_current_state"] = 1.0

    # Cross-consistency between event summary and snapshot totals
    if snapshot_json is not None and isinstance(snapshot_json, dict) and event_json is not None and isinstance(event_json, dict):
        snap_files = snapshot_json.get("files", {})
        if isinstance(snap_files, dict):
            snap_totals = {"files_scanned": len(snap_files)}
            for cat in categories:
                snap_totals[f"total_{cat}"] = sum(len((snap_files[p].get("markers", {}) or {}).get(cat, [])) for p in snap_files)
            ev_summ = event_json.get("summary", {})
            if all(ev_summ.get(k) == v for k, v in snap_totals.items()):
                scores["cross_consistency_event_snapshot"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()