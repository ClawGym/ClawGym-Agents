import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[dict]:
    text = _read_text_safe(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _parse_library_name(path: Path) -> Optional[str]:
    data = _load_json_safe(path)
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    if not isinstance(name, str) or not name:
        return None
    return name


def _parse_version_name(path: Path) -> Optional[str]:
    text = _read_text_safe(path)
    if text is None:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("VERSION_NAME="):
            return line.split("=", 1)[1].strip()
    return None


def _parse_build_gradle_sdks(path: Path) -> Optional[Tuple[int, int]]:
    text = _read_text_safe(path)
    if text is None:
        return None
    min_match = re.search(r"minSdkVersion\s+(\d+)", text)
    target_match = re.search(r"targetSdkVersion\s+(\d+)", text)
    if not min_match or not target_match:
        return None
    try:
        min_sdk = int(min_match.group(1))
        target_sdk = int(target_match.group(1))
        return (min_sdk, target_sdk)
    except Exception:
        return None


def _parse_test_summary(path: Path) -> Optional[Tuple[int, int]]:
    data = _load_json_safe(path)
    if not isinstance(data, dict):
        return None
    try:
        passed = int(data.get("passed"))
        failed = int(data.get("failed"))
        return (passed, failed)
    except Exception:
        return None


def _parse_docs_yaml(path: Path) -> Optional[Tuple[Optional[str], Optional[int]]]:
    """
    Minimal YAML parsing for expected keys: doc_title (string), minSdk (int)
    """
    text = _read_text_safe(path)
    if text is None:
        return None
    doc_title = None
    min_sdk = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("doc_title:"):
            val = line.split(":", 1)[1].strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            doc_title = val
        elif line.startswith("minSdk:"):
            val = line.split(":", 1)[1].strip()
            try:
                min_sdk = int(val)
            except Exception:
                min_sdk = None
    return (doc_title, min_sdk)


def _run_validator(workspace: Path) -> bool:
    script = workspace / "scripts" / "validate_docs.py"
    if not script.exists():
        return False
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return proc.returncode == 0 and ("All checks passed." in (proc.stdout or ""))
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    path_library_json = workspace / "config" / "library.json"
    path_props = workspace / "gradle.properties"
    path_build = workspace / "app" / "build.gradle"
    path_tests = workspace / "reports" / "test_results.json"
    path_doc_yaml = workspace / "config" / "docs.yaml"
    path_setup_md = workspace / "docs" / "SETUP.md"

    lib_name = _parse_library_name(path_library_json)
    version_name = _parse_version_name(path_props)
    sdks = _parse_build_gradle_sdks(path_build)
    tests = _parse_test_summary(path_tests)

    min_sdk = sdks[0] if sdks else None
    target_sdk = sdks[1] if sdks else None
    passed = tests[0] if tests else None
    failed = tests[1] if tests else None

    expected_title = None
    if lib_name is not None and version_name is not None:
        expected_title = f"Setup for {lib_name} v{version_name}"

    setup_text = _read_text_safe(path_setup_md) if path_setup_md.exists() else None
    yaml_parsed = _parse_docs_yaml(path_doc_yaml) if path_doc_yaml.exists() else None
    yaml_title = yaml_parsed[0] if yaml_parsed else None
    yaml_min = yaml_parsed[1] if yaml_parsed else None

    scores = {
        "setup_md_title_correct": 0.0,
        "setup_md_min_sdk_correct": 0.0,
        "setup_md_target_sdk_correct": 0.0,
        "setup_md_passed_correct": 0.0,
        "setup_md_failed_correct": 0.0,
        "docs_yaml_title_correct": 0.0,
        "docs_yaml_min_sdk_correct": 0.0,
        "validator_passed": 0.0,
    }

    # SETUP.md checks
    if setup_text is not None and expected_title is not None:
        if expected_title in setup_text:
            scores["setup_md_title_correct"] = 1.0
    if setup_text is not None and min_sdk is not None:
        if f"minSdk: {min_sdk}" in setup_text:
            scores["setup_md_min_sdk_correct"] = 1.0
    if setup_text is not None and target_sdk is not None:
        if f"targetSdk: {target_sdk}" in setup_text:
            scores["setup_md_target_sdk_correct"] = 1.0
    if setup_text is not None and passed is not None:
        if f"passed: {passed}" in setup_text:
            scores["setup_md_passed_correct"] = 1.0
    if setup_text is not None and failed is not None:
        if f"failed: {failed}" in setup_text:
            scores["setup_md_failed_correct"] = 1.0

    # docs.yaml checks
    if yaml_title is not None and expected_title is not None:
        if yaml_title == expected_title:
            scores["docs_yaml_title_correct"] = 1.0
    if yaml_min is not None and min_sdk is not None:
        if yaml_min == min_sdk:
            scores["docs_yaml_min_sdk_correct"] = 1.0

    # Validator execution
    scores["validator_passed"] = 1.0 if _run_validator(workspace) else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()