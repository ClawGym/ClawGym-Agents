import json
import sys
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional


ALLOWED_DIRS = ["docs", "studio", "artworks", "references", "assets"]


def safe_read_text(path: Path) -> Tuple[Optional[str], bool]:
    try:
        return path.read_text(encoding="utf-8"), True
    except Exception:
        return None, False


def safe_read_bytes(path: Path) -> Tuple[Optional[bytes], bool]:
    try:
        return path.read_bytes(), True
    except Exception:
        return None, False


def safe_load_json(path: Path) -> Tuple[Optional[dict], bool]:
    content, ok = safe_read_text(path)
    if not ok or content is None:
        return None, False
    try:
        return json.loads(content), True
    except Exception:
        return None, False


def list_files_in_dir(root: Path, dir_name: str) -> List[Path]:
    base = root / dir_name
    if not base.exists() or not base.is_dir():
        return []
    return sorted([p for p in base.rglob("*") if p.is_file()])


def compute_inventory(workspace: Path) -> Tuple[Dict, Dict[str, List[str]]]:
    files_by_dir: Dict[str, List[Path]] = {}
    for d in ALLOWED_DIRS:
        files_by_dir[d] = list_files_in_dir(workspace, d)

    counts_by_dir = {d: len(files_by_dir[d]) for d in ALLOWED_DIRS}

    # Build relative paths for each file and compute total size
    rel_paths_by_dir: Dict[str, List[str]] = {}
    total_files = 0
    total_size_bytes = 0
    counts_by_ext: Dict[str, int] = {}

    for d in ALLOWED_DIRS:
        rels: List[str] = []
        for p in files_by_dir[d]:
            rel = p.relative_to(workspace).as_posix()
            rels.append(rel)
            # size in bytes
            data, okb = safe_read_bytes(p)
            if okb and data is not None:
                total_size_bytes += len(data)
            else:
                # If unreadable, count as 0 bytes but still count as file
                total_size_bytes += 0
            # extension (lower-cased)
            ext = p.suffix.lower()
            counts_by_ext[ext] = counts_by_ext.get(ext, 0) + 1
            total_files += 1
        rel_paths_by_dir[d] = sorted(rels)

    inventory = {
        "total_files": total_files,
        "total_size_bytes": total_size_bytes,
        "counts_by_dir": counts_by_dir,
        "counts_by_ext": counts_by_ext,
    }
    return inventory, rel_paths_by_dir


def parse_open_tasks(project_plan_path: Path) -> Tuple[Optional[List[str]], bool]:
    content, ok = safe_read_text(project_plan_path)
    if not ok or content is None:
        return None, False
    open_tasks: List[str] = []
    for line in content.splitlines():
        if line.startswith("- [ ] "):
            task_text = line[len("- [ ] "):].strip()
            open_tasks.append(task_text)
    return open_tasks, True


def parse_manifest_required_files(manifest_path: Path) -> Tuple[Optional[List[str]], bool]:
    manifest, ok = safe_load_json(manifest_path)
    if not ok or manifest is None:
        return None, False
    if not isinstance(manifest, dict) or "required_files" not in manifest or not isinstance(manifest["required_files"], list):
        return None, False
    # Filter to strings
    reqs = []
    for item in manifest["required_files"]:
        if isinstance(item, str):
            reqs.append(item)
        else:
            # Malformed manifest entry
            return None, False
    return reqs, True


def compute_missing_files(workspace: Path, required_files: List[str]) -> List[str]:
    missing: List[str] = []
    for rel in required_files:
        p = workspace / rel
        if not p.exists() or not p.is_file():
            missing.append(rel)
    return sorted(missing)


def check_report_totals(content: str, total_files: int, total_size: int) -> bool:
    tf_line = f"Total files: {total_files}"
    ts_line = f"Total size (bytes): {total_size}"
    return (tf_line in content) and (ts_line in content)


def check_report_inventory(content: str, rel_paths_by_dir: Dict[str, List[str]], counts_by_dir: Dict[str, int]) -> bool:
    ok = True
    for d in ALLOWED_DIRS:
        # Bullet like "- DIRNAME: N files"
        header_line = f"- {d}: {counts_by_dir.get(d, 0)} files"
        if header_line not in content:
            ok = False
            continue
        # For each file in this directory, there should be an indented bullet "  - <path>"
        for rel in rel_paths_by_dir.get(d, []):
            expected_line = f"  - {rel}"
            if expected_line not in content:
                ok = False
    return ok


def check_report_missing_list(content: str, missing_files: List[str]) -> bool:
    if not missing_files:
        # Expect a single line "- None"
        return "- None" in content
    # Expect each missing file as "- path"
    for rel in missing_files:
        line = f"- {rel}"
        if line not in content:
            return False
    return True


def check_report_open_tasks_list(content: str, open_tasks: List[str]) -> bool:
    if not open_tasks:
        return "- None" in content
    for t in open_tasks:
        line = f"- {t}"
        if line not in content:
            return False
    return True


