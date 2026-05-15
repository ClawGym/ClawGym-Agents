import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None


def _compute_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _count_nonempty_lines(path: Path) -> Optional[int]:
    try:
        count = 0
        with path.open("r", encoding="utf-8", newline="") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
    except Exception:
        return None


def _parse_recipients_emails(path: Path) -> Optional[List[str]]:
    parsed = _read_csv(path)
    if not parsed:
        return None
    header, rows = parsed
    try:
        email_idx = header.index("email")
    except ValueError:
        return None
    emails: List[str] = []
    for r in rows:
        if len(r) <= email_idx:
            return None
        emails.append(r[email_idx].strip())
    if not emails:
        return None
    return emails


def _parse_iris_csv_numeric(path: Path) -> Optional[Tuple[List[str], List[Tuple[float, float, float, float, str]]]]:
    parsed = _read_csv(path)
    if not parsed:
        return None
    header, rows = parsed
    expected_header = ["sepal_length", "sepal_width", "petal_length", "petal_width", "species"]
    if header != expected_header:
        return None
    parsed_rows: List[Tuple[float, float, float, float, str]] = []
    for r in rows:
        if len(r) != 5:
            return None
        try:
            sl = float(r[0].strip())
            sw = float(r[1].strip())
            pl = float(r[2].strip())
            pw = float(r[3].strip())
        except Exception:
            return None
        species = r[4].strip()
        if species == "":
            return None
        # Ensure species is categorical: not purely numeric
        try:
            _ = float(species)
            return None
        except Exception:
            pass
        parsed_rows.append((sl, sw, pl, pw, species))
    return header, parsed_rows


def _compute_species_stats(rows: List[Tuple[float, float, float, float, str]]) -> Dict[str, Dict[str, str]]:
    # Returns mapping: species -> {'count': str(int), 'mean_sepal_length': 'x.xxx', ...}
    agg: Dict[str, Dict[str, float]] = {}
    counts: Dict[str, int] = {}
    for sl, sw, pl, pw, sp in rows:
        if sp not in agg:
            agg[sp] = {"sl": 0.0, "sw": 0.0, "pl": 0.0, "pw": 0.0}
            counts[sp] = 0
        agg[sp]["sl"] += sl
        agg[sp]["sw"] += sw
        agg[sp]["pl"] += pl
        agg[sp]["pw"] += pw
        counts[sp] += 1
    out: Dict[str, Dict[str, str]] = {}
    for sp in sorted(agg.keys()):
        c = counts[sp]
        if c == 0:
            # Avoid division by zero: leave out
            continue
        msl = agg[sp]["sl"] / c
        msw = agg[sp]["sw"] / c
        mpl = agg[sp]["pl"] / c
        mpw = agg[sp]["pw"] / c
        out[sp] = {
            "count": str(c),
            "mean_sepal_length": f"{msl:.3f}",
            "mean_sepal_width": f"{msw:.3f}",
            "mean_petal_length": f"{mpl:.3f}",
            "mean_petal_width": f"{mpw:.3f}",
        }
    return out


def _parse_species_stats_csv(path: Path) -> Optional[Tuple[List[str], Dict[str, Dict[str, str]]]]:
    parsed = _read_csv(path)
    if not parsed:
        return None
    header, rows = parsed
    expected_header = [
        "species",
        "count",
        "mean_sepal_length",
        "mean_sepal_width",
        "mean_petal_length",
        "mean_petal_width",
    ]
    if header != expected_header:
        return None
    result: Dict[str, Dict[str, str]] = {}
    for r in rows:
        if len(r) != 6:
            return None
        species = r[0].strip()
        count_str = r[1].strip()
        msl_str = r[2].strip()
        msw_str = r[3].strip()
        mpl_str = r[4].strip()
        mpw_str = r[5].strip()
        # Validate count is integer
        if not re.fullmatch(r"\d+", count_str):
            return None
        # Validate means are numeric and with 3 decimals when formatted
        try:
            msl_val = float(msl_str)
            msw_val = float(msw_str)
            mpl_val = float(mpl_str)
            mpw_val = float(mpw_str)
        except Exception:
            return None
        # Ensure they have exactly 3 decimal places (string format or match pattern)
        # Accept if the string representation exactly equals formatted with 3 decimals
        if msl_str != f"{msl_val:.3f}" or msw_str != f"{msw_val:.3f}" or mpl_str != f"{mpl_val:.3f}" or mpw_str != f"{mpw_val:.3f}":
            return None
        result[species] = {
            "count": count_str,
            "mean_sepal_length": msl_str,
            "mean_sepal_width": msw_str,
            "mean_petal_length": mpl_str,
            "mean_petal_width": mpw_str,
        }
    return header, result


