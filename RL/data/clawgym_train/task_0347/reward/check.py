import json
import sys
import re
from pathlib import Path


ORIGINAL_DATA_SOURCES_SECTION = "- data/market_snapshot.csv: Exported from our research database."


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except Exception:
        return -1


def find_section(md_text: str, header_title: str) -> str:
    lines = md_text.splitlines()
    content_lines = []
    in_section = False
    for line in lines:
        if line.strip().lower() == f"## {header_title}".lower():
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):
                break
            content_lines.append(line)
    return "\n".join(content_lines).strip()


def section_exists(md_text: str, header_title: str) -> bool:
    lines = md_text.splitlines()
    header_line = f"## {header_title}"
    for line in lines:
        if line.strip() == header_line:
            return True
    return False


def contains_schedule_text(text: str) -> bool:
    if not text:
        return False
    cron_match = re.search(r"cron:\s*[\"']?\s*0\s+6\s+\*\s+\*\s+sun\s*[\"']?", text, flags=re.IGNORECASE)
    english_time = all(s in text.lower() for s in ["sunday", "06:00", "utc"])
    return bool(cron_match) or english_time


def contains_push_main(text: str) -> bool:
    if not text:
        return False
    has_push = "push" in text.lower()
    has_main = re.search(r"\bmain\b", text, flags=re.IGNORECASE) is not None
    return has_push and has_main


def yaml_has_setup_python_310(text: str) -> bool:
    if not text:
        return False
    uses_setup = "actions/setup-python" in text
    python_version = re.search(r"python-version:\s*[\"']?3\.10[\"']?", text)
    return uses_setup and (python_version is not None)


def yaml_has_runs_on_ubuntu(text: str) -> bool:
    return bool(re.search(r"runs-on:\s*ubuntu-latest", text))


def yaml_has_install_requirements(text: str) -> bool:
    if not text:
        return False
    return ("pip install -r requirements.txt" in text) or ("python -m pip install -r requirements.txt" in text)


def yaml_has_pytest_q(text: str) -> bool:
    return "pytest -q" in text


def yaml_has_build_command(text: str) -> bool:
    cmd = "python scripts/build_digest.py -i data/market_snapshot.csv -o dist/digest.html"
    return cmd in text


def yaml_has_upload_artifact(text: str) -> bool:
    if not text:
        return False
    has_action = "actions/upload-artifact" in text
    has_name = re.search(r"name:\s*[\"']?weekly-digest[\"']?", text) is not None
    has_path = re.search(r"path:\s*[\"']?dist/digest\.html[\"']?", text) is not None
    return has_action and has_name and has_path


def inventory_includes_all_top_level(inventory_text: str, workspace: Path) -> bool:
    if not inventory_text:
        return False
    listed = set()
    for raw in inventory_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        listed.add(line)
    def line_matches(name: str) -> bool:
        return (name in listed) or (name + "/" in listed)
    try:
        for child in workspace.iterdir():
            if not line_matches(child.name):
                return False
    except Exception:
        return False
    return True


def inventory_has_path_with_size(inventory_text: str, relpath: str, expected_size: int) -> bool:
    if not inventory_text or expected_size < 0:
        return False
    for raw in inventory_text.splitlines():
        if relpath in raw:
            nums = re.findall(r"\d+", raw)
            for n in nums:
                try:
                    if int(n) == expected_size:
                        return True
                except Exception:
                    continue
    return False