def extract_latest_status_section(readme_text: str) -> Tuple[Optional[str], bool, bool]:
    """
    Returns (section_text, present, at_top)
    section_text includes content from the 'Latest Status' heading until the next heading or EOF.
    """
    lines = readme_text.splitlines()
    # Find first non-empty line
    first_non_empty_idx = None
    for i, l in enumerate(lines):
        if l.strip() != "":
            first_non_empty_idx = i
            break
    at_top = False
    present = False
    section_text = None

    # Find heading lines
    heading_indices = []
    for i, l in enumerate(lines):
        if re.match(r"^\s{0,3}#{1,6}\s+.+", l):
            heading_indices.append(i)

    latest_idx = None
    for i, l in enumerate(lines):
        if re.match(r"^\s{0,3}#{1,6}\s+Latest Status\s*$", l, flags=re.IGNORECASE):
            latest_idx = i
            present = True
            break

    if present and latest_idx is not None:
        # Determine end index: next heading after latest_idx
        end_idx = len(lines)
        for idx in heading_indices:
            if idx > latest_idx:
                end_idx = idx
                break
        section_text = "\n".join(lines[latest_idx:end_idx]).strip()
        if first_non_empty_idx is not None and first_non_empty_idx == latest_idx:
            at_top = True

    return section_text, present, at_top


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "inventory_json_present": 0.0,
        "inventory_json_fields_exact": 0.0,
        "inventory_json_totals_match_workspace": 0.0,
        "inventory_json_counts_by_dir_match": 0.0,
        "inventory_json_counts_by_ext_match": 0.0,
        "inventory_json_missing_files_match": 0.0,
        "inventory_json_open_tasks_match": 0.0,
        "report_present": 0.0,
        "report_overview_totals_correct": 0.0,
        "report_inventory_blocks_correct": 0.0,
        "report_missing_list_correct": 0.0,
        "report_open_tasks_list_correct": 0.0,
        "report_placeholders_replaced": 0.0,
        "report_team_summary_written": 0.0,
        "readme_latest_status_section_present": 0.0,
        "readme_latest_status_at_top": 0.0,
        "readme_latest_status_contains_numbers": 0.0,
        "readme_latest_status_contains_link": 0.0,
    }

    # Compute expected inventory from workspace
    inventory_data, rel_paths_by_dir = compute_inventory(workspace)
    expected_total_files = inventory_data["total_files"]
    expected_total_size = inventory_data["total_size_bytes"]
    expected_counts_by_dir = inventory_data["counts_by_dir"]
    expected_counts_by_ext = inventory_data["counts_by_ext"]

    # Compute expected open tasks
    open_tasks_expected: Optional[List[str]] = None
    open_tasks_ok = False
    project_plan_path = workspace / "studio" / "project_plan.md"
    open_tasks_expected, open_tasks_ok = parse_open_tasks(project_plan_path)

    # Compute expected missing files
    manifest_path = workspace / "studio" / "manifest.json"
    required_files, manifest_ok = parse_manifest_required_files(manifest_path)
    missing_files_expected: Optional[List[str]] = None
    if manifest_ok and required_files is not None:
        missing_files_expected = compute_missing_files(workspace, required_files)

    # Check outputs/inventory.json
    inv_json_path = workspace / "outputs" / "inventory.json"
    inv_json, inv_present = safe_load_json(inv_json_path)
    if inv_present and isinstance(inv_json, dict):
        scores["inventory_json_present"] = 1.0
        # Check fields exactly
        expected_keys = {
            "total_files",
            "total_size_bytes",
            "counts_by_dir",
            "counts_by_ext",
            "missing_files",
            "open_tasks",
        }
        if set(inv_json.keys()) == expected_keys:
            # Validate types and nested fields
            types_ok = (
                isinstance(inv_json.get("total_files"), int)
                and isinstance(inv_json.get("total_size_bytes"), int)
                and isinstance(inv_json.get("counts_by_dir"), dict)
                and isinstance(inv_json.get("counts_by_ext"), dict)
                and isinstance(inv_json.get("missing_files"), list)
                and isinstance(inv_json.get("open_tasks"), list)
            )
            # counts_by_dir should include exactly the five keys
            dir_keys_ok = False
            if isinstance(inv_json.get("counts_by_dir"), dict):
                dir_keys_ok = set(inv_json["counts_by_dir"].keys()) == set(ALLOWED_DIRS)
            if types_ok and dir_keys_ok:
                scores["inventory_json_fields_exact"] = 1.0

            # Compare totals
            if inv_json.get("total_files") == expected_total_files and inv_json.get("total_size_bytes") == expected_total_size:
                scores["inventory_json_totals_match_workspace"] = 1.0

            # Compare counts_by_dir
            if isinstance(inv_json.get("counts_by_dir"), dict):
                if all(
                    isinstance(inv_json["counts_by_dir"].get(k), int) and inv_json["counts_by_dir"].get(k) == expected_counts_by_dir.get(k, 0)
                    for k in ALLOWED_DIRS
                ):
                    scores["inventory_json_counts_by_dir_match"] = 1.0

            # Compare counts_by_ext
            if isinstance(inv_json.get("counts_by_ext"), dict):
                # Normalize keys to strings and integers
                ext_ok = True
                # We consider exact mapping equality
                if set(inv_json["counts_by_ext"].keys()) != set(expected_counts_by_ext.keys()):
                    ext_ok = False
                else:
                    for k, v in expected_counts_by_ext.items():
                        if inv_json["counts_by_ext"].get(k) != v:
                            ext_ok = False
                            break
                if ext_ok:
                    scores["inventory_json_counts_by_ext_match"] = 1.0

            # Compare missing_files
            if missing_files_expected is not None:
                if isinstance(inv_json.get("missing_files"), list):
                    try:
                        inv_missing_sorted = sorted([str(x) for x in inv_json["missing_files"]])
                        expected_missing_sorted = sorted(missing_files_expected)
                        if inv_missing_sorted == expected_missing_sorted:
                            scores["inventory_json_missing_files_match"] = 1.0
                    except Exception:
                        pass

            # Compare open_tasks
            if open_tasks_ok and open_tasks_expected is not None:
                if isinstance(inv_json.get("open_tasks"), list):
                    try:
                        inv_open_sorted = sorted([str(x) for x in inv_json["open_tasks"]])
                        expected_open_sorted = sorted(open_tasks_expected)
                        if inv_open_sorted == expected_open_sorted:
                            scores["inventory_json_open_tasks_match"] = 1.0
                    except Exception:
                        pass

    # Check outputs/studio_status_report.md
    report_path = workspace / "outputs" / "studio_status_report.md"
    report_text, report_ok = safe_read_text(report_path)
    if report_ok and report_text is not None:
        scores["report_present"] = 1.0
        # Totals in overview
        if check_report_totals(report_text, expected_total_files, expected_total_size):
            scores["report_overview_totals_correct"] = 1.0

        # Inventory blocks
        if check_report_inventory(report_text, rel_paths_by_dir, expected_counts_by_dir):
            scores["report_inventory_blocks_correct"] = 1.0

        # Missing files list
        if missing_files_expected is not None:
            if check_report_missing_list(report_text, missing_files_expected):
                scores["report_missing_list_correct"] = 1.0

        # Open tasks list
        if open_tasks_ok and open_tasks_expected is not None:
            if check_report_open_tasks_list(report_text, open_tasks_expected):
                scores["report_open_tasks_list_correct"] = 1.0

        # Placeholders replaced
        placeholders = ["{{TOTAL_FILES}}", "{{TOTAL_SIZE_BYTES}}", "{{INVENTORY_LIST}}", "{{MISSING_LIST}}", "{{OPEN_TASKS_LIST}}"]
        if not any(ph in report_text for ph in placeholders):
            scores["report_placeholders_replaced"] = 1.0

        # Team summary written (not the template placeholder, and non-empty text following "Team summary:")
        ts_idx = report_text.find("Team summary:")
        if ts_idx != -1:
            after = report_text[ts_idx + len("Team summary:"):].strip()
            # Should not contain the exact placeholder sentence
            if "Write a short paragraph here summarizing overall readiness for critique and next actions." not in after:
                # Consider it written if there's at least one non-empty line and > 20 characters
                # (heuristic to ensure substance)
                lines_after = [l for l in after.splitlines() if l.strip() != ""]
                if len(after) >= 20 and len(lines_after) >= 1:
                    scores["report_team_summary_written"] = 1.0

    # Check docs/README.md modifications
    readme_path = workspace / "docs" / "README.md"
    readme_text, readme_ok = safe_read_text(readme_path)
    if readme_ok and readme_text is not None:
        section_text, present, at_top = extract_latest_status_section(readme_text)
        if present:
            scores["readme_latest_status_section_present"] = 1.0
        if present and at_top:
            scores["readme_latest_status_at_top"] = 1.0
        if present and section_text is not None:
            # Check that the section contains the required numbers
            has_total_files = str(expected_total_files) in section_text
            has_total_size = str(expected_total_size) in section_text
            # counts of missing_files and open_tasks
            missing_count = len(missing_files_expected) if missing_files_expected is not None else None
            open_count = len(open_tasks_expected) if open_tasks_expected is not None else None

            has_missing_count = False
            has_open_count = False
            if missing_count is not None:
                has_missing_count = str(missing_count) in section_text
            if open_count is not None:
                has_open_count = str(open_count) in section_text

            if has_total_files and has_total_size and (missing_count is None or has_missing_count) and (open_count is None or has_open_count):
                scores["readme_latest_status_contains_numbers"] = 1.0

            # Check link to outputs/studio_status_report.md
            if "outputs/studio_status_report.md" in section_text:
                scores["readme_latest_status_contains_link"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()