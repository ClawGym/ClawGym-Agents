import json
import csv
import hashlib
import platform
import shutil
import sys
from pathlib import Path
from typing import Tuple, List, Dict, Any

BEGIN_MARKER = "<!-- BEGIN SYSTEM AUDIT -->"
END_MARKER = "<!-- END SYSTEM AUDIT -->"

# Immutable expected context from the provided manuscript (outside markers)
EXPECTED_PRE_BEFORE_MARKER = """Title: Light, Line, and Intimacy in the Bloomsbury Circle

I have long argued that the Bloomsbury Group’s visual experiments—circulating through Bell, Grant, Fry, and others—made the English interior an arena of cosmopolitan inquiry. The still, reflective planes of Vanessa Bell’s mantels and tables are never simply domestic; they are linguistic propositions about color, sympathy, and friendship. Duncan Grant’s bodies—bathers and dancers—index a social world that accepts porous identities and values the tender contingency of form.

Notes toward slides: Bell’s Still Life on a Corner of a Mantelpiece; Grant’s Bathers by the Pond; Fry’s Omega Workshops textiles. The excerpts below will be refined before delivery and synchronized with the image permissions.

Appendix: System & Assets Audit
"""
EXPECTED_BEGIN_MARKER_LINE = BEGIN_MARKER + "\n"
EXPECTED_END_MARKER_LINE = END_MARKER + "\n"
EXPECTED_POST_AFTER_MARKER = """
Draft prepared for: University seminar on Bloomsbury aesthetics and art criticism.
"""

