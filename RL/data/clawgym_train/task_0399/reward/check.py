import json
import hashlib
import sys
import os
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any
import zipfile
import glob
import fnmatch
import subprocess
import shlex
import re


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _compute_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _read_version_txt(workspace: Path) -> Optional[str]:
    p = workspace / "input" / "version.txt"
    txt = _safe_read_text(p)
    if txt is None:
        return None
    return txt.strip()


def _extract_yaml_version(text: str) -> Optional[str]:
    # Find a line with version: value and return the value without quotes/spaces
    # Use a strict line-based regex to avoid complex YAML parsing.
    for line in text.splitlines():
        m = re.match(r'^\s*version\s*:\s*["\']?([^"\']+)["\']?\s*$', line)
        if m:
            return m.group(1).strip()
    return None


def _zip_list_files(zip_path: Path) -> Optional[List[str]]:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = []
            for n in zf.namelist():
                if n.endswith("/"):
                    continue
                names.append(n)
            return names
    except Exception:
        return None


def _zip_read_file(zip_path: Path, inner_path: str) -> Optional[bytes]:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            with zf.open(inner_path, "r") as f:
                return f.read()
    except Exception:
        return None


def _glob_files(workspace: Path, pattern: str) -> List[str]:
    # Return list of relative posix paths matching the pattern, limited to files
    # Use glob with recursive to support ** if present.
    matches = []
    full_pattern = str(workspace / pattern)
    for p in glob.glob(full_pattern, recursive=True):
        p_path = Path(p)
        if p_path.is_file():
            try:
                rel = p_path.relative_to(workspace).as_posix()
            except Exception:
                # If cannot make relative, skip
                continue
            matches.append(rel)
    return matches


def _compute_rules_expected(workspace: Path) -> Optional[Tuple[List[str], List[str], Optional[str]]]:
    # Returns (expected_rebased_files_in_zip_sorted, excluded_files_sorted, expected_zip_name) or None on error
    rules_path = workspace / "input" / "release_rules.json"
    rules = _safe_load_json(rules_path)
    if not isinstance(rules, dict):
        return None
    include_globs = rules.get("include_globs")
    exclude_globs = rules.get("exclude_globs")
    template = rules.get("artifact_name_template")
    if not isinstance(include_globs, list) or not isinstance(exclude_globs, list) or not isinstance(template, str):
        return None

    included_set = set()
    for pat in include_globs:
        for rel in _glob_files(workspace, pat):
            included_set.add(rel)

    excluded_set = set()
    for pat in exclude_globs:
        for rel in _glob_files(workspace, pat):
            excluded_set.add(rel)

    # Only files that are both included by include_globs and excluded by exclude_globs are "excluded_by_rules"
    excluded_by_rules = sorted(included_set.intersection(excluded_set))

    # Files to include in zip from input/, with the leading "input/" stripped
    def _strip_input_prefix(rel: str) -> Optional[str]:
        if rel.startswith("input/"):
            return rel[len("input/"):]
        return None

    final_included = []
    for rel in sorted(included_set - set(excluded_by_rules)):
        stripped = _strip_input_prefix(rel)
        if stripped is None:
            # If included file is not under input/, it's invalid per task, but ignore here
            continue
        final_included.append(stripped)

    version = _read_version_txt(workspace)
    if version is None:
        expected_zip_name = None
    else:
        try:
            expected_zip_name = template.format(version=version)
        except Exception:
            expected_zip_name = None

    return (sorted(final_included), excluded_by_rules, expected_zip_name)


def _is_executable_file(path: Path) -> bool:
    try:
        return path.is_file() and os.access(str(path), os.X_OK)
    except Exception:
        return False


