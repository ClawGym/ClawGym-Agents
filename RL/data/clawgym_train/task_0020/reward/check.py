import json
import re
import sys
import subprocess
from pathlib import Path
from typing import Optional, Tuple, List


def _read_text_safe(path: Path) -> Tuple[bool, str]:
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
        return True, data
    except Exception:
        return False, ""


def _word_count(text: str) -> int:
    words = re.findall(r"\b\S+\b", text)
    return len(words)


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _parse_ci_matrix_versions(ci_text: str) -> List[str]:
    # Try inline list
    m = re.search(r"python-version\s*:\s*\[([^\]]+)\]", ci_text)
    versions = []
    if m:
        items = m.group(1)
        for part in items.split(","):
            v = part.strip().strip("'").strip('"')
            if re.fullmatch(r"3\.\d+", v):
                versions.append(v)
        return sorted(set(versions))
    # Try block list under 'matrix:'
    # Capture up to 60 lines after 'matrix:' and search for 3.xx patterns likely listed for python-version
    mat = re.search(r"matrix\s*:\s*(?:\n[^\n]*){0,60}", ci_text)
    if mat:
        block = mat.group(0)
        # Narrow further to python-version subsection if present
        pv = re.search(r"python-version\s*:(?:\s*\n(?:\s*-\s*['\"]?3\.\d+['\"]?\s*\n?)+|.*)", block)
        target = pv.group(0) if pv else block
        found = re.findall(r"['\"](3\.\d+)['\"]|(?:^|\s)-\s*['\"]?(3\.\d+)['\"]?", target, flags=re.M)
        for a, b in found:
            v = a or b
            if v:
                versions.append(v)
    return sorted(set(versions))


def _ci_uses_matrix_setup_python(ci_text: str) -> bool:
    # Must use actions/setup-python and reference matrix.python-version
    if "actions/setup-python@v" not in ci_text:
        return False
    if "matrix.python-version" not in ci_text:
        return False
    return True


def _ci_has_pip_cache(ci_text: str) -> bool:
    # Require actions/cache@v3 and path ~/.cache/pip and key contains runner.os, matrix.python-version, and hashFiles('requirements.txt')
    if "uses: actions/cache@v3" not in ci_text:
        return False
    path_ok = ("path: ~/.cache/pip" in ci_text) or ("path: '${{ env.PIP_CACHE_DIR }}'" in ci_text and "~/.cache/pip" in ci_text)
    if not path_ok:
        return False
    key_ok = all(s in ci_text for s in ["runner.os", "matrix.python-version", "hashFiles('requirements.txt')"])
    return key_ok


def _ci_runs_unittest_q(ci_text: str) -> bool:
    return "python -m unittest -q" in ci_text


def _docker_base_image(docker_text: str) -> Optional[str]:
    for line in docker_text.splitlines():
        line_s = line.strip()
        if line_s.upper().startswith("FROM "):
            parts = line_s.split()
            if len(parts) >= 2:
                return parts[1]
    return None


def _docker_has_healthcheck_probe(docker_text: str) -> bool:
    # Must contain HEALTHCHECK and invoke python -m app.metrics --health
    if "HEALTHCHECK" not in docker_text.upper():
        return False
    txt = docker_text
    if ("python -m app.metrics" in txt) and ("--health" in txt):
        return True
    if re.search(r'HEALTHCHECK.*\["python"\s*,\s*"-m"\s*,\s*"app\.metrics"\s*,\s*"--health"\s*\]', txt, re.I | re.S):
        return True
    return False


def _run_health_probe(workspace: Path) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.metrics", "--health"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=20,
        )
        out = (proc.stdout or "").strip()
        ok = (proc.returncode == 0) and (out.lower() == "ok")
        return ok, out
    except Exception as e:
        return False, f"error: {e}"


