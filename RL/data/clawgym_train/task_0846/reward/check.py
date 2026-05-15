import json
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List


def read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_yaml_kv(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for top-level key: value mappings (scalars only).
    Handles comments (# ...), single/double quoted scalars, and booleans.
    Returns None on failure.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    data: Dict[str, Any] = {}
    try:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            # Remove comments not inside quotes (simple heuristic: split at #)
            if "#" in line:
                # Keep content before first '#'
                before_hash = line.split("#", 1)[0].rstrip()
            else:
                before_hash = line
            if not before_hash:
                continue
            if ":" not in before_hash:
                continue
            key, val = before_hash.split(":", 1)
            key = key.strip()
            val = val.strip()
            if not key:
                continue
            # Normalize quoted values
            if val.startswith(("'", '"')) and len(val) >= 2 and val[-1] == val[0]:
                val = val[1:-1]
            # Convert booleans
            lower = val.lower()
            if lower == "true":
                parsed_val: Any = True
            elif lower == "false":
                parsed_val = False
            else:
                parsed_val = val
            data[key] = parsed_val
        return data
    except Exception:
        return None


def is_relative_path_str(p: str) -> bool:
    # Consider both POSIX and Windows; treat drive-letter absolute or leading slash as absolute
    if not isinstance(p, str) or p == "":
        return False
    # Normalize whitespace
    p = p.strip()
    if p.startswith("/"):
        return False
    # Windows drive letter
    if re.match(r"^[A-Za-z]:[\\/]", p):
        return False
    return True


def normalize_to_workspace(workspace: Path, p: str) -> Path:
    return (workspace / p).resolve()


def list_corpus_files(corpus_dir: Path) -> List[Path]:
    try:
        return sorted([p for p in corpus_dir.glob("*.txt") if p.is_file()])
    except Exception:
        return []


def recompute_term_counts(corpus_dir: Path, terms: List[str], case_sensitive: bool) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int]]:
    files = list_corpus_files(corpus_dir)
    flags = 0 if case_sensitive else re.IGNORECASE
    patterns: Dict[str, re.Pattern] = {}
    for t in terms:
        try:
            pat = re.compile(r"\b" + re.escape(t) + r"\b", flags)
        except re.error:
            # Fallback to literal search if regex fails (shouldn't happen with re.escape)
            pat = re.compile(re.escape(t), flags)
        patterns[t] = pat
    per_file: Dict[str, Dict[str, int]] = {}
    totals: Dict[str, int] = {t: 0 for t in terms}
    for fpath in files:
        text = read_text_file(fpath) or ""
        counts: Dict[str, int] = {}
        for term, pat in patterns.items():
            c = len(pat.findall(text))
            if c > 0:
                counts[term] = c
                totals[term] += c
        per_file[str(fpath)] = counts
    return per_file, totals


def extract_term_file_examples_from_notes(notes_text: str, expected_pairs: List[Tuple[str, str]]) -> int:
    """
    Count how many distinct (term, file_basename) pairs appear on the same line in notes.
    """
    found: set = set()
    lines = notes_text.splitlines()
    # Build regex patterns for each pair to avoid overlapping greedy checks
    for line in lines:
        low = line.lower()
        for term, base in expected_pairs:
            if term.lower() in low and base.lower() in low:
                found.add((term.lower(), base.lower()))
    return len(found)


def count_bullets(notes_text: str) -> int:
    count = 0
    for line in notes_text.splitlines():
        s = line.strip()
        if s.startswith(("- ", "* ")):
            count += 1
        elif re.match(r"^\d+[.)]\s", s):
            count += 1
    return count


def load_terms_list(path: Path) -> Optional[List[str]]:
    data = load_json_safe(path)
    if isinstance(data, list) and all(isinstance(x, str) for x in data):
        return data
    return None


