import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_json_load(path: Path) -> Optional[dict]:
    try:
        text = safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def find_markdown_files(root: Path, subdirs: List[str]) -> List[Path]:
    files: List[Path] = []
    for sd in subdirs:
        dir_path = root / sd
        if not dir_path.exists():
            continue
        for p in dir_path.rglob("*.md"):
            if p.is_file():
                files.append(p)
    return sorted(files)


def count_todo_occurrences(text: str) -> int:
    # Case-sensitive occurrences of "TODO:"
    return text.count("TODO:")


def extract_citation_keys(text: str) -> List[str]:
    # Find patterns like [@key] and [@key1; @key2] - capture all @keys inside brackets
    keys: List[str] = []
    for m in re.finditer(r"\[([^\]]+)\]", text):
        inner = m.group(1)
        for k in re.findall(r"@([A-Za-z0-9_:-]+)", inner):
            keys.append(k)
    return keys


def extract_local_links(text: str) -> List[str]:
    # Capture markdown links and images: [text](path) or ![text](path)
    # Return only relative targets starting with ../ or ./
    links: List[str] = []
    for m in re.finditer(r"!?\[[^\]]*\]\(([^)]+)\)", text):
        target = m.group(1).strip()
        if target.startswith("../") or target.startswith("./"):
            links.append(target)
    return links


def compute_file_scan(path: Path, citations_keys: Optional[Set[str]]) -> Dict[str, object]:
    text = safe_read_text(path) or ""
    todos = count_todo_occurrences(text)
    cited_keys = extract_citation_keys(text)
    missing_keys: List[str] = []
    if citations_keys is None:
        # Cannot compute missing keys deterministically if citations.json missing/malformed
        missing_keys = None  # type: ignore
    else:
        missing_keys = sorted({k for k in cited_keys if k not in citations_keys})
    rel_links = extract_local_links(text)
    # Resolve link paths relative to the markdown file's directory
    broken_links: List[str] = []
    for t in rel_links:
        target_path = (path.parent / t).resolve()
        # Ensure target is still within workspace by not enforcing, just existence check
        if not target_path.exists():
            broken_links.append(t)
    # Unique list for listing
    broken_links_unique = sorted(set(broken_links))
    result: Dict[str, object] = {
        "todos": todos,
        "cited_keys": cited_keys,
        "missing_keys": missing_keys,
        "rel_links": rel_links,
        "broken_links": broken_links_unique,
    }
    return result


def get_report_sections(text: str) -> Dict[str, Tuple[int, int]]:
    # Return approximate section bounds by header keywords
    lines = text.splitlines()
    sections: Dict[str, Tuple[int, int]] = {}
    # Find indices of header markers by keywords
    exec_idx = None
    perfile_idx = None
    agg_idx = None
    for i, line in enumerate(lines):
        low = line.lower()
        if exec_idx is None and "executive summary" in low:
            exec_idx = i
        if perfile_idx is None and "per-file checks" in low:
            perfile_idx = i
        if agg_idx is None and "aggregate totals" in low:
            agg_idx = i
    total_lines = len(lines)
    if exec_idx is not None:
        end = perfile_idx if perfile_idx is not None else total_lines
        sections["executive"] = (exec_idx, end)
    if perfile_idx is not None:
        end = agg_idx if agg_idx is not None else total_lines
        sections["perfile"] = (perfile_idx, end)
    if agg_idx is not None:
        sections["aggregate"] = (agg_idx, total_lines)
    return sections


def extract_words_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def normalize_rel(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root)
        return rel.as_posix()
    except Exception:
        return path.as_posix()


def find_line_index_with_substring(lines: List[str], substring: str) -> int:
    for i, line in enumerate(lines):
        if substring in line:
            return i
    return -1


