import json
import re
import sys
from pathlib import Path
from typing import Optional, List, Set, Dict


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_python_version(workspace: Path) -> Optional[str]:
    pv_text = _read_text(workspace / ".python-version")
    if pv_text is None:
        return None
    version = pv_text.strip()
    m = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*", version)
    if not m:
        return None
    return m.group(1)


def _extract_ci_python_versions(ci_text: str) -> List[str]:
    versions = re.findall(r"python-version\s*:\s*['\"]?([0-9]+(?:\.[0-9]+)?)", ci_text)
    return versions


def _extract_dockerfile_args(docker_text: str) -> Set[str]:
    args = set()
    for line in docker_text.splitlines():
        m = re.match(r"^\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)", line)
        if m:
            args.add(m.group(1))
    return args


def _ci_contains_build_arg_with_secret(ci_text: str, arg_name: str) -> bool:
    pattern = r"--build-arg\s+" + re.escape(arg_name) + r"\s*=\s*\$\{\{\s*secrets\." + re.escape(arg_name) + r"\s*\}\}"
    return re.search(pattern, ci_text) is not None


def _readme_contains_python_version(readme_text: str, version: str) -> bool:
    explicit = re.search(r"Python:\s*" + re.escape(version) + r"\b", readme_text)
    if explicit:
        return True
    return version in readme_text


def _read_email_fields(email_text: str) -> Dict[str, Optional[str]]:
    lines = email_text.splitlines()
    fields = {"To": None, "Subject": None, "Body": None}
    body_lines = []
    seen_body = False
    for line in lines:
        if not seen_body:
            m_to = re.match(r"^\s*To:\s*(.*)\s*$", line)
            if m_to:
                fields["To"] = m_to.group(1).strip()
                continue
            m_subj = re.match(r"^\s*Subject:\s*(.*)\s*$", line)
            if m_subj:
                fields["Subject"] = m_subj.group(1).strip()
                continue
            m_body = re.match(r"^\s*Body:\s*(.*)$", line)
            if m_body:
                first = m_body.group(1)
                body_lines.append(first.strip())
                seen_body = True
                continue
        else:
            body_lines.append(line.strip())
    if seen_body:
        body = " ".join([ln for ln in body_lines if ln is not None])
        fields["Body"] = body.strip()
    return fields