def _run_cmd_capture(args: List[str], cwd: Optional[Path] = None, timeout: int = 10) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(args, cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        return proc.returncode, proc.stdout.decode("utf-8", errors="replace"), proc.stderr.decode("utf-8", errors="replace")
    except Exception as e:
        return (1, "", str(e))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "release_script_present_and_executable": 0.0,
        "release_script_mentions_tools_yq": 0.0,
        "yq_binary_present_and_executable": 0.0,
        "yq_version_in_report_and_valid": 0.0,
        "yq_version_binary_matches_report": 0.0,
        "input_app_yaml_version_updated": 0.0,
        "artifact_zip_path_and_name_valid": 0.0,
        "zip_includes_expected_files_only": 0.0,
        "app_yaml_inside_zip_updated": 0.0,
        "checksums_txt_matches_artifact": 0.0,
        "report_json_consistent_with_artifact": 0.0,
    }

    # Check release script existence and executability
    release_script = workspace / "scripts" / "release.sh"
    if release_script.exists() and _is_executable_file(release_script):
        scores["release_script_present_and_executable"] = 1.0
    # Check that script references tools/yq
    script_text = _safe_read_text(release_script) if release_script.exists() else None
    if isinstance(script_text, str) and "tools/yq" in script_text:
        scores["release_script_mentions_tools_yq"] = 1.0

    # Check yq binary presence and executability
    yq_path = workspace / "tools" / "yq"
    if _is_executable_file(yq_path):
        scores["yq_binary_present_and_executable"] = 1.0

    # Read version.txt and ensure input/app.yaml updated
    version_txt = _read_version_txt(workspace)
    app_yaml_path = workspace / "input" / "app.yaml"
    app_yaml_text = _safe_read_text(app_yaml_path)
    if version_txt is not None and isinstance(app_yaml_text, str):
        v_in_yaml = _extract_yaml_version(app_yaml_text)
        if v_in_yaml == version_txt:
            scores["input_app_yaml_version_updated"] = 1.0

    # Compute rules expected files and zip name
    rules_expected = _compute_rules_expected(workspace)
    expected_rebased_files: List[str] = []
    expected_excluded_originals: List[str] = []
    expected_zip_name: Optional[str] = None
    if rules_expected is not None:
        expected_rebased_files = rules_expected[0]
        expected_excluded_originals = rules_expected[1]
        expected_zip_name = rules_expected[2]

    # Load report.json and validate yq version presence
    report_path = workspace / "build" / "report.json"
    report = _safe_load_json(report_path)
    if isinstance(report, dict) and isinstance(report.get("yq_version"), str):
        if "v4.44.3" in report.get("yq_version", ""):
            scores["yq_version_in_report_and_valid"] = 1.0

    # Compare runtime yq --version with report yq_version
    if _is_executable_file(yq_path) and isinstance(report, dict) and isinstance(report.get("yq_version"), str):
        rc, out, err = _run_cmd_capture([str(yq_path), "--version"], cwd=workspace)
        # Accept stdout or stderr, but yq prints to stdout normally.
        runtime_ver = (out or err).strip()
        if runtime_ver and ("v4.44.3" in runtime_ver) and (runtime_ver == report.get("yq_version")):
            scores["yq_version_binary_matches_report"] = 1.0

    # Validate artifact path and name
    dist_dir = workspace / "dist"
    artifact_path = None
    if isinstance(report, dict) and isinstance(report.get("artifact_path"), str):
        artifact_path = workspace / report["artifact_path"]
    # Determine expected artifact path
    expected_artifact_path = None
    if expected_zip_name:
        expected_artifact_path = dist_dir / expected_zip_name

    if artifact_path and expected_artifact_path and artifact_path == expected_artifact_path and artifact_path.exists():
        scores["artifact_zip_path_and_name_valid"] = 1.0

    # Zip contents checks
    zip_ok = False
    app_yaml_in_zip_ok = False
    no_extra_input_prefix = False
    if artifact_path and artifact_path.exists():
        actual_files = _zip_list_files(artifact_path) or []
        # Must contain app.yaml at root
        if "app.yaml" in actual_files:
            # Check app.yaml version inside zip
            app_yaml_bytes = _zip_read_file(artifact_path, "app.yaml")
            if isinstance(app_yaml_bytes, (bytes, bytearray)):
                try:
                    inner_text = app_yaml_bytes.decode("utf-8", errors="replace")
                except Exception:
                    inner_text = ""
                v_in_zip_yaml = _extract_yaml_version(inner_text)
                if version_txt is not None and v_in_zip_yaml == version_txt:
                    app_yaml_in_zip_ok = True
        # Check no 'input/' prefix present anywhere
        no_extra_input_prefix = all(not name.startswith("input/") for name in actual_files)
        # Build expected full set inside zip
        expected_full_set = set(["app.yaml"] + expected_rebased_files)
        actual_set = set(actual_files)
        if actual_set == expected_full_set and no_extra_input_prefix:
            zip_ok = True

    if zip_ok:
        scores["zip_includes_expected_files_only"] = 1.0
    if app_yaml_in_zip_ok:
        scores["app_yaml_inside_zip_updated"] = 1.0

    # Checksums file validation
    checksums_path = workspace / "dist" / "checksums.txt"
    if artifact_path and artifact_path.exists():
        expected_sha = _compute_sha256(artifact_path)
        cs_text = _safe_read_text(checksums_path)
        if expected_zip_name and expected_sha and isinstance(cs_text, str):
            # Verify exactly one non-empty line
            lines = [ln for ln in cs_text.splitlines() if ln.strip() != ""]
            if len(lines) == 1:
                expected_line = f"artifact={expected_zip_name} sha256={expected_sha}"
                if lines[0].strip() == expected_line:
                    scores["checksums_txt_matches_artifact"] = 1.0

    # Report JSON consistency
    report_ok = False
    if isinstance(report, dict) and artifact_path and artifact_path.exists():
        # Exact keys check
        expected_keys = {
            "yq_version",
            "app_version",
            "artifact_path",
            "artifact_size_bytes",
            "included_files",
            "excluded_files",
            "zip_sha256",
        }
        keys_ok = set(report.keys()) == expected_keys
        # Type and value checks
        types_ok = (
            isinstance(report.get("yq_version"), str)
            and isinstance(report.get("app_version"), str)
            and isinstance(report.get("artifact_path"), str)
            and isinstance(report.get("artifact_size_bytes"), int)
            and isinstance(report.get("included_files"), list)
            and isinstance(report.get("excluded_files"), list)
            and isinstance(report.get("zip_sha256"), str)
        )
        # Values validations
        app_ver_ok = (version_txt is not None) and (report.get("app_version") == version_txt)
        artifact_path_ok = (expected_artifact_path is not None) and (report.get("artifact_path") == str(expected_artifact_path.relative_to(workspace)))
        size_ok = False
        try:
            size_ok = artifact_path.stat().st_size == report.get("artifact_size_bytes")
        except Exception:
            size_ok = False
        # included_files must equal actual zip content sorted ascending
        actual_files = _zip_list_files(artifact_path) or []
        actual_sorted = sorted(actual_files)
        included_files_value = report.get("included_files")
        included_sorted_ok = False
        included_equals_ok = False
        if isinstance(included_files_value, list):
            # ensure list of strings
            if all(isinstance(x, str) for x in included_files_value):
                included_sorted_ok = included_files_value == sorted(included_files_value)
                included_equals_ok = included_files_value == actual_sorted
        # excluded_files should equal the originals that were excluded by rules (input paths)
        excluded_files_ok = False
        if expected_excluded_originals is not None:
            excluded_list = report.get("excluded_files")
            if isinstance(excluded_list, list) and all(isinstance(x, str) for x in excluded_list):
                excluded_files_ok = excluded_list == sorted(expected_excluded_originals)
        # zip_sha256 correctness
        sha_ok = False
        computed_sha = _compute_sha256(artifact_path)
        if isinstance(report.get("zip_sha256"), str) and computed_sha is not None:
            sha_ok = (report.get("zip_sha256") == computed_sha)

        report_ok = all([
            keys_ok,
            types_ok,
            app_ver_ok,
            artifact_path_ok,
            size_ok,
            included_sorted_ok,
            included_equals_ok,
            excluded_files_ok,
            sha_ok,
        ])

    if report_ok:
        scores["report_json_consistent_with_artifact"] = 1.0

    # Ensure scores are floats within [0.0, 1.0]
    for k, v in list(scores.items()):
        try:
            vf = float(v)
        except Exception:
            vf = 0.0
        if vf < 0.0:
            vf = 0.0
        if vf > 1.0:
            vf = 1.0
        scores[k] = vf

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()