def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def _load_json_safe(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _load_manifest_expected_txts(manifest_path: Path) -> List[str]:
    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or "filename" not in reader.fieldnames:
                return []
            filenames: List[str] = []
            for row in reader:
                fn = (row.get("filename") or "").strip()
                if fn and fn.lower().endswith(".txt"):
                    filenames.append(fn)
            return filenames
    except Exception:
        return []

def _compute_assets_info(workspace: Path, expected_filenames: List[str]) -> Tuple[List[Dict[str, Any]], List[str]]:
    assets_dir = workspace / "assets" / "paintings"
    present: List[Dict[str, Any]] = []
    missing: List[str] = []
    for fn in expected_filenames:
        p = assets_dir / fn
        if p.is_file():
            try:
                data = p.read_bytes()
                size = len(data)
                sha = hashlib.sha256(data).hexdigest()
                present.append({"filename": fn, "size_bytes": size, "sha256": sha})
            except Exception:
                missing.append(fn)
        else:
            missing.append(fn)
    return present, missing

def _json_has_valid_structure(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    required_types = {
        "os_name": str,
        "os_version": str,
        "python_version": str,
        "disk_free_bytes": int,
        "present_assets": list,
        "missing_assets": list,
    }
    for k, t in required_types.items():
        if k not in obj or not isinstance(obj[k], t):
            return False
    # Validate present_assets entries
    for item in obj["present_assets"]:
        if not isinstance(item, dict):
            return False
        if set(item.keys()) != {"filename", "size_bytes", "sha256"}:
            return False
        if not isinstance(item.get("filename"), str):
            return False
        if not isinstance(item.get("size_bytes"), int):
            return False
        sha = item.get("sha256")
        if not isinstance(sha, str):
            return False
        if len(sha) != 64:
            return False
        try:
            int(sha, 16)
        except Exception:
            return False
    # Validate missing_assets entries
    for fn in obj["missing_assets"]:
        if not isinstance(fn, str):
            return False
    return True

def _os_version_matches(json_version: str) -> bool:
    # Accept platform.version() or platform.release() representations
    try:
        candidates = {platform.version(), platform.release()}
    except Exception:
        candidates = set()
    if json_version in candidates:
        return True
    for cand in candidates:
        try:
            if json_version.startswith(cand) or cand.startswith(json_version):
                return True
        except Exception:
            continue
    return False

def _get_disk_free_bytes(path: Path) -> int:
    try:
        usage = shutil.disk_usage(str(path))
        return int(usage.free)
    except Exception:
        return -1

def _extract_between_markers(text: str) -> Tuple[str, str, str, bool]:
    """
    Returns (prefix, between, suffix, markers_ok)
    """
    if not text:
        return "", "", "", False
    begin_idx = text.find(BEGIN_MARKER)
    end_idx = text.find(END_MARKER)
    if begin_idx == -1 or end_idx == -1 or end_idx <= begin_idx:
        return "", "", "", False

    # Expect markers as separate lines with newline after begin marker
    begin_line_end = begin_idx + len(EXPECTED_BEGIN_MARKER_LINE)
    end_marker_start = end_idx
    prefix = text[:begin_idx]
    between = text[begin_line_end:end_marker_start]
    suffix = text[end_idx + len(EXPECTED_END_MARKER_LINE):]
    return prefix, between, suffix, True

def _bullet_lines(text: str) -> List[str]:
    lines: List[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            lines.append(line)
    return lines

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "system_audit_json_valid_structure": 0.0,
        "system_audit_values_match_environment": 0.0,
        "present_assets_content_correct": 0.0,
        "present_assets_sorted_by_size": 0.0,
        "missing_assets_list_correct": 0.0,
        "manuscript_markers_and_context_preserved": 0.0,
        "manuscript_system_info_bullets_correct": 0.0,
        "manuscript_top2_assets_bullets_correct": 0.0,
    }

    system_json_path = workspace / "output" / "system_audit.json"
    manifest_path = workspace / "input" / "data" / "asset_manifest.csv"
    manuscript_path = workspace / "input" / "manuscripts" / "lecture_draft.md"

    obj = _load_json_safe(system_json_path)
    if obj is not None and _json_has_valid_structure(obj):
        scores["system_audit_json_valid_structure"] = 1.0

        # Validate environment values strictly but with OS version flexibility and disk tolerance
        env_os_name = platform.system()
        ok_os_name = (obj.get("os_name") == env_os_name)

        json_os_version = obj.get("os_version")
        ok_os_version = isinstance(json_os_version, str) and _os_version_matches(json_os_version)

        env_python_version = platform.python_version()
        ok_python = (obj.get("python_version") == env_python_version)

        env_disk_free = _get_disk_free_bytes(workspace)
        json_disk_free = obj.get("disk_free_bytes")
        if env_disk_free > 0 and isinstance(json_disk_free, int):
            tolerance = max(int(0.05 * env_disk_free), 20 * 1024 * 1024)  # 5% or 20MB
            ok_disk = abs(env_disk_free - json_disk_free) <= tolerance
        else:
            ok_disk = False

        if ok_os_name and ok_os_version and ok_python and ok_disk:
            scores["system_audit_values_match_environment"] = 1.0

        # Asset checks derived from manifest and workspace
        expected_filenames = _load_manifest_expected_txts(manifest_path)
        if expected_filenames:
            expected_present, expected_missing = _compute_assets_info(workspace, expected_filenames)

            # Check present_assets content equality (filenames and their size/sha)
            json_present = obj.get("present_assets", [])
            try:
                json_map = {e["filename"]: (e["size_bytes"], e["sha256"]) for e in json_present if isinstance(e, dict)}
            except Exception:
                json_map = {}

            expected_map = {e["filename"]: (e["size_bytes"], e["sha256"]) for e in expected_present}
            if set(json_map.keys()) == set(expected_map.keys()):
                content_match = True
                for fn, vals in expected_map.items():
                    if json_map.get(fn) != vals:
                        content_match = False
                        break
                if content_match:
                    scores["present_assets_content_correct"] = 1.0

            # Check sorting by size_bytes descending in JSON
            if isinstance(json_present, list) and len(json_present) >= 1:
                sizes = []
                valid = True
                for e in json_present:
                    if not isinstance(e, dict) or "size_bytes" not in e or not isinstance(e["size_bytes"], int):
                        valid = False
                        break
                    sizes.append(e["size_bytes"])
                if valid and all(sizes[i] >= sizes[i + 1] for i in range(len(sizes) - 1)):
                    scores["present_assets_sorted_by_size"] = 1.0

            # Missing assets list exact match
            json_missing = obj.get("missing_assets", [])
            if isinstance(json_missing, list):
                if set(json_missing) == set(expected_missing):
                    scores["missing_assets_list_correct"] = 1.0

    # Manuscript checks (only award if appendix content has been replaced)
    manuscript_text = _read_text_safe(manuscript_path)
    if manuscript_text:
        prefix, between, suffix, markers_ok = _extract_between_markers(manuscript_text)
        if markers_ok:
            # Verify context outside markers is preserved exactly and placeholder replaced
            placeholder = "This appendix will be generated to document the environment and asset checks for reproducibility."
            replaced = placeholder not in between
            begin_marker_line_ok = BEGIN_MARKER + "\n" in manuscript_text
            end_marker_line_ok = END_MARKER + "\n" in manuscript_text
            if (
                prefix == EXPECTED_PRE_BEFORE_MARKER
                and suffix == EXPECTED_POST_AFTER_MARKER
                and begin_marker_line_ok
                and end_marker_line_ok
                and replaced
            ):
                # Only award this if replaced to avoid giving points to the baseline
                scores["manuscript_markers_and_context_preserved"] = 1.0

            # System info bullets must reflect JSON if JSON is valid
            if obj is not None and _json_has_valid_structure(obj) and replaced:
                bullets = _bullet_lines(between)
                os_name_str = obj.get("os_name")
                os_version_str = obj.get("os_version")
                py_ver_str = obj.get("python_version")
                disk_free_str = str(obj.get("disk_free_bytes"))

                contains_os_name = any(isinstance(b, str) and os_name_str in b for b in bullets) if isinstance(os_name_str, str) else False
                contains_os_version = any(isinstance(b, str) and os_version_str in b for b in bullets) if isinstance(os_version_str, str) else False
                contains_python = any(isinstance(b, str) and py_ver_str in b for b in bullets) if isinstance(py_ver_str, str) else False
                contains_disk = any(isinstance(b, str) and disk_free_str in b for b in bullets)

                if contains_os_name and contains_os_version and contains_python and contains_disk:
                    scores["manuscript_system_info_bullets_correct"] = 1.0

                # Top 2 largest present assets bullets: verify inclusion of top 2 from JSON (already sorted there)
                present_assets = obj.get("present_assets") or []
                top2 = present_assets[:2]
                if len(top2) >= 1 and bullets:
                    found_all = True
                    for asset in top2:
                        fn = asset.get("filename")
                        size_str = str(asset.get("size_bytes"))
                        sha8 = (asset.get("sha256") or "")[:8]
                        found = any((isinstance(b, str)) and (fn in b) and (size_str in b) and (sha8 in b) for b in bullets)
                        if not found:
                            found_all = False
                            break
                    if found_all:
                        scores["manuscript_top2_assets_bullets_correct"] = 1.0

    return scores

def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()