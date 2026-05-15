import json
import re
import sys
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Set


def _read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json_file(path: Path) -> Optional[dict]:
    try:
        txt = _read_text_file(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _scan_files(base: Path, relative_dir: str, suffix: str) -> List[Path]:
    root = base / relative_dir
    if not root.exists() or not root.is_dir():
        return []
    return sorted([p for p in root.rglob(f"*{suffix}") if p.is_file()])


def _extract_java_types_from_text(text: str, file_path: Path) -> List[Tuple[str, str, bool, str]]:
    """
    Return list of tuples: (fully_qualified_name, simple_name, is_ignored, package_name)
    Excludes anything under com.example.annotations and excludes annotation types (@interface).
    A type is considered @DiagramIgnore if the annotation appears before the type declaration.
    Only top-level class/interface declarations are considered.
    """
    results: List[Tuple[str, str, bool, str]] = []
    if text is None:
        return results

    # Package
    pkg_match = re.search(r'^\s*package\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;', text, flags=re.MULTILINE)
    package_name = pkg_match.group(1) if pkg_match else ""
    if package_name == "com.example.annotations":
        return results  # exclude whole package

    # Find top-level type declarations (class|interface but not @interface)
    decl_pattern = re.compile(
        r'^(?P<prefix>\s*(?:public|protected|private|abstract|final|static|\s)*)'
        r'(?:(?P<classkw>class)|(?P<intkw>(?<!@)interface))\s+'
        r'(?P<name>[A-Za-z_]\w*)\b',
        flags=re.MULTILINE
    )

    for m in decl_pattern.finditer(text):
        simple_name = m.group("name")

        # Determine if @DiagramIgnore applies: appears before this declaration.
        before_text = text[:m.start()]
        is_ignored = bool(re.search(r'@DiagramIgnore\b', before_text))

        if not package_name:
            fqn = simple_name
        else:
            fqn = f"{package_name}.{simple_name}"

        results.append((fqn, simple_name, is_ignored, package_name))

    return results


def _extract_puml_types_from_text(text: str) -> Set[str]:
    """
    Extract simple type names from lines explicitly declaring types:
    lines starting with 'class ', 'interface ', or 'abstract class ' (ignoring leading whitespace).
    Ignore lines that are comments starting with apostrophe '.
    """
    types: Set[str] = set()
    if text is None:
        return types
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("'"):
            continue
        m = re.match(r'^(?:abstract\s+class|class|interface)\s+([A-Za-z_][A-Za-z0-9_]*)\b', stripped)
        if m:
            types.add(m.group(1))
    return types


def _compute_expected(workspace: Path) -> Dict[str, object]:
    # Scan files
    java_paths = _scan_files(workspace, "src/main/java", ".java")
    puml_paths = _scan_files(workspace, "docs/diagrams", ".puml")

    # Extract java types
    code_entries: List[Tuple[str, str, bool, str]] = []
    for jp in java_paths:
        text = _read_text_file(jp)
        if text is None:
            continue
        code_entries.extend(_extract_java_types_from_text(text, jp))

    # Build code_classes (FQN) excluding annotation types already; also excluding com.example.annotations already.
    code_classes_fqn = sorted({fqn for (fqn, simple, ignored, pkg) in code_entries})

    # For coverage/discrepancy, exclude those annotated with @DiagramIgnore
    code_types_for_coverage: Set[str] = {simple for (fqn, simple, ignored, pkg) in code_entries if not ignored}

    # Extract diagram types
    diagram_types: Set[str] = set()
    for dp in puml_paths:
        text = _read_text_file(dp)
        if text is None:
            continue
        diagram_types |= _extract_puml_types_from_text(text)

    # Compute discrepancies
    missing_in_diagrams = sorted(code_types_for_coverage - diagram_types)
    missing_in_code = sorted(diagram_types - code_types_for_coverage)

    # Coverage
    total_code = len(code_types_for_coverage)
    if total_code == 0:
        coverage = 100.0
    else:
        covered = len(code_types_for_coverage & diagram_types)
        coverage = round((covered / total_code) * 100.0, 1)

    passed = coverage >= 75.0

    # Sources lists as relative POSIX paths
    java_rel = [p.relative_to(workspace).as_posix() for p in java_paths]
    diagram_rel = [p.relative_to(workspace).as_posix() for p in puml_paths]

    # Diagram classes sorted ascending (simple names)
    diagram_classes_sorted = sorted(diagram_types)

    expected = {
        "code_classes_fqn": code_classes_fqn,
        "diagram_classes": diagram_classes_sorted,
        "missing_in_diagrams": missing_in_diagrams,
        "missing_in_code": missing_in_code,
        "coverage_percent": coverage,
        "pass_flag": passed,
        "sources_java_files": java_rel,
        "sources_diagram_files": diagram_rel,
    }
    return expected


def _compare_lists_exact(a: List[str], b: List[str]) -> bool:
    return a == b


def _contains_all(text: str, items: List[str]) -> bool:
    return all(item in text for item in items)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "output_json_exists": 0.0,
        "output_json_valid": 0.0,
        "json_code_classes_correct": 0.0,
        "json_diagram_classes_correct": 0.0,
        "json_missing_in_diagrams_correct": 0.0,
        "json_missing_in_code_correct": 0.0,
        "json_coverage_percent_correct": 0.0,
        "json_pass_flag_correct": 0.0,
        "json_sources_java_files_correct": 0.0,
        "json_sources_diagram_files_correct": 0.0,
        "review_md_exists": 0.0,
        "review_md_mentions_coverage_and_judgment": 0.0,
        "review_md_lists_discrepancies": 0.0,
        "review_md_has_recommendations": 0.0,
        "email_exists": 0.0,
        "email_subject_correct": 0.0,
        "email_mentions_coverage_and_result": 0.0,
        "email_lists_missing_types": 0.0,
        "email_mentions_diagramignore_note": 0.0,
        "email_requests_actions": 0.0,
    }

    expected = _compute_expected(workspace)

    # Paths
    output_dir = workspace / "output"
    json_path = output_dir / "model_review.json"
    review_md_path = output_dir / "review.md"
    email_path = output_dir / "email_to_team.txt"

    # Check JSON deliverable
    json_data = _load_json_file(json_path)
    if json_path.exists() and json_path.is_file():
        scores["output_json_exists"] = 1.0
    if json_data is not None and isinstance(json_data, dict):
        # Validate exact keys
        expected_keys = {
            "code_classes",
            "diagram_classes",
            "missing_in_diagrams",
            "missing_in_code",
            "coverage_percent",
            "pass",
            "sources",
        }
        if set(json_data.keys()) == expected_keys and isinstance(json_data.get("sources"), dict) and set(json_data["sources"].keys()) == {"java_files", "diagram_files"}:
            scores["output_json_valid"] = 1.0

            # Check values
            # code_classes
            code_classes = json_data.get("code_classes")
            if isinstance(code_classes, list) and all(isinstance(x, str) for x in code_classes):
                if _compare_lists_exact(code_classes, expected["code_classes_fqn"]):
                    scores["json_code_classes_correct"] = 1.0

            # diagram_classes
            diagram_classes = json_data.get("diagram_classes")
            if isinstance(diagram_classes, list) and all(isinstance(x, str) for x in diagram_classes):
                if _compare_lists_exact(diagram_classes, expected["diagram_classes"]):
                    scores["json_diagram_classes_correct"] = 1.0

            # missing_in_diagrams
            mid = json_data.get("missing_in_diagrams")
            if isinstance(mid, list) and all(isinstance(x, str) for x in mid):
                if _compare_lists_exact(mid, expected["missing_in_diagrams"]):
                    scores["json_missing_in_diagrams_correct"] = 1.0

            # missing_in_code
            mic = json_data.get("missing_in_code")
            if isinstance(mic, list) and all(isinstance(x, str) for x in mic):
                if _compare_lists_exact(mic, expected["missing_in_code"]):
                    scores["json_missing_in_code_correct"] = 1.0

            # coverage_percent
            cov = json_data.get("coverage_percent")
            if isinstance(cov, (int, float)):
                if float(cov) == float(expected["coverage_percent"]):
                    scores["json_coverage_percent_correct"] = 1.0

            # pass flag
            pf = json_data.get("pass")
            if isinstance(pf, bool):
                if pf == expected["pass_flag"]:
                    scores["json_pass_flag_correct"] = 1.0

            # sources
            sources = json_data.get("sources", {})
            java_files = sources.get("java_files")
            diagram_files = sources.get("diagram_files")
            if isinstance(java_files, list) and all(isinstance(x, str) for x in java_files):
                if _compare_lists_exact(java_files, expected["sources_java_files"]):
                    scores["json_sources_java_files_correct"] = 1.0
            if isinstance(diagram_files, list) and all(isinstance(x, str) for x in diagram_files):
                if _compare_lists_exact(diagram_files, expected["sources_diagram_files"]):
                    scores["json_sources_diagram_files_correct"] = 1.0

    # Check review.md
    review_text = _read_text_file(review_md_path)
    if review_md_path.exists() and review_md_path.is_file():
        scores["review_md_exists"] = 1.0
    if review_text is not None:
        cov_str = f"{expected['coverage_percent']:.1f}"
        has_cov = cov_str in review_text
        expected_result_word = "pass" if expected["pass_flag"] else "fail"
        has_result = expected_result_word.lower() in review_text.lower()
        if has_cov and has_result:
            scores["review_md_mentions_coverage_and_judgment"] = 1.0

        # discrepancies listed
        all_missing_names = expected["missing_in_diagrams"] + expected["missing_in_code"]
        if _contains_all(review_text, all_missing_names):
            scores["review_md_lists_discrepancies"] = 1.0

        # recommendations presence: check for suggestive words
        text_low = review_text.lower()
        if ("recommend" in text_low or "should" in text_low or "suggest" in text_low or "consider" in text_low
            or ("add" in text_low and "diagram" in text_low) or "implement" in text_low):
            scores["review_md_has_recommendations"] = 1.0

    # Check email
    email_text = _read_text_file(email_path)
    if email_path.exists() and email_path.is_file():
        scores["email_exists"] = 1.0
    if email_text is not None:
        lines = email_text.splitlines()
        first_line = lines[0] if lines else ""
        if first_line.startswith("Subject: ") and "Diagram coverage review for billing module" in first_line:
            scores["email_subject_correct"] = 1.0

        cov_str = f"{expected['coverage_percent']:.1f}"
        expected_result_word = "pass" if expected["pass_flag"] else "fail"
        body_text = email_text
        if (cov_str in body_text) and (expected_result_word.lower() in body_text.lower()):
            scores["email_mentions_coverage_and_result"] = 1.0

        # lists missing types
        all_missing_names = expected["missing_in_diagrams"] + expected["missing_in_code"]
        if _contains_all(body_text, all_missing_names):
            scores["email_lists_missing_types"] = 1.0

        # mentions @DiagramIgnore
        if "@DiagramIgnore" in body_text:
            scores["email_mentions_diagramignore_note"] = 1.0

        # requests actions: add to diagrams and remove/implement
        body_low = body_text.lower()
        if ("add" in body_low and "diagram" in body_low) and ("remove" in body_low and "implement" in body_low):
            scores["email_requests_actions"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()