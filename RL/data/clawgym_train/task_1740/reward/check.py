import json
import hashlib
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def list_input_files(input_root: Path) -> List[Path]:
    if not input_root.exists():
        return []
    files = []
    for p in input_root.rglob("*"):
        if p.is_file():
            files.append(p)
    return files


def parse_csv_basic(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        txt = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None, None
    if not txt:
        return None, None
    header_line = txt[0].strip()
    if not header_line:
        return None, None
    headers = header_line.split(",")
    rows: List[Dict[str, str]] = []
    for line in txt[1:]:
        if not line.strip():
            continue
        parts = line.strip().split(",")
        if len(parts) != len(headers):
            return None, None
        rows.append(dict(zip(headers, parts)))
    return headers, rows


def to_float_safe(x: str, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def compute_expected_summary_rows(input_csv: Path) -> Optional[List[Dict[str, str]]]:
    headers, rows = parse_csv_basic(input_csv)
    if headers is None or rows is None:
        return None
    # Expect these columns in input
    required_cols = ["batch_id", "strain", "dry_weight_kg", "cbd_percent"]
    for col in required_cols:
        if col not in headers:
            return None
    out_rows: List[Dict[str, str]] = []
    for r in rows:
        dry = to_float_safe(r.get("dry_weight_kg", "0"))
        pct = to_float_safe(r.get("cbd_percent", "0"))
        est = round(dry * 1000.0 * (pct / 100.0), 3)
        out_rows.append({
            "batch_id": r.get("batch_id", ""),
            "strain": r.get("strain", ""),
            "dry_weight_kg": str(dry),
            "cbd_percent": str(pct),
            "est_cbd_g": str(est),
        })
    return out_rows


def check_csv_matches_expected(csv_path: Path, expected_rows: List[Dict[str, str]]) -> float:
    headers, rows = parse_csv_basic(csv_path)
    if headers is None or rows is None:
        return 0.0
    expected_header = ["batch_id", "strain", "dry_weight_kg", "cbd_percent", "est_cbd_g"]
    if headers != expected_header:
        return 0.0
    if len(rows) != len(expected_rows):
        return 0.0
    # Compare row by row in order
    for i, (r, exp) in enumerate(zip(rows, expected_rows)):
        # Check id and strain exact match
        if r.get("batch_id", "") != exp["batch_id"]:
            return 0.0
        if r.get("strain", "") != exp["strain"]:
            return 0.0
        # Check numeric fields by float equality after parsing
        try:
            dry_val = float(r.get("dry_weight_kg", "nan"))
            pct_val = float(r.get("cbd_percent", "nan"))
            est_val = float(r.get("est_cbd_g", "nan"))
            exp_dry = float(exp["dry_weight_kg"])
            exp_pct = float(exp["cbd_percent"])
            exp_est = float(exp["est_cbd_g"])
        except Exception:
            return 0.0
        # Exact numeric equality for these deterministic values
        if not (abs(dry_val - exp_dry) < 1e-12 and abs(pct_val - exp_pct) < 1e-12 and abs(est_val - exp_est) < 1e-12):
            return 0.0
    return 1.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "review_present": 0.0,
        "review_references_code_files": 0.0,
        "review_references_other_files": 0.0,
        "review_identifies_issues": 0.0,
        "review_describes_refactor_and_preserves_behavior": 0.0,
        "review_edge_cases_mentioned": 0.0,
        "refactored_script_exists": 0.0,
        "refactored_accepts_arguments": 0.0,
        "refactored_has_formula": 0.0,
        "refactored_header_and_columns": 0.0,
        "refactored_no_third_party_imports": 0.0,
        "inventory_json_valid": 0.0,
        "inventory_covers_all_input_files": 0.0,
        "inventory_metadata_correct": 0.0,
        "validation_files_present": 0.0,
        "validation_comparison_correct": 0.0,
        "original_summary_correct_values": 0.0,
        "refactored_summary_correct_values": 0.0,
        "email_present": 0.0,
        "email_mentions_refactored_path": 0.0,
        "email_contains_reproduction_command": 0.0,
        "email_mentions_verification": 0.0,
    }

    # Paths
    review_md = workspace / "output" / "review.md"
    refactored_script = workspace / "output" / "refactored" / "batch_report_refactored.py"
    inventory_json_path = workspace / "output" / "inventory.json"
    validation_dir = workspace / "output" / "validation"
    original_csv = validation_dir / "original_summary.csv"
    refactored_csv = validation_dir / "refactored_summary.csv"
    comparison_json = validation_dir / "comparison.json"
    email_txt = workspace / "output" / "email_to_store_manager.txt"
    input_csv_path = workspace / "input" / "data" / "batches.csv"

    # 1) Review checks
    review_text = read_text_safe(review_md)
    if review_text is not None:
        scores["review_present"] = 1.0
        # references to code files
        if ("input/src/batch_report.py" in review_text) and ("input/src/utils.py" in review_text):
            scores["review_references_code_files"] = 1.0
        # references to other input files (either data or README)
        if ("input/data/batches.csv" in review_text) or ("input/README.md" in review_text):
            scores["review_references_other_files"] = 1.0
        # identifies issues: look for multiple distinct issue tokens
        issue_tokens = [
            "duplicate", "duplicated", "path assumption", "hard-coded", "hard coded", "weak error handling",
            "error handling", "magic number", "magic numbers", "missing docstring", "missing docstrings",
            "global constant", "global constants", "unused", "code smell"
        ]
        found_issue_categories = set()
        low_text = review_text.lower()
        for tok in issue_tokens:
            if tok in low_text:
                found_issue_categories.add(tok)
        if len(found_issue_categories) >= 2:
            scores["review_identifies_issues"] = 1.0
        elif len(found_issue_categories) == 1:
            scores["review_identifies_issues"] = 0.5
        # describes refactor and preserves behavior
        has_refactor = ("refactor" in low_text) or ("refactored" in low_text)
        preserves = any(s in low_text for s in [
            "preserve behavior", "preserves behavior", "identical", "same results", "no change in numbers",
            "did not change", "kept calculations", "unchanged", "does not change"
        ])
        if has_refactor and preserves:
            scores["review_describes_refactor_and_preserves_behavior"] = 1.0
        # edge cases mentioned
        edge_indicators = any(("edge case" in low_text) or ("edge cases" in low_text) for _ in [0])
        robustness_tokens = ["missing", "blank", "empty", "malformed", "non-numeric", "non numeric", "bad row", "headers mismatch"]
        handles_tokens = ["handled", "handles", "now handled", "validated", "validation", "guard", "safe"]
        robustness_mentioned = any(tok in low_text for tok in robustness_tokens)
        handles_mentioned = any(tok in low_text for tok in handles_tokens)
        if edge_indicators or (robustness_mentioned and handles_mentioned):
            scores["review_edge_cases_mentioned"] = 1.0

    # 2) Refactored script checks
    refactored_text = read_text_safe(refactored_script)
    if refactored_text is not None:
        scores["refactored_script_exists"] = 1.0
        low = refactored_text.lower()
        # accepts args with --input and --output
        if ("--input" in refactored_text) and ("--output" in refactored_text) and ("argparse" in low or "sys.argv" in low):
            scores["refactored_accepts_arguments"] = 1.0
        # formula presence (round to 3 decimals and 1000 and /100)
        formula_ok = ("round" in low) and ("1000" in low or "1000.0" in low) and ("/ 100" in low or "/100" in low) and re.search(r"round\s*\(.+,\s*3\s*\)", refactored_text, re.DOTALL) is not None
        if formula_ok:
            scores["refactored_has_formula"] = 1.0
        # header string presence
        if "batch_id,strain,dry_weight_kg,cbd_percent,est_cbd_g" in refactored_text:
            scores["refactored_header_and_columns"] = 1.0
        # no third-party imports (basic check: disallow common third-party)
        banned = ["pandas", "numpy", "polars"]
        imports = re.findall(r"^\s*(?:from|import)\s+([a-zA-Z0-9_\.]+)", refactored_text, flags=re.MULTILINE)
        if not any(any(b in imp for b in banned) for imp in imports):
            scores["refactored_no_third_party_imports"] = 1.0

    # 3) Inventory checks
    inv = load_json_safe(inventory_json_path)
    if isinstance(inv, list):
        # validate structure
        ok_struct = True
        for item in inv:
            if not isinstance(item, dict):
                ok_struct = False
                break
            if not all(k in item for k in ["relative_path", "size_bytes", "sha256", "role"]):
                ok_struct = False
                break
        if ok_struct:
            scores["inventory_json_valid"] = 1.0
        # coverage and correctness
        # Build expected list of files under input/
        input_root = workspace / "input"
        expected_files = list_input_files(input_root)
        expected_rel = set()
        for p in expected_files:
            expected_rel.add(p.as_posix().replace(workspace.as_posix().rstrip("/") + "/", ""))
        # coverage: every input file present in inventory
        inv_paths = {str(item.get("relative_path")) for item in inv if isinstance(item, dict)}
        if expected_rel and expected_rel.issubset(inv_paths):
            scores["inventory_covers_all_input_files"] = 1.0
        elif not expected_rel and (inv_paths == set()):
            # empty input directory case
            scores["inventory_covers_all_input_files"] = 1.0
        # metadata correctness ratio
        correct = 0
        total = 0
        for item in inv:
            rel = item.get("relative_path")
            if not isinstance(rel, str):
                continue
            p = workspace / rel
            if not p.exists() or not p.is_file():
                continue
            total += 1
            size_ok = isinstance(item.get("size_bytes"), int) and item.get("size_bytes") == p.stat().st_size
            sha = sha256_file(p)
            sha_ok = isinstance(item.get("sha256"), str) and sha is not None and item.get("sha256") == sha
            role = item.get("role")
            role_ok = False
            if rel.startswith("input/src/") and role == "code":
                role_ok = True
            elif rel.startswith("input/data/") and role == "data":
                role_ok = True
            elif rel == "input/README.md" and role == "docs":
                role_ok = True
            # If other files exist under input that are not src/data/README.md, relax role requirement to any of code/data/docs
            elif rel.startswith("input/") and role in {"code", "data", "docs"}:
                role_ok = True
            if size_ok and sha_ok and role_ok:
                correct += 1
        if total > 0:
            scores["inventory_metadata_correct"] = correct / total
        else:
            # If there are no files, consider correct
            scores["inventory_metadata_correct"] = 1.0

    # 4) Validation files and correctness
    all_present = original_csv.exists() and refactored_csv.exists() and comparison_json.exists()
    if all_present:
        scores["validation_files_present"] = 1.0
        comp = load_json_safe(comparison_json)
        left_hash = sha256_file(original_csv)
        right_hash = sha256_file(refactored_csv)
        if isinstance(comp, dict) and isinstance(comp.get("identical"), bool) and isinstance(comp.get("left_sha256"), str) and isinstance(comp.get("right_sha256"), str):
            # correctness of reported hashes
            hashes_match_report = (left_hash == comp.get("left_sha256")) and (right_hash == comp.get("right_sha256"))
            ident_calc = (left_hash == right_hash) if (left_hash is not None and right_hash is not None) else False
            ident_report = comp.get("identical")
            if hashes_match_report and (ident_calc == ident_report):
                scores["validation_comparison_correct"] = 1.0

    # 5) Check CSV content correctness using input data
    expected_rows = None
    if input_csv_path.exists():
        expected_rows = compute_expected_summary_rows(input_csv_path)
    if expected_rows is not None:
        if original_csv.exists():
            scores["original_summary_correct_values"] = check_csv_matches_expected(original_csv, expected_rows)
        if refactored_csv.exists():
            scores["refactored_summary_correct_values"] = check_csv_matches_expected(refactored_csv, expected_rows)

    # 6) Email checks
    email_text = read_text_safe(email_txt)
    if email_text is not None:
        scores["email_present"] = 1.0
        low = email_text.lower()
        # subject line
        if re.search(r"^\s*subject\s*:", email_text, flags=re.IGNORECASE | re.MULTILINE):
            scores["email_mentions_refactored_path"] += 0.5  # temporary accumulation; we'll split below
            # We'll reassign properly after evaluating individual components
            scores["email_mentions_refactored_path"] -= 0.5
        # mentions path to refactored summary
        if "output/validation/refactored_summary.csv" in email_text:
            scores["email_mentions_refactored_path"] = 1.0
        # contains reproduction command
        has_python = "python" in low
        mentions_script = "batch_report_refactored.py" in email_text
        has_args = ("--input" in email_text) and ("--output" in email_text)
        if has_python and mentions_script and has_args:
            scores["email_contains_reproduction_command"] = 1.0
        # mentions verification matches old method
        verification_tokens = ["verified", "verify", "identical", "matches", "match", "same as old", "same as the old", "unchanged"]
        old_tokens = ["old method", "original", "previous", "old script"]
        verif = any(tok in low for tok in verification_tokens)
        old = any(tok in low for tok in old_tokens)
        if verif or old:
            # Require at least indication of matching or identical in context; be tolerant:
            scores["email_mentions_verification"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()