def professional_tone(email_text: str) -> bool:
    if not email_text:
        return False
    lower = email_text.lower()
    has_greeting = ("dear " in lower) or ("hello" in lower)
    has_closing = ("regards" in lower) or ("thank you" in lower) or ("sincerely" in lower)
    return has_greeting and has_closing


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "workflow_exists_and_name": 0.0,
        "workflow_triggers": 0.0,
        "workflow_job_env": 0.0,
        "workflow_install_and_test": 0.0,
        "workflow_build_step": 0.0,
        "workflow_artifact_upload": 0.0,
        "workflow_paths_reference_valid": 0.0,
        "docs_automated_section_present": 0.0,
        "docs_manual_section_removed": 0.0,
        "docs_triggers_documented": 0.0,
        "docs_commands_documented": 0.0,
        "docs_artifact_documented": 0.0,
        "docs_operations_overview_updated": 0.0,
        "docs_data_sources_unchanged": 0.0,
        "repo_check_inventory": 0.0,
        "repo_check_sizes": 0.0,
        "email_workflow_path": 0.0,
        "email_triggers": 0.0,
        "email_artifact": 0.0,
        "email_no_secrets": 0.0,
        "email_requests": 0.0,
        "email_tone": 0.0,
    }

    # Workflow checks
    wf_path = workspace / ".github" / "workflows" / "digest.yml"
    wf_text = read_text_safe(wf_path)
    if wf_path.exists() and wf_text:
        has_name = re.search(r"^name:\s*Weekly Digest CI\s*$", wf_text, flags=re.MULTILINE) is not None
        if has_name:
            scores["workflow_exists_and_name"] = 1.0
        trig_push_main = contains_push_main(wf_text)
        trig_schedule = contains_schedule_text(wf_text)
        if trig_push_main and trig_schedule:
            scores["workflow_triggers"] = 1.0
        if yaml_has_runs_on_ubuntu(wf_text) and yaml_has_setup_python_310(wf_text):
            scores["workflow_job_env"] = 1.0
        if yaml_has_install_requirements(wf_text) and yaml_has_pytest_q(wf_text):
            scores["workflow_install_and_test"] = 1.0
        if yaml_has_build_command(wf_text):
            scores["workflow_build_step"] = 1.0
        if yaml_has_upload_artifact(wf_text):
            scores["workflow_artifact_upload"] = 1.0
        build_cmd_ok = yaml_has_build_command(wf_text)
        build_script_exists = (workspace / "scripts" / "build_digest.py").exists()
        data_file_exists = (workspace / "data" / "market_snapshot.csv").exists()
        if build_cmd_ok and build_script_exists and data_file_exists:
            scores["workflow_paths_reference_valid"] = 1.0

    # Docs checks
    ops_path = workspace / "docs" / "ops-guide.md"
    ops_text = read_text_safe(ops_path)
    if ops_text:
        has_automated = section_exists(ops_text, "Automated Build (CI)")
        has_manual = section_exists(ops_text, "Manual Build Process")
        if has_automated:
            scores["docs_automated_section_present"] = 1.0
        if not has_manual:
            scores["docs_manual_section_removed"] = 1.0

        auto_section = find_section(ops_text, "Automated Build (CI)")
        if auto_section and contains_push_main(auto_section) and contains_schedule_text(auto_section):
            scores["docs_triggers_documented"] = 1.0
        cmd_build = "python scripts/build_digest.py -i data/market_snapshot.csv -o dist/digest.html"
        if auto_section and ("pytest -q" in auto_section) and (cmd_build in auto_section):
            scores["docs_commands_documented"] = 1.0
        if auto_section and ("dist/digest.html" in auto_section) and ("weekly-digest" in auto_section):
            scores["docs_artifact_documented"] = 1.0

        ops_overview = find_section(ops_text, "Operations Overview")
        if ops_overview and ("automated" in ops_overview.lower()) and ("ci" in ops_overview.lower()):
            scores["docs_operations_overview_updated"] = 1.0

        # Only credit Data Sources unchanged if the doc was actually modified (automated section present and manual removed)
        if has_automated and not has_manual:
            data_sources = find_section(ops_text, "Data Sources")
            expected_lines = [ORIGINAL_DATA_SOURCES_SECTION]
            ds_lines = [ln.rstrip() for ln in data_sources.splitlines() if ln.strip() != ""]
            if ds_lines == expected_lines:
                scores["docs_data_sources_unchanged"] = 1.0

    # Repo check inventory
    repo_check_path = workspace / "output" / "repo_check.txt"
    repo_check_text = read_text_safe(repo_check_path)
    if repo_check_text:
        if inventory_includes_all_top_level(repo_check_text, workspace):
            scores["repo_check_inventory"] = 1.0
        targets = [
            ("scripts/build_digest.py", workspace / "scripts" / "build_digest.py"),
            ("data/market_snapshot.csv", workspace / "data" / "market_snapshot.csv"),
            ("tests/test_build.py", workspace / "tests" / "test_build.py"),
        ]
        size_ok = True
        for rel, pth in targets:
            sz = file_size(pth)
            if sz < 0 or not inventory_has_path_with_size(repo_check_text, rel, sz):
                size_ok = False
                break
        if size_ok:
            scores["repo_check_sizes"] = 1.0

    # Email checks
    email_path = workspace / "output" / "email_to_it_vendor.txt"
    email_text = read_text_safe(email_path)
    if email_text:
        if ".github/workflows/digest.yml" in email_text:
            scores["email_workflow_path"] = 1.0
        if contains_push_main(email_text) and contains_schedule_text(email_text):
            scores["email_triggers"] = 1.0
        if ("dist/digest.html" in email_text) and ("weekly-digest" in email_text):
            scores["email_artifact"] = 1.0
        if "no secrets" in email_text.lower():
            scores["email_no_secrets"] = 1.0
        requests_ok = ("scheduled" in email_text.lower()) and ("artifact retention" in email_text.lower())
        if requests_ok:
            scores["email_requests"] = 1.0
        if professional_tone(email_text):
            scores["email_tone"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()