def _count_sentences(text: str) -> int:
    if not text:
        return 0
    s = re.sub(r"\s+", " ", text.strip())
    parts = re.split(r"(?<=[.!?])\s+", s)
    parts = [p for p in parts if p.strip()]
    return len(parts)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "ci_python_version_matches": 0.0,
        "ci_build_arg_matches": 0.0,
        "readme_python_version_updated": 0.0,
        "readme_token_name_updated": 0.0,
        "readme_ci_section_and_typed_ast": 0.0,
        "email_fields_valid": 0.0,
        "email_sentence_count_valid": 0.0,
        "email_content_includes_requirements": 0.0,
        "report_lists_changed_files": 0.0,
        "report_python_version_and_arg": 0.0,
    }

    python_version = _load_python_version(workspace)
    ci_text = _read_text(workspace / ".github" / "workflows" / "ci.yml")
    docker_text = _read_text(workspace / "Dockerfile")
    readme_text = _read_text(workspace / "app" / "README.md")
    email_text = _read_text(workspace / "outgoing" / "community_email.txt")
    report_text = _read_text(workspace / "report" / "ci_fix_summary.txt")

    if python_version is not None and ci_text is not None:
        versions_in_ci = _extract_ci_python_versions(ci_text)
        if python_version in versions_in_ci:
            scores["ci_python_version_matches"] = 1.0
        else:
            scores["ci_python_version_matches"] = 0.0
    else:
        scores["ci_python_version_matches"] = 0.0

    if ci_text is not None and docker_text is not None:
        arg_names = _extract_dockerfile_args(docker_text)
        if arg_names:
            all_matched = True
            for arg in arg_names:
                if not _ci_contains_build_arg_with_secret(ci_text, arg):
                    all_matched = False
                    break
            scores["ci_build_arg_matches"] = 1.0 if all_matched else 0.0
        else:
            scores["ci_build_arg_matches"] = 0.0
    else:
        scores["ci_build_arg_matches"] = 0.0

    if readme_text is not None and python_version is not None:
        has_correct_version = _readme_contains_python_version(readme_text, python_version)
        contains_old_39 = "3.9" in readme_text
        scores["readme_python_version_updated"] = 1.0 if has_correct_version and not contains_old_39 else 0.0
    else:
        scores["readme_python_version_updated"] = 0.0

    if readme_text is not None:
        has_new_token = "COMMUNITY_API_TOKEN" in readme_text
        has_old_token = "SECRET_API_KEY" in readme_text
        scores["readme_token_name_updated"] = 1.0 if has_new_token and not has_old_token else 0.0

        has_ci_section_phrase = re.search(r"CI and Deployment Notes", readme_text, flags=re.IGNORECASE) is not None
        mentions_typed_ast = re.search(r"typed-ast", readme_text, flags=re.IGNORECASE) is not None
        scores["readme_ci_section_and_typed_ast"] = 1.0 if has_ci_section_phrase and mentions_typed_ast else 0.0
    else:
        scores["readme_token_name_updated"] = 0.0
        scores["readme_ci_section_and_typed_ast"] = 0.0

    if email_text is not None:
        fields = _read_email_fields(email_text)
        to_ok = (fields.get("To") == "diana@example.org")
        subj_ok = (fields.get("Subject") == "[Yale Service App] CI fix for token name and Python version")
        body_present = bool(fields.get("Body"))
        scores["email_fields_valid"] = 1.0 if (to_ok and subj_ok and body_present) else 0.0

        body = fields.get("Body") or ""
        sentence_count = _count_sentences(body)
        scores["email_sentence_count_valid"] = 1.0 if 4 <= sentence_count <= 6 else 0.0

        has_python_version_ref = ".python-version" in body
        has_dockerfile_ref = "Dockerfile" in body
        has_token_ref = ("token" in body.lower()) or ("COMMUNITY_API_TOKEN" in body)
        has_no_action = re.search(r"\bno action\b", body, flags=re.IGNORECASE) is not None
        has_deploy = re.search(r"\bdeploy", body, flags=re.IGNORECASE) is not None
        has_revert_commit = (re.search(r"\brevert\b", body, flags=re.IGNORECASE) is not None) and (re.search(r"\bcommit\b", body, flags=re.IGNORECASE) is not None)
        content_ok = all([has_python_version_ref, has_dockerfile_ref, has_token_ref, has_no_action, has_deploy, has_revert_commit])
        scores["email_content_includes_requirements"] = 1.0 if content_ok else 0.0
    else:
        scores["email_fields_valid"] = 0.0
        scores["email_sentence_count_valid"] = 0.0
        scores["email_content_includes_requirements"] = 0.0

    if report_text is not None:
        has_bullets = "- " in report_text
        mentions_ci_file = ".github/workflows/ci.yml" in report_text
        mentions_readme_file = "app/README.md" in report_text or "./app/README.md" in report_text
        scores["report_lists_changed_files"] = 1.0 if (has_bullets and mentions_ci_file and mentions_readme_file) else 0.0

        version_ok = False
        arg_ok = False
        if python_version is not None:
            version_ok = python_version in report_text
        if docker_text is not None:
            arg_names = _extract_dockerfile_args(docker_text)
            if arg_names:
                arg_ok = any(arg in report_text for arg in arg_names)
        scores["report_python_version_and_arg"] = 1.0 if (version_ok and arg_ok) else 0.0
    else:
        scores["report_lists_changed_files"] = 0.0
        scores["report_python_version_and_arg"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()