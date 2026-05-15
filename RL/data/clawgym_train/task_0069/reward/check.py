import json
import sys
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set
from urllib.parse import urlparse


def _load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        if not path.exists():
            return None, f"missing:{path}"
        data = path.read_text(encoding="utf-8")
    except Exception as e:
        return None, f"read_error:{e}"
    try:
        return json.loads(data), None
    except Exception as e:
        return None, f"parse_error:{e}"


def _is_iso8601(s: Any) -> bool:
    if not isinstance(s, str) or not s:
        return False
    ts = s
    try:
        # Normalize trailing Z
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        datetime.fromisoformat(ts)
        return True
    except Exception:
        return False


def _sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _find_file_by_name(root: Path, name: str) -> Optional[Path]:
    if not root.exists():
        return None
    for p in root.rglob("*"):
        if p.is_file() and p.name == name:
            return p
    return None


def _is_hex_sha256(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    if len(s) != 64:
        return False
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", s))


def _is_http_url(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    return s.startswith("http://") or s.startswith("https://")


def _netloc(s: str) -> Optional[str]:
    try:
        return urlparse(s).netloc.lower()
    except Exception:
        return None


def _load_inputs(workspace: Path) -> Tuple[List[Dict[str, Any]], Set[str]]:
    events_path = workspace / "input" / "ambience_events.json"
    allowed_path = workspace / "input" / "allowed_licenses.json"
    events_json, events_err = _load_json(events_path)
    allowed_json, allowed_err = _load_json(allowed_path)
    events_list: List[Dict[str, Any]] = []
    allowed_set: Set[str] = set()
    if events_err is None and isinstance(events_json, dict) and isinstance(events_json.get("events"), list):
        events_list = [e for e in events_json.get("events", []) if isinstance(e, dict)]
    if allowed_err is None and isinstance(allowed_json, dict) and isinstance(allowed_json.get("allowed"), list):
        allowed_set = set(x for x in allowed_json.get("allowed", []) if isinstance(x, str))
    return events_list, allowed_set


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "per_event_manifest_presence": 0.0,
        "processed_at_format": 0.0,
        "items_metadata_valid": 0.0,
        "downloads_integrity": 0.0,
        "allowed_licenses_compliance": 0.0,
        "combined_manifest_consistency": 0.0,
        "state_file_structure": 0.0,
        "max_downloads_compliance": 0.0,
        "empty_items_have_reasons": 0.0,
        "deduplication_per_event": 0.0,
    }

    # Load inputs if present (no score is awarded solely for existing inputs)
    events_list, allowed_set = _load_inputs(workspace)

    total_events = len(events_list)
    present_valid_manifests = 0
    processed_at_ok = 0
    max_downloads_ok = 0
    empty_items_reasons_ok = 0
    dedup_events_ok = 0

    total_items = 0
    valid_items = 0
    download_items_ok = 0
    allowed_license_ok = 0

    per_event_items_map: Dict[str, List[Dict[str, Any]]] = {}

    for ev in events_list:
        ev_id = ev.get("id")
        if not isinstance(ev_id, str):
            continue
        expected_keywords = ev.get("keywords")
        expected_keywords_set = set(expected_keywords) if isinstance(expected_keywords, list) else set()
        max_downloads = ev.get("max_downloads")

        ev_dir = workspace / "output" / "events" / ev_id
        manifest_path = ev_dir / "manifest.json"
        manifest_json, manifest_err = _load_json(manifest_path)

        manifest_ok = False
        ev_processed_at_ok = False
        ev_max_downloads_ok = False
        ev_empty_reasons_ok = False
        ev_dedup_ok = False

        if manifest_err is None and isinstance(manifest_json, dict):
            mid = manifest_json.get("event_id")
            mkeywords = manifest_json.get("keywords")
            mitems = manifest_json.get("items")
            mprocessed_at = manifest_json.get("processed_at")
            if isinstance(mid, str) and mid == ev_id and isinstance(mkeywords, list) and isinstance(mitems, list):
                mkeywords_set = set(k for k in mkeywords if isinstance(k, str))
                if mkeywords_set == expected_keywords_set:
                    manifest_ok = True

            if _is_iso8601(mprocessed_at):
                ev_processed_at_ok = True

            if isinstance(max_downloads, int) and max_downloads >= 0 and isinstance(mitems, list):
                if len(mitems) <= max_downloads:
                    ev_max_downloads_ok = True

            if isinstance(mitems, list) and len(mitems) == 0:
                skipped_reasons = manifest_json.get("skipped_reasons", None)
                if isinstance(skipped_reasons, list) and all(isinstance(x, str) and x for x in skipped_reasons) and len(skipped_reasons) >= 1:
                    ev_empty_reasons_ok = True
                else:
                    ev_empty_reasons_ok = False

            # Deduplication: require unique sha256 per event when items present
            if isinstance(mitems, list):
                shas = [it.get("file_sha256") for it in mitems if isinstance(it, dict)]
                filtered = [s for s in shas if _is_hex_sha256(s)]
                if len(mitems) == 0:
                    ev_dedup_ok = True
                elif len(filtered) == len(mitems) and len(set(filtered)) == len(filtered):
                    ev_dedup_ok = True
                else:
                    ev_dedup_ok = False

            # Collect items
            if isinstance(mitems, list):
                per_event_items_map[ev_id] = mitems

        if manifest_ok:
            present_valid_manifests += 1
        if ev_processed_at_ok:
            processed_at_ok += 1
        if ev_max_downloads_ok:
            max_downloads_ok += 1
        if ev_empty_reasons_ok:
            empty_items_reasons_ok += 1
        if ev_dedup_ok:
            dedup_events_ok += 1

        # Validate item metadata and downloads
        if manifest_err is None and isinstance(manifest_json, dict) and isinstance(manifest_json.get("items"), list):
            downloads_dir = ev_dir / "downloads"
            for item in manifest_json["items"]:
                total_items += 1
                if not isinstance(item, dict):
                    continue
                # Required common fields
                required_fields = [
                    "source_domain",
                    "page_url",
                    "file_url",
                    "file_name",
                    "file_size_bytes",
                    "file_sha256",
                    "title",
                    "creator",
                    "license",
                ]
                if not all(f in item for f in required_fields):
                    continue
                # Basic type checks
                source_domain = item.get("source_domain")
                page_url = item.get("page_url")
                file_url = item.get("file_url")
                file_name = item.get("file_name")
                file_size_bytes = item.get("file_size_bytes")
                file_sha256 = item.get("file_sha256")
                title = item.get("title")
                creator = item.get("creator")
                license_str = item.get("license")
                if not (isinstance(source_domain, str) and source_domain):
                    continue
                if not (_is_http_url(page_url) and _is_http_url(file_url)):
                    continue
                # Ensure source_domain matches page_url netloc
                page_netloc = _netloc(page_url)
                if not page_netloc or page_netloc != source_domain.lower():
                    continue
                if not (isinstance(file_name, str) and file_name):
                    continue
                if not (isinstance(file_size_bytes, int) and file_size_bytes >= 0):
                    continue
                if not _is_hex_sha256(file_sha256):
                    continue
                if not (isinstance(title, str) and title):
                    continue
                if not (isinstance(creator, str) and creator):
                    continue
                if not (isinstance(license_str, str) and license_str):
                    continue

                # Optional fields checks
                duration = item.get("duration_seconds", None)
                if duration is not None and not (isinstance(duration, (int, float)) and duration >= 0):
                    continue
                # item_identifier if source is archive.org should be present and non-empty
                if isinstance(source_domain, str) and "archive.org" in source_domain.lower():
                    item_identifier = item.get("item_identifier")
                    if not (isinstance(item_identifier, str) and item_identifier):
                        continue

                valid_items += 1

                # Download integrity
                fpath = _find_file_by_name(downloads_dir, file_name) if isinstance(file_name, str) else None
                if fpath is None or not fpath.exists():
                    continue
                try:
                    actual_size = fpath.stat().st_size
                except Exception:
                    actual_size = None
                if actual_size is None or actual_size != file_size_bytes:
                    continue
                actual_sha = _sha256_file(fpath)
                if actual_sha is None or actual_sha.lower() != file_sha256.lower():
                    continue
                # size limit <= 20 MB
                if actual_size > 20 * 1024 * 1024:
                    continue
                download_items_ok += 1

                # Allowed license compliance
                if allowed_set and license_str in allowed_set:
                    allowed_license_ok += 1
                else:
                    # If allowed_set is empty or license not in set, do not increment
                    pass

    # Per-event aggregate scores
    if total_events > 0:
        scores["per_event_manifest_presence"] = present_valid_manifests / total_events
        scores["processed_at_format"] = processed_at_ok / total_events
        scores["max_downloads_compliance"] = max_downloads_ok / total_events
        scores["empty_items_have_reasons"] = empty_items_reasons_ok / total_events
        scores["deduplication_per_event"] = dedup_events_ok / total_events
    else:
        scores["per_event_manifest_presence"] = 0.0
        scores["processed_at_format"] = 0.0
        scores["max_downloads_compliance"] = 0.0
        scores["empty_items_have_reasons"] = 0.0
        scores["deduplication_per_event"] = 0.0

    # Item-level scores
    if total_items > 0:
        scores["items_metadata_valid"] = valid_items / total_items
        scores["downloads_integrity"] = download_items_ok / total_items
        if allowed_set:
            scores["allowed_licenses_compliance"] = allowed_license_ok / total_items
        else:
            scores["allowed_licenses_compliance"] = 0.0
    else:
        # With no items, do not award points
        scores["items_metadata_valid"] = 0.0
        scores["downloads_integrity"] = 0.0
        scores["allowed_licenses_compliance"] = 0.0

    # combined_manifest_consistency: union of (event_id, file_sha256)
    combined_path = workspace / "output" / "combined_manifest.json"
    combined_json, combined_err = _load_json(combined_path)
    expected_set = set()
    for ev_id, items in per_event_items_map.items():
        for it in items:
            if isinstance(it, dict):
                sha = it.get("file_sha256")
                if isinstance(sha, str):
                    expected_set.add((ev_id, sha))
    if expected_set:
        if combined_err is None and isinstance(combined_json, list):
            got_set = set()
            all_items_have_event = True
            for it in combined_json:
                if not isinstance(it, dict):
                    all_items_have_event = False
                    break
                ceid = it.get("event_id")
                csha = it.get("file_sha256")
                if isinstance(ceid, str) and isinstance(csha, str):
                    got_set.add((ceid, csha))
                else:
                    all_items_have_event = False
                    break
            if all_items_have_event and got_set == expected_set:
                scores["combined_manifest_consistency"] = 1.0
            else:
                scores["combined_manifest_consistency"] = 0.0
        else:
            scores["combined_manifest_consistency"] = 0.0
    else:
        # No items across events; require combined manifest to exist and be an empty array to pass
        if combined_err is None and isinstance(combined_json, list) and len(combined_json) == 0:
            scores["combined_manifest_consistency"] = 1.0
        else:
            scores["combined_manifest_consistency"] = 0.0

    # state_file_structure: verify required fields and count consistency
    state_path = workspace / "state" / "processed_events.json"
    state_json, state_err = _load_json(state_path)
    events_with_manifests = [ev for ev in events_list if isinstance(ev, dict) and ev.get("id") in per_event_items_map]
    if events_with_manifests:
        ok_count = 0
        if state_err is None and isinstance(state_json, dict):
            for ev in events_with_manifests:
                ev_id = ev.get("id")
                rec = state_json.get(ev_id) if isinstance(ev_id, str) else None
                if not isinstance(rec, dict):
                    continue
                config_hash = rec.get("config_hash")
                processed_at = rec.get("processed_at")
                # Accept a few possible keys for item count since the exact name is not specified
                count_val = None
                for key in ("count", "downloaded_count", "items_count"):
                    if isinstance(rec.get(key), int):
                        count_val = rec.get(key)
                        break
                items_len = len(per_event_items_map.get(ev_id, []))
                if not (isinstance(config_hash, str) and config_hash):
                    continue
                if not _is_iso8601(processed_at):
                    continue
                if not (isinstance(count_val, int) and count_val == items_len):
                    continue
                ok_count += 1
            if len(events_with_manifests) > 0:
                scores["state_file_structure"] = ok_count / len(events_with_manifests)
            else:
                scores["state_file_structure"] = 0.0
        else:
            scores["state_file_structure"] = 0.0
    else:
        scores["state_file_structure"] = 0.0

    # Ensure scores are floats within [0.0, 1.0]
    for k, v in list(scores.items()):
        try:
            if not (isinstance(v, float) or isinstance(v, int)):
                scores[k] = 0.0
            else:
                if v < 0.0:
                    scores[k] = 0.0
                elif v > 1.0:
                    scores[k] = 1.0
                else:
                    scores[k] = float(v)
        except Exception:
            scores[k] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()