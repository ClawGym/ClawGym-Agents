import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_file(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_freeze(text: str) -> Dict[str, str]:
    freeze_map: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^\s*([A-Za-z0-9_.\-]+)==([^\s#]+)\s*$", line)
        if not m:
            continue
        name, version = m.group(1), m.group(2)
        freeze_map[name.lower()] = version
    return freeze_map


def extract_name_and_spec(line: str) -> Tuple[Optional[str], str]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return (None, "unpinned")
    m = re.match(r"^\s*([A-Za-z0-9_.\-]+)", stripped)
    if not m:
        return (None, "unpinned")
    name = m.group(1)
    remainder = stripped[len(m.group(0)):]
    if "==" in remainder:
        spec_type = "exact"
    elif re.search(r"(~=|>=|<=|<|>)", remainder):
        spec_type = "range"
    else:
        spec_type = "unpinned"
    return (name, spec_type)


def parse_requirements_top_level(text: str) -> List[Tuple[str, str, str]]:
    results: List[Tuple[str, str, str]] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, spec = extract_name_and_spec(stripped)
        if name is None:
            continue
        results.append((stripped, name, spec))
    return results


def compute_expected_lock_lines(reqs: List[Tuple[str, str, str]], freeze_map: Dict[str, str]) -> Tuple[List[str], Dict[str, Optional[str]]]:
    expected_lines: List[str] = []
    locked_versions: Dict[str, Optional[str]] = {}
    for original_line, name, _spec in reqs:
        lower = name.lower()
        if lower in freeze_map:
            version = freeze_map[lower]
            expected_line = f"{name}=={version}"
            expected_lines.append(expected_line)
            locked_versions[name] = version
        else:
            expected_line = f"{original_line}  # NOT_FOUND_IN_FREEZE"
            expected_lines.append(expected_line)
            locked_versions[name] = None
    return expected_lines, locked_versions


def compute_expected_stats(
    reqs: List[Tuple[str, str, str]],
    freeze_map: Dict[str, str],
    locked_versions: Dict[str, Optional[str]]
) -> dict:
    total_top_level = len(reqs)
    pinned_from_freeze = sum(1 for _, v in locked_versions.items() if v is not None)
    missing_in_freeze = total_top_level - pinned_from_freeze
    coverage_rate = (pinned_from_freeze / total_top_level) if total_top_level > 0 else 0.0

    spec_counts = {"exact": 0, "range": 0, "unpinned": 0}
    for _orig, _name, spec in reqs:
        if spec in spec_counts:
            spec_counts[spec] += 1

    top_names_lower = {name.lower() for _orig, name, _spec in reqs}
    freeze_names_lower = set(freeze_map.keys())
    extra_freeze_packages = len(freeze_names_lower - top_names_lower)

    locked_versions_out = {}
    for _orig, name, _spec in reqs:
        locked_versions_out[name] = locked_versions.get(name, None)

    stats = {
        "total_top_level": total_top_level,
        "pinned_from_freeze": pinned_from_freeze,
        "missing_in_freeze": missing_in_freeze,
        "coverage_rate": float(coverage_rate),
        "spec_counts": spec_counts,
        "extra_freeze_packages": extra_freeze_packages,
        "locked_versions": locked_versions_out,
    }
    return stats


def compare_float(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def readme_expected_outside() -> Tuple[str, str]:
    # Expected original README content outside markers from the provided task inputs.
    prefix = (
        "# Sample App\n\n"
        "This is a demo app I use for personal scripts.\n\n"
        "## Install\n"
    )
    suffix = (
        "\n\n## Notes\n\n"
        "- Python 3 is fine.\n"
        "- I don't care about the newest features.\n"
    )
    return prefix, suffix


def readme_inner_has_numbers_line(inner: str, total: int, pinned: int, coverage: float) -> bool:
    # Require that a single line (one sentence) mentions all three numbers.
    total_str = str(total)
    pinned_str = str(pinned)
    cov_str = str(float(coverage))
    for line in inner.splitlines():
        if total_str in line and pinned_str in line and cov_str in line:
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "constraints_copied_exactly": 0.0,
        "requirements_lock_correct": 0.0,
        "stats_json_correct": 0.0,
        "readme_markers_and_outside_unchanged": 0.0,
        "readme_contains_install_command": 0.0,
        "readme_mentions_numbers_matching_stats": 0.0,
    }

    input_dir = workspace / "input"
    output_dir = workspace / "output"
    req_path = input_dir / "requirements.txt"
    freeze_path = input_dir / "freeze.txt"
    readme_path = input_dir / "README.md"

    constraints_path = output_dir / "constraints.txt"
    lock_path = output_dir / "requirements.lock.txt"
    stats_path = output_dir / "stats.json"

    req_text = read_text_file(req_path)
    freeze_text = read_text_file(freeze_path)

    # Check constraints: exact copy of freeze
    constraints_text = read_text_file(constraints_path)
    if freeze_text is not None and constraints_text is not None and constraints_text == freeze_text:
        scores["constraints_copied_exactly"] = 1.0

    # Prepare expected lock and stats from inputs
    expected_lock_lines: Optional[List[str]] = None
    expected_stats: Optional[dict] = None
    if req_text is not None and freeze_text is not None:
        reqs = parse_requirements_top_level(req_text)
        freeze_map = parse_freeze(freeze_text)
        exp_lines, locked_versions = compute_expected_lock_lines(reqs, freeze_map)
        expected_lock_lines = exp_lines
        expected_stats = compute_expected_stats(reqs, freeze_map, locked_versions)

    # Check requirements.lock content
    lock_text = read_text_file(lock_path)
    if expected_lock_lines is not None and lock_text is not None:
        actual_lines = [ln.strip() for ln in lock_text.splitlines()]
        if actual_lines == expected_lock_lines:
            scores["requirements_lock_correct"] = 1.0

    # Check stats.json correctness
    stats_json = load_json_file(stats_path)
    if expected_stats is not None and stats_json is not None and isinstance(stats_json, dict):
        ok = True
        req_keys = {
            "total_top_level",
            "pinned_from_freeze",
            "missing_in_freeze",
            "coverage_rate",
            "spec_counts",
            "extra_freeze_packages",
            "locked_versions",
        }
        if set(stats_json.keys()) != req_keys:
            ok = False
        else:
            if stats_json.get("total_top_level") != expected_stats["total_top_level"]:
                ok = False
            if stats_json.get("pinned_from_freeze") != expected_stats["pinned_from_freeze"]:
                ok = False
            if stats_json.get("missing_in_freeze") != expected_stats["missing_in_freeze"]:
                ok = False
            cov_actual = stats_json.get("coverage_rate")
            try:
                cov_actual_f = float(cov_actual)
            except Exception:
                ok = False
                cov_actual_f = None
            if ok and not compare_float(cov_actual_f, expected_stats["coverage_rate"]):
                ok = False
            if stats_json.get("spec_counts") != expected_stats["spec_counts"]:
                ok = False
            if stats_json.get("extra_freeze_packages") != expected_stats["extra_freeze_packages"]:
                ok = False
            if stats_json.get("locked_versions") != expected_stats["locked_versions"]:
                ok = False
        scores["stats_json_correct"] = 1.0 if ok else 0.0

    # README checks - gated on stats.json correctness to avoid awarding in scaffold workspaces
    readme_text = read_text_file(readme_path)
    if readme_text is not None and scores["stats_json_correct"] == 1.0:
        start_marker = "<!-- install-start -->"
        end_marker = "<!-- install-end -->"

        s_idx = readme_text.find(start_marker)
        e_idx = readme_text.find(end_marker)

        if s_idx != -1 and e_idx != -1 and e_idx > s_idx:
            prefix_actual = readme_text[:s_idx]
            inner_actual = readme_text[s_idx + len(start_marker):e_idx]
            suffix_actual = readme_text[e_idx + len(end_marker):]

            expected_prefix, expected_suffix = readme_expected_outside()
            outside_ok = (prefix_actual == expected_prefix) and (suffix_actual == expected_suffix)

            # Check for "Locked Environment Setup" and command
            inner_lower = inner_actual.lower()
            has_locked_heading = "locked environment setup" in inner_lower
            command = "pip install -r output/requirements.lock.txt -c output/constraints.txt"
            has_command = command in inner_actual

            if outside_ok and has_locked_heading and has_command:
                scores["readme_markers_and_outside_unchanged"] = 1.0
                scores["readme_contains_install_command"] = 1.0
            else:
                # If the command or heading missing, do not award either of the two checks
                scores["readme_markers_and_outside_unchanged"] = 0.0
                scores["readme_contains_install_command"] = 0.0

            # Numbers mention check: must include all three values in one line
            if isinstance(stats_json, dict):
                total = stats_json.get("total_top_level")
                pinned = stats_json.get("pinned_from_freeze")
                coverage = stats_json.get("coverage_rate")
                try:
                    coverage_f = float(coverage)
                except Exception:
                    coverage_f = None
                if (
                    isinstance(total, int)
                    and isinstance(pinned, int)
                    and coverage_f is not None
                    and readme_inner_has_numbers_line(inner_actual, total, pinned, coverage_f)
                ):
                    scores["readme_mentions_numbers_matching_stats"] = 1.0
                else:
                    scores["readme_mentions_numbers_matching_stats"] = 0.0
        else:
            # Markers missing or malformed
            scores["readme_markers_and_outside_unchanged"] = 0.0
            scores["readme_contains_install_command"] = 0.0
            scores["readme_mentions_numbers_matching_stats"] = 0.0
    else:
        # If stats are incorrect or README missing, all readme checks should be 0
        scores["readme_markers_and_outside_unchanged"] = 0.0
        scores["readme_contains_install_command"] = 0.0
        scores["readme_mentions_numbers_matching_stats"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()