def _parse_unittest_output(text: str) -> Tuple[Optional[int], Optional[str]]:
    m = re.search(r"Ran\s+(\d+)\s+tests?", text)
    num = int(m.group(1)) if m else None
    status = None
    if re.search(r"(^|\n)OK(\n|$)", text):
        status = "OK"
    elif "FAILED" in text or "ERROR" in text:
        status = "FAILED"
    if num is None:
        dots = len(re.findall(r"(^|\n)\.+(\n|$)", text))
        if dots > 0:
            num = dots
    return num, status


def _single_paragraph(text: str) -> bool:
    lines = text.splitlines()
    paras = []
    current = []
    for ln in lines:
        if ln.strip():
            current.append(ln)
        else:
            if current:
                paras.append("\n".join(current))
                current = []
    if current:
        paras.append("\n".join(current))
    return len(paras) == 1 and len(paras[0].strip()) > 0


def _release_notes_has_sections(text: str) -> Tuple[bool, bool, bool, bool]:
    first = _first_nonempty_line(text).strip()
    title_ok = "v0.2.0" in first
    labels = ["Highlights", "Upgrade notes", "CI changes"]
    positions = {}
    for i, line in enumerate(text.splitlines()):
        stripped = line.strip().lstrip("#").strip()
        if stripped in labels and stripped not in positions:
            positions[stripped] = i
    sections_ok = all(lbl in positions for lbl in labels)
    order_ok = False
    if sections_ok:
        order_ok = positions["Highlights"] < positions["Upgrade notes"] < positions["CI changes"]
    return title_ok, ("Highlights" in positions), ("Upgrade notes" in positions), (sections_ok and order_ok)


def _release_notes_mentions_topics(text: str) -> bool:
    low = text.lower()
    py_ok = ("python" in low) and ("upgrade" in low or "3.11" in low)
    cache_ok = ("pip" in low) and ("cache" in low)
    health_ok = ("healthcheck" in low) or (("health" in low) and ("check" in low))
    return py_ok and cache_ok and health_ok


def _deploy_status_contains_matrix(text: str) -> bool:
    return re.search(r'\["3\.10"\s*,\s*"3\.11"\]', text) is not None


def _deploy_status_contains_pip_cache(text: str) -> bool:
    low = text.lower()
    return ("cache" in low) and ("~/.cache/pip" in text)


def _deploy_status_contains_base_image(text: str, tag: str) -> bool:
    return tag in text


def _deploy_status_contains_healthcheck_cmd(text: str) -> bool:
    low = text.lower()
    return ("healthcheck" in low) and ("python -m app.metrics --health" in low)