def parse_int_from_line(line: str) -> Optional[int]:
    m = re.search(r"([-+]?\d+)", line)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "report_file_exists_and_sections": 0.0,
        "report_exec_summary_quality": 0.0,
        "report_per_file_notes_critique_outline_correct": 0.0,
        "report_per_file_drafts_essay_heian_correct": 0.0,
        "report_per_file_drafts_essay_kofun_correct": 0.0,
        "report_aggregate_totals_correct": 0.0,
        "critique_outline_status_line_updated": 0.0,
        "critique_outline_status_update_section_position": 0.0,
        "critique_outline_status_update_bullets_correct": 0.0,
    }

    # Compute expected scan results from workspace
    md_files = find_markdown_files(workspace, ["notes", "drafts"])
    citations_path = workspace / "sources" / "citations.json"
    citations_data = safe_json_load(citations_path)
    citations_keys: Optional[Set[str]] = None
    if citations_data is not None and isinstance(citations_data, dict):
        citations_keys = set(citations_data.keys())

    # Build expected per-file info
    per_file_expected: Dict[str, Dict[str, object]] = {}
    for p in md_files:
        rel = normalize_rel(p, workspace)
        per_file_expected[rel] = compute_file_scan(p, citations_keys)

    # Aggregate expected totals
    total_markdown_files_scanned = len(md_files)
    total_todos = 0
    total_broken_local_links = 0
    all_missing_keys: Set[str] = set()
    for rel, data in per_file_expected.items():
        total_todos += int(data.get("todos") or 0)
        broken_list = data.get("broken_links")
        if isinstance(broken_list, list):
            total_broken_local_links += len(broken_list)
        else:
            # If citations_keys missing, broken links still computable; keep
            pass
        mk = data.get("missing_keys")
        if isinstance(mk, list):
            all_missing_keys.update(mk)
        else:
            # Cannot compute missing keys if citations.json missing or malformed
            all_missing_keys = None  # type: ignore
    # Build expected missing keys unique count
    total_missing_citation_keys = len(all_missing_keys) if isinstance(all_missing_keys, set) else None

    # Start grading reports/project_status_ancient_japan.md
    report_path = workspace / "reports" / "project_status_ancient_japan.md"
    report_text = safe_read_text(report_path)

    # Check file exists and sections presence
    if report_text is not None:
        rt_lower = report_text.lower()
        has_exec = "executive summary" in rt_lower
        has_perfile = "per-file checks" in rt_lower
        has_agg = "aggregate totals" in rt_lower
        if has_exec and has_perfile and has_agg:
            scores["report_file_exists_and_sections"] = 1.0

        # Exec summary quality check
        sections = get_report_sections(report_text)
        if "executive" in sections:
            exec_start, exec_end = sections["executive"]
            exec_lines = report_text.splitlines()
            # Exclude the header line itself
            summary_text = "\n".join(exec_lines[exec_start + 1:exec_end])
            # Extract until next section header if present
            if "perfile" in sections:
                _, perfile_start = sections["perfile"]
                # but we already set end to perfile_start in get_report_sections
            words_count = extract_words_count(summary_text)
            contains_readiness = "readiness" in summary_text.lower()
            contains_critique = "critique" in summary_text.lower()
            contains_todo = ("todo" in summary_text) or ("TODO" in summary_text)
            contains_citation = "citation" in summary_text.lower()
            contains_link = "link" in summary_text.lower()
            if 100 <= words_count <= 150 and contains_readiness and contains_critique and contains_todo and contains_citation and contains_link:
                scores["report_exec_summary_quality"] = 1.0

        # Per-file checks validation
        # Build a helper to validate a specific file entry
        def validate_per_file(file_rel: str, expected: Dict[str, object]) -> bool:
            lines = report_text.splitlines()
            idx = find_line_index_with_substring(lines, file_rel)
            if idx < 0:
                return False
            # Create a window of lines for this file entry
            window = "\n".join(lines[idx: idx + 12])
            # Check TODO count
            todos_expected = expected.get("todos")
            todos_found: Optional[int] = None
            # Try multiple patterns
            patterns = [
                r"TODO count[^0-9]*([0-9]+)",
                r"TODOs?\s*:\s*([0-9]+)",
            ]
            for pat in patterns:
                m = re.search(pat, window)
                if m:
                    try:
                        todos_found = int(m.group(1))
                        break
                    except Exception:
                        pass
            if todos_found is None or int(todos_expected) != todos_found:
                return False

            # Check missing citations
            # Find the line(s) mentioning missing citation(s)
            miss_block = None
            for l in lines[idx: idx + 12]:
                if "missing citation" in l.lower():
                    miss_block = l
                    break
            mk = expected.get("missing_keys")
            if not isinstance(mk, list):
                # Cannot verify without expected missing keys
                return False
            expected_missing_set = set(mk)
            if miss_block is None:
                return False
            miss_low = miss_block.lower()
            # 'none' handling
            if len(expected_missing_set) == 0:
                if "none" not in miss_low:
                    return False
            else:
                # Ensure all expected keys are present
                for key in expected_missing_set:
                    if key not in miss_block:
                        return False
                # Ensure present keys (e.g., those in citations_keys) are not incorrectly listed
                if citations_keys:
                    for present_key in citations_keys:
                        if present_key in miss_block and present_key not in expected_missing_set:
                            return False
                # Should not claim 'none'
                if "none" in miss_low:
                    return False

            # Check broken local links
            broken_block = None
            for l in lines[idx: idx + 12]:
                if "broken local link" in l.lower():
                    broken_block = l
                    break
            expected_broken = expected.get("broken_links")
            if not isinstance(expected_broken, list):
                expected_broken = []
            if broken_block is None:
                return False
            broken_low = broken_block.lower()
            if len(expected_broken) == 0:
                if "none" not in broken_low:
                    return False
            else:
                # Ensure all expected broken paths appear
                for path_str in expected_broken:
                    if path_str not in broken_block:
                        return False
                # And 'none' should not appear
                if "none" in broken_low:
                    return False
            return True

        # Validate for each expected file
        for rel_path, expected in per_file_expected.items():
            key_name = None
            if rel_path == "notes/critique_outline.md":
                key_name = "report_per_file_notes_critique_outline_correct"
            elif rel_path == "drafts/essay_heian.md":
                key_name = "report_per_file_drafts_essay_heian_correct"
            elif rel_path == "drafts/essay_kofun.md":
                key_name = "report_per_file_drafts_essay_kofun_correct"
            else:
                # Only grade the three files required by inputs; ignore others
                key_name = None
            if key_name:
                # If citations keys couldn't be computed, this check cannot pass
                if not isinstance(expected.get("missing_keys"), list):
                    scores[key_name] = 0.0
                else:
                    scores[key_name] = 1.0 if validate_per_file(rel_path, expected) else 0.0

        # Aggregate totals validation
        if "aggregate" in get_report_sections(report_text):
            agg_section = get_report_sections(report_text)["aggregate"]
            agg_text = "\n".join(report_text.splitlines()[agg_section[0]:agg_section[1]])
            def find_total(name: str) -> Optional[int]:
                m = re.search(rf"{re.escape(name)}\s*[:=]\s*([0-9]+)", agg_text, re.IGNORECASE)
                if not m:
                    return None
                try:
                    return int(m.group(1))
                except Exception:
                    return None

            val_scanned = find_total("total_markdown_files_scanned")
            val_todos = find_total("total_todos")
            val_missing_keys = find_total("total_missing_citation_keys")
            val_broken = find_total("total_broken_local_links")

            ok = True
            if val_scanned is None or val_scanned != total_markdown_files_scanned:
                ok = False
            if val_todos is None or val_todos != total_todos:
                ok = False
            # Only check missing keys if we could compute
            if total_missing_citation_keys is not None:
                if val_missing_keys is None or val_missing_keys != total_missing_citation_keys:
                    ok = False
            else:
                # If we cannot compute, require that the field exists but cannot validate; mark fail
                ok = False
            if val_broken is None or val_broken != total_broken_local_links:
                ok = False

            scores["report_aggregate_totals_correct"] = 1.0 if ok else 0.0

    # Grade notes/critique_outline.md modifications
    critique_path = workspace / "notes" / "critique_outline.md"
    critique_text = safe_read_text(critique_path)
    # Compute expected scan results for this file (from earlier dict if available)
    expected_critique = per_file_expected.get("notes/critique_outline.md")

    if critique_text is not None:
        lines = critique_text.splitlines()

        # Check status line replaced
        has_updated = any(line.strip() == "Last status: updated" for line in lines)
        has_pending = any("Last status: pending" in line for line in lines)
        if has_updated and not has_pending:
            scores["critique_outline_status_line_updated"] = 1.0

        # Find top-level heading line index
        heading_idx = None
        for i, line in enumerate(lines):
            if line.lstrip().startswith("#"):
                heading_idx = i
                break

        # Check Status Update section position
        status_section_ok = False
        if heading_idx is not None:
            # Find first non-empty line after heading
            j = heading_idx + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines):
                # Normalize heading text (allow #, ## etc.)
                content = lines[j].strip()
                normalized = content.lstrip("#").strip()
                if normalized.lower() == "status update":
                    status_section_ok = True
        if status_section_ok:
            scores["critique_outline_status_update_section_position"] = 1.0

        # Validate bullets content
        bullets_ok = False
        if heading_idx is not None:
            # Locate 'Status Update' line anywhere below heading
            su_idx = None
            for i in range(heading_idx + 1, min(len(lines), heading_idx + 10)):
                normalized = lines[i].lstrip("#").strip().lower()
                if normalized == "status update":
                    su_idx = i
                    break
            if su_idx is not None:
                # Collect subsequent bullet lines
                bullet_lines: List[str] = []
                k = su_idx + 1
                while k < len(lines):
                    if lines[k].strip().startswith(("-", "*")):
                        bullet_lines.append(lines[k].strip())
                        k += 1
                    elif lines[k].strip() == "":
                        # allow empty lines within section but stop at first non-bullet non-empty
                        k += 1
                        # but do not collect beyond first non-bullet content
                        break
                    else:
                        break
                # Exactly three bullets
                if len(bullet_lines) == 3 and expected_critique and isinstance(expected_critique.get("missing_keys"), list):
                    # Bullet 1: TODOs: X
                    b1 = bullet_lines[0]
                    m = re.search(r"TODOs?\s*:\s*([0-9]+)", b1)
                    b1_ok = bool(m and int(m.group(1)) == int(expected_critique.get("todos")))
                    # Bullet 2: Missing citations: ...
                    b2 = bullet_lines[1]
                    b2_ok = False
                    if b2.lower().startswith(("missing citations:", "missing citation:")):
                        miss_expected = set(expected_critique.get("missing_keys"))
                        if len(miss_expected) == 0:
                            b2_ok = "none" in b2.lower()
                        else:
                            # All expected keys present, and 'none' not present
                            has_all = all((k in b2) for k in miss_expected)
                            none_absent = ("none" not in b2.lower())
                            b2_ok = has_all and none_absent
                    # Bullet 3: Broken local links: ...
                    b3 = bullet_lines[2]
                    b3_ok = False
                    if b3.lower().startswith("broken local links:"):
                        broken_expected = expected_critique.get("broken_links") or []
                        if len(broken_expected) == 0:
                            b3_ok = "none" in b3.lower()
                        else:
                            has_all = all((p in b3) for p in broken_expected)
                            none_absent = ("none" not in b3.lower())
                            b3_ok = has_all and none_absent
                    bullets_ok = b1_ok and b2_ok and b3_ok

        if bullets_ok:
            scores["critique_outline_status_update_bullets_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()