import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_simple_yaml_mapping(path: Path) -> Optional[Dict[str, str]]:
    """
    Very simple YAML parser for flat key: value pairs with scalar string values.
    Handles quoted strings and unquoted simple strings.
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    result: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            return None
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Remove surrounding quotes if present
        if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
            q = val[0]
            if val[-1] == q:
                val = val[1:-1]
        result[key] = val
    return result


def _extract_citations_and_figures_from_tex(tex: str, base_file: Path, input_root: Path) -> Tuple[Set[str], List[str]]:
    # Extract citations
    citations: Set[str] = set()
    for m in re.finditer(r"\\cite\{([^}]*)\}", tex):
        inner = m.group(1)
        for key in inner.split(","):
            k = key.strip()
            if k:
                citations.add(k)

    # Extract figures from \includegraphics
    figures: List[str] = []
    for m in re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}", tex):
        ref = m.group(1).strip()
        if not ref:
            continue
        resolved = (base_file.parent / ref)
        # Normalize relative to input_root
        figures.append(_normalize_project_relative_path(resolved, input_root))
    return citations, figures


def _extract_md_image_paths(md_text: str, base_file: Path, input_root: Path) -> List[str]:
    figures: List[str] = []
    for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", md_text):
        ref = m.group(1).strip()
        if not ref:
            continue
        resolved = (base_file.parent / ref)
        figures.append(_normalize_project_relative_path(resolved, input_root))
    return figures


def _normalize_project_relative_path(path: Path, input_root: Path) -> str:
    """
    Normalize a path to forward-slash, project-relative to input_root if possible.
    """
    try:
        abs_path = path.resolve()
    except Exception:
        # Fallback: join and normalize without resolving
        abs_path = (path.parent / path.name)
    try:
        rel = abs_path.relative_to(input_root.resolve())
        return rel.as_posix()
    except Exception:
        # Fallback to as_posix of path relative to base (best effort)
        # Remove any leading './'
        s = str(path.as_posix())
        while s.startswith("./"):
            s = s[2:]
        return s


def _parse_bib_keys_and_count(path: Path) -> Optional[Tuple[Set[str], int]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    keys: Set[str] = set()
    for m in re.finditer(r"@\w+\s*\{\s*([^,\s]+)\s*,", text):
        keys.add(m.group(1).strip())
    return keys, len(keys)


def _read_all_dist_files(dist_root: Path) -> Set[str]:
    """Return set of all file paths under dist relative to dist_root, posix style."""
    if not dist_root.exists():
        return set()
    files: Set[str] = set()
    for p in dist_root.rglob("*"):
        if p.is_file():
            try:
                rel = p.relative_to(dist_root).as_posix()
            except Exception:
                rel = p.as_posix()
            files.add(rel)
    return files


def _is_iso8601(s: str) -> bool:
    try:
        # Allow fromisoformat parse
        datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    input_root = workspace / "input"
    dist_root = workspace / "dist"

    scores = {
        "paper_copied_correct": 0.0,
        "refs_copied_correct": 0.0,
        "slides_copied_correct": 0.0,
        "images_copied_set_correct": 0.0,
        "manifest_json_valid": 0.0,
        "manifest_metadata_contains_yaml_keys": 0.0,
        "manifest_lists_and_counts_correct": 0.0,
        "manifest_files_copied_and_sizes_correct": 0.0,
        "deployment_status_overview_correct": 0.0,
        "deployment_status_readiness_counts_correct": 0.0,
        "deployment_status_issues_list_correct": 0.0,
        "dist_no_extraneous_files": 0.0,
    }

    # Prepare expected derived data from inputs
    paper_path = input_root / "paper.tex"
    refs_path = input_root / "refs.bib"
    slides_path = input_root / "slides" / "outline.md"
    metadata_path = input_root / "metadata.yaml"

    paper_text = _safe_read_text(paper_path) if paper_path.exists() else None
    refs_text = _safe_read_text(refs_path) if refs_path.exists() else None
    slides_text = _safe_read_text(slides_path) if slides_path.exists() else None
    metadata = _parse_simple_yaml_mapping(metadata_path) if metadata_path.exists() else None

    # Compute expected citations and figures
    expected_citations: Optional[Set[str]] = None
    paper_figs: Optional[List[str]] = None
    if paper_text is not None:
        citations, figs = _extract_citations_and_figures_from_tex(paper_text, paper_path, input_root)
        expected_citations = citations
        paper_figs = figs

    slides_figs: Optional[List[str]] = None
    if slides_text is not None:
        slides_figs = _extract_md_image_paths(slides_text, slides_path, input_root)

    bib_parse = _parse_bib_keys_and_count(refs_path) if refs_text is not None else None
    bib_keys: Optional[Set[str]] = None
    bib_size: Optional[int] = None
    if bib_parse is not None:
        bib_keys, bib_size = bib_parse

    # Expected figures referenced and missing/existing
    figures_referenced_set: Optional[Set[str]] = None
    if paper_figs is not None and slides_figs is not None:
        figures_referenced_set = set(paper_figs) | set(slides_figs)
    elif paper_figs is not None:
        figures_referenced_set = set(paper_figs)
    elif slides_figs is not None:
        figures_referenced_set = set(slides_figs)
    else:
        figures_referenced_set = None

    def _exists_under_input(rel: str) -> bool:
        return (input_root / rel).exists()

    expected_figures_existing: Optional[Set[str]] = None
    expected_figures_missing: Optional[Set[str]] = None
    if figures_referenced_set is not None:
        existing = {p for p in figures_referenced_set if _exists_under_input(p)}
        missing = figures_referenced_set - existing
        expected_figures_existing = existing
        expected_figures_missing = missing

    # Check copied content correctness
    dist_paper = dist_root / "paper.tex"
    dist_refs = dist_root / "refs.bib"
    dist_slides = dist_root / "slides" / "outline.md"

    if paper_text is not None and dist_paper.exists():
        dist_paper_text = _safe_read_text(dist_paper)
        if dist_paper_text is not None and dist_paper_text == paper_text:
            scores["paper_copied_correct"] = 1.0

    if refs_text is not None and dist_refs.exists():
        dist_refs_text = _safe_read_text(dist_refs)
        if dist_refs_text is not None and dist_refs_text == refs_text:
            scores["refs_copied_correct"] = 1.0

    if slides_text is not None and dist_slides.exists():
        dist_slides_text = _safe_read_text(dist_slides)
        if dist_slides_text is not None and dist_slides_text == slides_text:
            scores["slides_copied_correct"] = 1.0

    # Check images copied set correctness
    dist_images_dir = dist_root / "images"
    if expected_figures_existing is not None and dist_images_dir.exists():
        # Gather images actually present in dist/images
        dist_images_files = set()
        if dist_images_dir.is_dir():
            for p in dist_images_dir.rglob("*"):
                if p.is_file():
                    try:
                        rel = p.relative_to(dist_root).as_posix()
                    except Exception:
                        rel = p.as_posix()
                    dist_images_files.add(rel)
        # Expected files in dist under images/
        normalized_expected = set()
        for p in expected_figures_existing:
            normalized_expected.add(Path(p).as_posix())
        expected_dist_images = normalized_expected

        if dist_images_files == expected_dist_images:
            # Ensure contents match source for each file
            all_match = True
            for rel in expected_dist_images:
                src = input_root / rel
                dst = dist_root / rel
                src_b = _safe_read_bytes(src)
                dst_b = _safe_read_bytes(dst)
                if src_b is None or dst_b is None or src_b != dst_b:
                    all_match = False
                    break
            if all_match:
                scores["images_copied_set_correct"] = 1.0

    # Manifest checks
    manifest_path = dist_root / "manifest.json"
    manifest = _safe_load_json(manifest_path) if manifest_path.exists() else None
    if manifest is not None and isinstance(manifest, dict):
        scores["manifest_json_valid"] = 1.0

        # Check metadata contains YAML keys
        if metadata is not None and isinstance(manifest.get("metadata"), dict):
            md_ok = True
            for k, v in metadata.items():
                if manifest["metadata"].get(k) != v:
                    md_ok = False
                    break
            if md_ok:
                scores["manifest_metadata_contains_yaml_keys"] = 1.0

        # Check lists and counts
        lists_ok = True
        if expected_citations is None or bib_keys is None or bib_size is None or figures_referenced_set is None or expected_figures_missing is None:
            lists_ok = False
        else:
            # Types
            paper_citations = manifest.get("paper_citations")
            missing_citations = manifest.get("missing_citations")
            bibliography_size = manifest.get("bibliography_size")
            figures_referenced = manifest.get("figures_referenced")
            figures_missing = manifest.get("figures_missing")
            generated_at = manifest.get("generated_at")

            if not isinstance(paper_citations, list):
                lists_ok = False
            if not isinstance(missing_citations, list):
                lists_ok = False
            if not (isinstance(bibliography_size, int) and not isinstance(bibliography_size, bool)):
                lists_ok = False
            if not isinstance(figures_referenced, list):
                lists_ok = False
            if not isinstance(figures_missing, list):
                lists_ok = False
            if not isinstance(generated_at, str) or not _is_iso8601(generated_at):
                lists_ok = False

            if lists_ok:
                # Compare content
                expected_paper_citations = sorted(expected_citations)
                expected_missing_citations = sorted(sorted(expected_citations - bib_keys))
                expected_figures_referenced = sorted({Path(p).as_posix() for p in figures_referenced_set})
                expected_figures_missing_list = sorted({Path(p).as_posix() for p in expected_figures_missing})

                if sorted(paper_citations) != expected_paper_citations:
                    lists_ok = False
                if sorted(missing_citations) != expected_missing_citations:
                    lists_ok = False
                if bibliography_size != bib_size:
                    lists_ok = False
                if sorted(figures_referenced) != expected_figures_referenced:
                    lists_ok = False
                if sorted(figures_missing) != expected_figures_missing_list:
                    lists_ok = False

        if lists_ok:
            scores["manifest_lists_and_counts_correct"] = 1.0

        # Check files_copied and file_sizes
        files_ok = True
        files_copied = manifest.get("files_copied")
        file_sizes = manifest.get("file_sizes")
        # Only perform if we can compute expected figures existing
        if not (isinstance(files_copied, list) and isinstance(file_sizes, dict) and expected_figures_existing is not None):
            files_ok = False
        else:
            expected_files_copied = [
                "paper.tex",
                "refs.bib",
                "slides/outline.md",
            ] + sorted({Path(p).as_posix() for p in expected_figures_existing})
            expected_files_copied = sorted(expected_files_copied)
            if sorted(files_copied) != expected_files_copied:
                files_ok = False
            else:
                # Check file sizes match actual dist files and mapping keys exactly match files_copied
                if sorted(file_sizes.keys()) != expected_files_copied:
                    files_ok = False
                else:
                    for rel in expected_files_copied:
                        fpath = dist_root / rel
                        try:
                            size = fpath.stat().st_size
                        except Exception:
                            files_ok = False
                            break
                        if not (isinstance(file_sizes.get(rel), int) and file_sizes.get(rel) == size):
                            files_ok = False
                            break

        if files_ok:
            scores["manifest_files_copied_and_sizes_correct"] = 1.0

    # Deployment status checks
    status_path = dist_root / "deployment_status.md"
    status_text = _safe_read_text(status_path) if status_path.exists() else None
    # Prepare expected counts for readiness
    if status_text is not None and metadata is not None and expected_citations is not None and bib_size is not None and figures_referenced_set is not None and expected_figures_missing is not None:
        # Overview paragraph
        # First non-empty paragraph
        paras = [p.strip() for p in re.split(r"\n\s*\n", status_text) if p.strip()]
        if paras:
            first_para = paras[0]
            title = metadata.get("title", "")
            conference = metadata.get("conference", "")
            if title and conference and (title in first_para) and (conference in first_para):
                scores["deployment_status_overview_correct"] = 1.0

        # Readiness section counts
        readiness_ok = False
        # Find Readiness section header and content block
        lines = status_text.splitlines()
        readiness_indices = [i for i, ln in enumerate(lines) if re.match(r"^\s*#+\s*Readiness\b", ln, flags=re.IGNORECASE)]
        if readiness_indices:
            start = readiness_indices[0] + 1
            # End at next header or end
            end = len(lines)
            for j in range(start, len(lines)):
                if re.match(r"^\s*#+\s*", lines[j]) and j > start:
                    end = j
                    break
            block = lines[start:end]
            block_text = "\n".join(block)
            # Expected counts
            exp_total_citations = len(expected_citations)
            exp_missing_citations = len(expected_citations - bib_keys) if bib_keys is not None else 0
            exp_bib_size = bib_size
            exp_total_figs = len(figures_referenced_set)
            exp_missing_figs = len(expected_figures_missing)
            # Check that each label with correct count appears
            def _has_label_with_count(text: str, label: str, expected: int) -> bool:
                # find a line containing the label and an integer equal to expected
                pattern = re.compile(re.escape(label), flags=re.IGNORECASE)
                for ln in text.splitlines():
                    if pattern.search(ln):
                        nums = re.findall(r"\d+", ln)
                        if nums:
                            try:
                                val = int(nums[0])
                            except Exception:
                                continue
                            if val == expected:
                                return True
                return False

            ok = True
            ok &= _has_label_with_count(block_text, "total citations", exp_total_citations)
            ok &= _has_label_with_count(block_text, "missing citations", exp_missing_citations)
            ok &= _has_label_with_count(block_text, "bibliography_size", exp_bib_size)
            ok &= _has_label_with_count(block_text, "total figures referenced", exp_total_figs)
            ok &= _has_label_with_count(block_text, "figures_missing", exp_missing_figs)
            readiness_ok = bool(ok)
        if readiness_ok:
            scores["deployment_status_readiness_counts_correct"] = 1.0

        # Issues section presence and items
        issues_ok = False
        # If there are any missing items we expect an Issues section
        missing_citations_list = sorted(expected_citations - bib_keys) if bib_keys is not None else []
        missing_figs_list = sorted({Path(p).as_posix() for p in expected_figures_missing})
        if missing_citations_list or missing_figs_list:
            issues_indices = [i for i, ln in enumerate(lines) if re.match(r"^\s*#+\s*Issues\b", ln, flags=re.IGNORECASE)]
            if issues_indices:
                s = issues_indices[0] + 1
                e = len(lines)
                for j in range(s, len(lines)):
                    if re.match(r"^\s*#+\s*", lines[j]) and j > s:
                        e = j
                        break
                issues_block = "\n".join(lines[s:e])
                ok_miss_cites = all((key in issues_block) for key in missing_citations_list)
                ok_miss_figs = all((p in issues_block) for p in missing_figs_list)
                issues_ok = ok_miss_cites and ok_miss_figs
        else:
            # No missing items, should have a "ready" statement somewhere
            if re.search(r"\bbundle\b.*\bready\b", status_text, flags=re.IGNORECASE):
                issues_ok = True

        if issues_ok:
            scores["deployment_status_issues_list_correct"] = 1.0

    # Dist has no extraneous files
    # Compute expected file set if inputs are available
    expected_file_set: Optional[Set[str]] = None
    if expected_figures_existing is not None:
        expected_file_set = {
            "paper.tex",
            "refs.bib",
            "slides/outline.md",
            "manifest.json",
            "deployment_status.md",
        } | {Path(p).as_posix() for p in expected_figures_existing}
        actual_files = _read_all_dist_files(dist_root)
        if actual_files == expected_file_set:
            scores["dist_no_extraneous_files"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()