def _deploy_status_contains_tests_summary(text: str, num_tests: Optional[int], status: Optional[str]) -> bool:
    if num_tests is None or status is None:
        return False
    num_ok = re.search(rf"\b{num_tests}\b", text) is not None
    status_ok = status in text
    return num_ok and status_ok


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "ci_matrix_exact_3_10_and_3_11": 0.0,
        "ci_uses_setup_python_matrix": 0.0,
        "ci_has_pip_cache_step": 0.0,
        "ci_runs_unittest_q": 0.0,
        "docker_base_image_3_11_slim": 0.0,
        "docker_has_healthcheck_with_probe": 0.0,
        "metrics_health_cli_ok": 0.0,
        "release_notes_final_structure": 0.0,
        "release_notes_final_mentions": 0.0,
        "release_notes_final_under_200_words": 0.0,
        "comms_slack_single_paragraph": 0.0,
        "comms_slack_mentions_required": 0.0,
        "comms_slack_under_80_words": 0.0,
        "reports_test_output_present": 0.0,
        "reports_deploy_status_includes_matrix": 0.0,
        "reports_deploy_status_pip_cache_and_path": 0.0,
        "reports_deploy_status_docker_base_image": 0.0,
        "reports_deploy_status_healthcheck_command": 0.0,
        "reports_deploy_status_tests_summary": 0.0,
    }

    # CI workflow checks
    ci_path = workspace / ".github" / "workflows" / "ci.yml"
    ci_ok, ci_text = _read_text_safe(ci_path)
    versions = []
    if ci_ok:
        versions = _parse_ci_matrix_versions(ci_text)
        if sorted(versions) == ["3.10", "3.11"] and len(versions) == 2:
            scores["ci_matrix_exact_3_10_and_3_11"] = 1.0
        if _ci_uses_matrix_setup_python(ci_text):
            scores["ci_uses_setup_python_matrix"] = 1.0
        if _ci_has_pip_cache(ci_text):
            scores["ci_has_pip_cache_step"] = 1.0
        # Preserve unittest command, but only award if matrix is exactly correct as well
        if _ci_runs_unittest_q(ci_text) and scores["ci_matrix_exact_3_10_and_3_11"] == 1.0:
            scores["ci_runs_unittest_q"] = 1.0

    # Dockerfile checks
    docker_path = workspace / "Dockerfile"
    d_ok, d_text = _read_text_safe(docker_path)
    docker_tag = None
    if d_ok:
        docker_tag = _docker_base_image(d_text)
        if docker_tag == "python:3.11-slim":
            scores["docker_base_image_3_11_slim"] = 1.0
        if _docker_has_healthcheck_probe(d_text):
            scores["docker_has_healthcheck_with_probe"] = 1.0

    # Metrics health probe CLI
    probe_ok, _ = _run_health_probe(workspace)
    if probe_ok:
        scores["metrics_health_cli_ok"] = 1.0

    # Release notes final
    rn_path = workspace / "docs" / "release_notes_final.md"
    rn_ok, rn_text = _read_text_safe(rn_path)
    if rn_ok:
        title_ok, has_highlights, has_upgrade, ordered_ci_changes = _release_notes_has_sections(rn_text)
        if title_ok and has_highlights and has_upgrade and ordered_ci_changes:
            scores["release_notes_final_structure"] = 1.0
        if _release_notes_mentions_topics(rn_text):
            scores["release_notes_final_mentions"] = 1.0
        if _word_count(rn_text) <= 200:
            scores["release_notes_final_under_200_words"] = 1.0

    # Comms Slack update
    comms_path = workspace / "comms" / "race_update_slack.txt"
    c_ok, c_text = _read_text_safe(comms_path)
    if c_ok:
        if _single_paragraph(c_text.strip()):
            scores["comms_slack_single_paragraph"] = 1.0
        low = c_text.lower()
        if ("fresh build pipeline" in low) and ("pre-race data dashboards" in low):
            scores["comms_slack_mentions_required"] = 1.0
        if _word_count(c_text) <= 80:
            scores["comms_slack_under_80_words"] = 1.0

    # Reports
    test_out_path = workspace / "reports" / "test_output.txt"
    t_ok, t_text = _read_text_safe(test_out_path)
    num_tests, status = (None, None)
    if t_ok and t_text.strip():
        scores["reports_test_output_present"] = 1.0
        num_tests, status = _parse_unittest_output(t_text)

    deploy_status_path = workspace / "reports" / "deploy_status.md"
    ds_ok, ds_text = _read_text_safe(deploy_status_path)
    if ds_ok:
        if _deploy_status_contains_matrix(ds_text):
            scores["reports_deploy_status_includes_matrix"] = 1.0
        if _deploy_status_contains_pip_cache(ds_text):
            scores["reports_deploy_status_pip_cache_and_path"] = 1.0
        if docker_tag and _deploy_status_contains_base_image(ds_text, docker_tag):
            scores["reports_deploy_status_docker_base_image"] = 1.0
        if _deploy_status_contains_healthcheck_cmd(ds_text):
            scores["reports_deploy_status_healthcheck_command"] = 1.0
        if _deploy_status_contains_tests_summary(ds_text, num_tests, status):
            scores["reports_deploy_status_tests_summary"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()