def _parse_email_draft_lines(path: Path) -> Optional[List[str]]:
    txt = _read_text(path)
    if txt is None:
        return None
    # Normalize newlines to '\n', strip trailing spaces on each line for robust comparison where appropriate.
    lines = [line.rstrip("\r\n") for line in txt.splitlines()]
    return lines


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "iris_raw_file_exists": 0.0,
        "iris_sha256_correct": 0.0,
        "iris_csv_header_and_types_valid": 0.0,
        "iris_csv_row_count_matches_raw": 0.0,
        "species_stats_header_and_format_valid": 0.0,
        "species_stats_matches_computed": 0.0,
        "species_count_total_matches_rows": 0.0,
        "email_to_and_subject_valid": 0.0,
        "email_includes_source_line": 0.0,
        "email_totals_checksum_and_species_lines_valid": 0.0,
    }

    # Paths
    raw_path = workspace / "downloads" / "iris.data"
    sha_path = workspace / "outputs" / "iris.sha256"
    iris_csv_path = workspace / "data" / "iris.csv"
    stats_csv_path = workspace / "outputs" / "species_stats.csv"
    email_path = workspace / "outputs" / "email_draft.txt"
    recipients_path = workspace / "input" / "recipients.csv"

    # 1) Raw file presence
    if raw_path.exists() and raw_path.is_file():
        # Non-empty check
        nonempty = False
        try:
            with raw_path.open("rb") as f:
                chunk = f.read(1)
                if chunk:
                    nonempty = True
        except Exception:
            nonempty = False
        if nonempty:
            scores["iris_raw_file_exists"] = 1.0

    # 1) SHA-256 correctness
    sha_expected = None
    raw_hash = None
    if sha_path.exists() and sha_path.is_file() and raw_path.exists():
        sha_text = _read_text(sha_path)
        raw_hash = _compute_sha256(raw_path)
        if sha_text is not None and raw_hash is not None:
            digest = sha_text.strip()
            # Must be exactly 64 hex chars
            if re.fullmatch(r"[0-9a-f]{64}", digest) is not None:
                sha_expected = digest
                if digest == raw_hash:
                    scores["iris_sha256_correct"] = 1.0

    # 2) Parse data/iris.csv header and numeric types
    iris_parsed = _parse_iris_csv_numeric(iris_csv_path)
    total_rows_csv = None
    if iris_parsed is not None:
        _, iris_rows = iris_parsed
        total_rows_csv = len(iris_rows)
        # Validity already enforced by parser
        scores["iris_csv_header_and_types_valid"] = 1.0

    # 2) Row count matches raw
    if raw_path.exists() and iris_parsed is not None:
        raw_nonempty_count = _count_nonempty_lines(raw_path)
        if raw_nonempty_count is not None and total_rows_csv is not None:
            if raw_nonempty_count == total_rows_csv:
                scores["iris_csv_row_count_matches_raw"] = 1.0

    # 3) Species stats header and format validity
    stats_parsed = _parse_species_stats_csv(stats_csv_path)
    if stats_parsed is not None:
        scores["species_stats_header_and_format_valid"] = 1.0

    # 3) Aggregates match computed from iris.csv
    if iris_parsed is not None and stats_parsed is not None:
        _, iris_rows = iris_parsed
        _, stats_map = stats_parsed
        computed = _compute_species_stats(iris_rows)
        # Ensure sets equal
        if set(computed.keys()) == set(stats_map.keys()):
            # Compare per species values exactly
            all_ok = True
            for sp, vals in computed.items():
                target = stats_map.get(sp)
                if target is None:
                    all_ok = False
                    break
                if target.get("count") != vals.get("count"):
                    all_ok = False
                    break
                for k in ["mean_sepal_length", "mean_sepal_width", "mean_petal_length", "mean_petal_width"]:
                    if target.get(k) != vals.get(k):
                        all_ok = False
                        break
                if not all_ok:
                    break
            if all_ok:
                scores["species_stats_matches_computed"] = 1.0

    # 3) Counts sum equals total rows in data/iris.csv
    if stats_parsed is not None and iris_parsed is not None:
        _, stats_map2 = stats_parsed
        try:
            sum_counts = sum(int(v["count"]) for v in stats_map2.values())
            if total_rows_csv is not None and sum_counts == total_rows_csv:
                scores["species_count_total_matches_rows"] = 1.0
        except Exception:
            pass

    # 4) Email draft checks
    email_lines = _parse_email_draft_lines(email_path) if email_path.exists() else None
    recipients_emails = _parse_recipients_emails(recipients_path) if recipients_path.exists() else None

    # To and Subject validity
    if email_lines is not None and len(email_lines) >= 2 and recipients_emails is not None:
        # To: line
        to_line = email_lines[0].strip()
        if to_line.startswith("To:"):
            # accept "To: " with optional space after colon
            to_payload = to_line[len("To:"):].strip()
            split_emails = [e.strip() for e in to_payload.split(",")] if to_payload else []
            if split_emails == recipients_emails:
                # Subject line: accept both ASCII hyphen and non-breaking hyphen variants
                subject_line = email_lines[1].strip()
                subj_ok_variants = [
                    "Subject: Iris dataset summary for cross-platform demo",
                    "Subject: Iris dataset summary for cross‑platform demo",
                ]
                if subject_line in subj_ok_variants:
                    scores["email_to_and_subject_valid"] = 1.0

    # Source line presence
    if email_lines is not None:
        source_ok = False
        for line in email_lines[2:] if len(email_lines) > 2 else []:
            lwr = line.strip()
            if "UCI Machine Learning Repository" in lwr and "Iris dataset" in lwr:
                source_ok = True
                break
        if source_ok:
            scores["email_includes_source_line"] = 1.0

    # Totals, checksum, and species lines validation
    # This check depends on email, iris.csv, species_stats.csv, and iris.sha256 being present/valid
    if email_lines is not None and iris_parsed is not None and stats_parsed is not None:
        _, iris_rows2 = iris_parsed
        _, stats_map3 = stats_parsed
        total_expected = len(iris_rows2)

        # Find Total rows line
        total_line_n = None
        for line in email_lines:
            m = re.fullmatch(r"Total rows:\s*(\d+)\s*", line.strip())
            if m:
                try:
                    total_line_n = int(m.group(1))
                    break
                except Exception:
                    total_line_n = None
        # Find checksum line
        checksum_line_hex = None
        for line in email_lines:
            m = re.fullmatch(r"Checksum\s*\(SHA-256\):\s*([0-9a-fA-F]{64})\s*", line.strip())
            if m:
                checksum_line_hex = m.group(1).lower()
                break

        # Prepare expected species lines strings exactly
        expected_species_lines = set()
        for sp, vals in stats_map3.items():
            expected_line = (
                f"{sp}: count={vals['count']}, "
                f"mean_sepal_length={vals['mean_sepal_length']}, "
                f"mean_sepal_width={vals['mean_sepal_width']}, "
                f"mean_petal_length={vals['mean_petal_length']}, "
                f"mean_petal_width={vals['mean_petal_width']}"
            )
            expected_species_lines.add(expected_line)

        # Check presence of all expected lines (order not enforced)
        email_body_lines = set([l.strip() for l in email_lines])
        species_lines_ok = expected_species_lines.issubset(email_body_lines)

        # Check checksum consistency with outputs/iris.sha256
        sha_file_hex = None
        if sha_path.exists():
            sha_text2 = _read_text(sha_path)
            if sha_text2 is not None:
                dt = sha_text2.strip()
                if re.fullmatch(r"[0-9a-f]{64}", dt):
                    sha_file_hex = dt

        checks_ok = True
        if total_line_n is None or total_line_n != total_expected:
            checks_ok = False
        if sha_file_hex is None or checksum_line_hex is None or checksum_line_hex != sha_file_hex:
            checks_ok = False
        if not species_lines_ok:
            checks_ok = False

        if checks_ok:
            # Also verify that the sum of species counts equals the "Total rows" reported in email
            try:
                sum_counts_email = sum(int(v["count"]) for v in stats_map3.values())
                if sum_counts_email != total_line_n:
                    checks_ok = False
            except Exception:
                checks_ok = False

        if checks_ok:
            scores["email_totals_checksum_and_species_lines_valid"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()