def load_results_structure(path: Path) -> Optional[Dict[str, Any]]:
    data = load_json_safe(path)
    if not isinstance(data, dict):
        return None
    # Basic structural validation
    if "files" not in data or "total_counts" not in data or "config_used" not in data:
        return None
    if not isinstance(data["files"], list):
        return None
    if not isinstance(data["total_counts"], dict):
        return None
    if not isinstance(data["config_used"], dict):
        return None
    # Validate each file entry structure
    for item in data["files"]:
        if not isinstance(item, dict):
            return None
        if "file" not in item or "matches" not in item:
            return None
        if not isinstance(item["file"], str):
            return None
        if not isinstance(item["matches"], dict):
            return None
        for k, v in item["matches"].items():
            if not isinstance(k, str) or not isinstance(v, int):
                return None
    # Validate total_counts values are ints > 0
    for k, v in data["total_counts"].items():
        if not isinstance(k, str) or not isinstance(v, int) or v <= 0:
            return None
    # Validate config_used keys presence
    for k in ["corpus_dir", "terms_file", "case_sensitive"]:
        if k not in data["config_used"]:
            return None
    return data


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_has_required_keys": 0.0,
        "config_paths_relative": 0.0,
        "config_paths_resolve_correctly": 0.0,
        "config_case_insensitive_set": 0.0,
        "results_file_exists": 0.0,
        "results_structure_valid": 0.0,
        "results_paths_relative": 0.0,
        "covers_all_corpus_files": 0.0,
        "results_match_recomputed_counts": 0.0,
        "results_total_counts_consistent": 0.0,
        "results_config_used_matches_config": 0.0,
        "total_counts_excludes_zero_hit_terms": 0.0,
        "meeting_notes_present": 0.0,
        "notes_include_config_changes": 0.0,
        "notes_env_setup_summary": 0.0,
        "notes_verify_examples_count": 0.0,
        "action_items_count_between_3_and_5": 0.0,
        "output_path_matches_spec": 0.0,
    }

    # Paths
    cfg_path = workspace / "config" / "project.yaml"
    results_path = workspace / "outputs" / "extracted_references.json"
    notes_path = workspace / "outputs" / "meeting_notes.md"
    terms_path = workspace / "input" / "terms.json"
    corpus_dir_expected = workspace / "input" / "corpus"

    # Load config
    cfg = parse_yaml_kv(cfg_path) if cfg_path.exists() else None
    if cfg is not None and isinstance(cfg, dict):
        required_keys = ["corpus_dir", "terms_file", "output_json", "case_sensitive"]
        if all(k in cfg for k in required_keys):
            scores["config_has_required_keys"] = 1.0

        # Check case_sensitive is False
        if isinstance(cfg.get("case_sensitive"), bool):
            scores["config_case_insensitive_set"] = 1.0 if (cfg.get("case_sensitive") is False) else 0.0
        else:
            # Accept string "false" if parsing did not convert to bool
            val = cfg.get("case_sensitive")
            if isinstance(val, str) and val.strip().lower() == "false":
                scores["config_case_insensitive_set"] = 1.0

        # Paths relative check
        corpus_dir_val = cfg.get("corpus_dir")
        terms_file_val = cfg.get("terms_file")
        output_json_val = cfg.get("output_json")
        if (
            isinstance(corpus_dir_val, str)
            and isinstance(terms_file_val, str)
            and isinstance(output_json_val, str)
            and is_relative_path_str(corpus_dir_val)
            and is_relative_path_str(terms_file_val)
            and is_relative_path_str(output_json_val)
        ):
            scores["config_paths_relative"] = 1.0

        # Paths resolve correctly check
        ok_paths = True
        resolved_corpus = None
        resolved_terms = None
        resolved_output = None
        if isinstance(corpus_dir_val, str):
            resolved_corpus = normalize_to_workspace(workspace, corpus_dir_val)
            if not resolved_corpus.exists() or not resolved_corpus.is_dir():
                ok_paths = False
            # Check that it is actually the expected corpus directory
            try:
                # Compare real path directories
                if resolved_corpus.resolve() != corpus_dir_expected.resolve():
                    ok_paths = False
            except Exception:
                ok_paths = False
        else:
            ok_paths = False
        if isinstance(terms_file_val, str):
            resolved_terms = normalize_to_workspace(workspace, terms_file_val)
            if not resolved_terms.exists() or not resolved_terms.is_file():
                ok_paths = False
            try:
                if resolved_terms.resolve() != terms_path.resolve():
                    ok_paths = False
            except Exception:
                ok_paths = False
        else:
            ok_paths = False
        if isinstance(output_json_val, str):
            resolved_output = normalize_to_workspace(workspace, output_json_val)
            # Must match specified path outputs/extracted_references.json
            expected_output = results_path
            try:
                if resolved_output.resolve() != expected_output.resolve():
                    ok_paths = False
            except Exception:
                ok_paths = False
        else:
            ok_paths = False
        if ok_paths:
            scores["config_paths_resolve_correctly"] = 1.0
        # Also record explicit check for output path name match
        if isinstance(output_json_val, str):
            try:
                if normalize_to_workspace(workspace, output_json_val).resolve() == results_path.resolve():
                    scores["output_path_matches_spec"] = 1.0
            except Exception:
                pass

    # Results existence
    if results_path.exists() and results_path.is_file():
        scores["results_file_exists"] = 1.0

    # Load and validate results structure
    results = None
    structure_ok = False
    if results_path.exists():
        results = load_results_structure(results_path)
        structure_ok = results is not None
        if structure_ok:
            scores["results_structure_valid"] = 1.0

    # Validate results content against recomputation
    # Load terms and corpus
    terms = None
    if terms_path.exists():
        terms = load_terms_list(terms_path)

    if structure_ok and terms is not None and cfg is not None and isinstance(cfg, dict):
        # Extract config_used values
        cfg_used = results["config_used"]
        used_corpus_dir = cfg_used.get("corpus_dir")
        used_terms_file = cfg_used.get("terms_file")
        used_case_sensitive = cfg_used.get("case_sensitive")

        # Ensure results file paths are relative
        rel_ok = True
        for item in results["files"]:
            fpath_str = item.get("file", "")
            if not isinstance(fpath_str, str) or not is_relative_path_str(fpath_str):
                rel_ok = False
                break
        if rel_ok:
            scores["results_paths_relative"] = 1.0

        # Compare config_used to YAML config (normalize to absolutes for comparison)
        cfg_match = False
        try:
            cfg_corpus_val = cfg.get("corpus_dir")
            cfg_terms_val = cfg.get("terms_file")
            cfg_case_val = cfg.get("case_sensitive")
            # Normalize booleans from strings if needed
            if isinstance(cfg_case_val, str):
                if cfg_case_val.strip().lower() == "false":
                    cfg_case_val_norm = False
                elif cfg_case_val.strip().lower() == "true":
                    cfg_case_val_norm = True
                else:
                    cfg_case_val_norm = cfg_case_val
            else:
                cfg_case_val_norm = cfg_case_val

            # Compare by resolved absolute paths for dir/files where possible
            corpus_equal = False
            terms_equal = False
            if isinstance(cfg_corpus_val, str) and isinstance(used_corpus_dir, str):
                corpus_equal = normalize_to_workspace(workspace, cfg_corpus_val).resolve() == normalize_to_workspace(workspace, used_corpus_dir).resolve()
            if isinstance(cfg_terms_val, str) and isinstance(used_terms_file, str):
                terms_equal = normalize_to_workspace(workspace, cfg_terms_val).resolve() == normalize_to_workspace(workspace, used_terms_file).resolve()
            case_equal = (cfg_case_val_norm == used_case_sensitive)
            if corpus_equal and terms_equal and case_equal:
                cfg_match = True
        except Exception:
            cfg_match = False
        if cfg_match:
            scores["results_config_used_matches_config"] = 1.0

        # Recompute counts and compare
        try:
            recomputed_per_file, recomputed_totals = recompute_term_counts(
                normalize_to_workspace(workspace, used_corpus_dir) if isinstance(used_corpus_dir, str) else corpus_dir_expected,
                terms,
                bool(used_case_sensitive),
            )
            # Build a mapping from results "file" strings to matches
            results_files_map: Dict[str, Dict[str, int]] = {}
            for item in results["files"]:
                fstr = item["file"]
                # Normalize to absolute to compare robustly
                abs_from_results = normalize_to_workspace(workspace, fstr).resolve()
                results_files_map[str(abs_from_results)] = item["matches"]

            # Compare coverage of files
            expected_files_abs = {str(p.resolve()) for p in list_corpus_files(corpus_dir_expected)}
            # Map recomputed keys normalized to absolute
            recomputed_files_abs = set()
            for fstr in recomputed_per_file.keys():
                try:
                    recomputed_files_abs.add(str(Path(fstr).resolve()))
                except Exception:
                    pass
            if expected_files_abs.issubset(set(results_files_map.keys())):
                scores["covers_all_corpus_files"] = 1.0

            # Compare per-file matches exactly (only positive counts included)
            per_file_ok = True
            for expected_abs in expected_files_abs:
                exp_counts = recomputed_per_file.get(str(Path(expected_abs)), {})
                res_counts = results_files_map.get(expected_abs, None)
                if res_counts is None:
                    per_file_ok = False
                    break
                # Ensure only terms with >0 counts are included in res_counts
                exp_positive = {k: v for k, v in exp_counts.items() if v > 0}
                if res_counts != exp_positive:
                    per_file_ok = False
                    break
            if per_file_ok:
                scores["results_match_recomputed_counts"] = 1.0

            # Compare total_counts equals recomputed with zeros removed
            expected_totals = {k: v for k, v in recomputed_totals.items() if v > 0}
            totals_ok = results["total_counts"] == expected_totals
            if totals_ok:
                scores["results_total_counts_consistent"] = 1.0

            # Ensure zero-hit terms are excluded (e.g., 'Frigg')
            zero_excluded_ok = True
            for term in terms:
                if recomputed_totals.get(term, 0) == 0 and term in results["total_counts"]:
                    zero_excluded_ok = False
                    break
            if zero_excluded_ok:
                scores["total_counts_excludes_zero_hit_terms"] = 1.0

        except Exception:
            # Any recomputation failure means checks remain 0.0
            pass

    # Meeting notes checks
    if notes_path.exists() and notes_path.is_file():
        scores["meeting_notes_present"] = 1.0
        notes_text = read_text_file(notes_path) or ""

        # Must include the final key names indicating config changes
        keys_required = ["corpus_dir", "terms_file", "output_json", "case_sensitive"]
        if all(k in notes_text for k in keys_required):
            scores["notes_include_config_changes"] = 1.0

        # Environment setup summary: mention requirements and an install concept
        lower_notes = notes_text.lower()
        mentions_requirements = "requirements.txt" in lower_notes or "requirements" in lower_notes
        env_keywords = ["pip", "install", "venv", "virtualenv", "conda", "pyyaml", "python -m venv", "activate"]
        mentions_env = any(k in lower_notes for k in env_keywords)
        if mentions_requirements and mentions_env:
            scores["notes_env_setup_summary"] = 1.0

        # Verify at least three term-to-file examples
        # Build expected pairs from results if available, else from known corpus/terms
        expected_pairs: List[Tuple[str, str]] = []
        if structure_ok and results is not None:
            # Derive from results: take any term with >0 in any file and build (term, basename)
            for item in results["files"]:
                base = Path(item["file"]).name
                for term, cnt in item["matches"].items():
                    if isinstance(cnt, int) and cnt > 0:
                        expected_pairs.append((term, base))
        else:
            # Fallback to known expected pairs based on provided inputs
            expected_pairs = [
                ("Odin", "poem1.txt"),
                ("Yggdrasil", "poem1.txt"),
                ("Asgard", "poem1.txt"),
                ("Loki", "essay.txt"),
                ("Ragnarok", "essay.txt"),
                ("Valhalla", "essay.txt"),
                ("Mjolnir", "essay.txt"),
                ("Freya", "poem2.txt"),
                ("Freyja", "poem2.txt"),
                ("Thor", "poem2.txt"),
                ("Midgard", "poem2.txt"),
            ]
        example_count = extract_term_file_examples_from_notes(notes_text, expected_pairs)
        if example_count >= 3:
            scores["notes_verify_examples_count"] = 1.0

        # Count action items 3–5
        bullets = count_bullets(notes_text)
        if 3 <= bullets <= 5:
            scores["action_items_count_between_3_and_5"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()