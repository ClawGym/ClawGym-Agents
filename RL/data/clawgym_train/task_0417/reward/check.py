import sys
import json
import csv
import gzip
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Tuple, List, Optional, Any


def _safe_load_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, f"missing_file:{path}"
    except Exception as e:
        return None, f"json_error:{e}"


def _safe_read_text_nonempty(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        data = path.read_text(encoding="utf-8")
        if data.strip() == "":
            return None, "empty_file"
        return data, None
    except FileNotFoundError:
        return None, "missing_file"
    except Exception as e:
        return None, f"read_error:{e}"


def _safe_open_csv_dict_reader(path: Path) -> Tuple[Optional[csv.DictReader], Optional[Any], Optional[str]]:
    try:
        f = path.open("r", encoding="utf-8", newline="")
        reader = csv.DictReader(f)
        # Ensure header exists
        if reader.fieldnames is None:
            f.close()
            return None, None, "missing_header"
        return reader, f, None
    except FileNotFoundError:
        return None, None, "missing_file"
    except Exception as e:
        return None, None, f"csv_error:{e}"


def _sha256_of_file(path: Path) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    try:
        h = hashlib.sha256()
        total = 0
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
                total += len(chunk)
        return h.hexdigest(), total, None
    except FileNotFoundError:
        return None, None, "missing_file"
    except Exception as e:
        return None, None, f"hash_error:{e}"


def _parse_iso8601(s: str) -> bool:
    # Accept common ISO8601 forms: YYYY-MM-DD, with time, with Z or offset
    if not isinstance(s, str):
        return False
    try:
        # Replace Z with +00:00 for fromisoformat
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _iter_title_basics_rows_gz(path: Path, required_cols: List[str]) -> Tuple[Optional[List[str]], Optional[str], Optional[Any]]:
    """
    Returns (columns, error, iterator)
    iterator yields dicts with required columns keys (and others), or None on error.
    """
    try:
        f = gzip.open(path, "rt", encoding="utf-8", newline="")
        header_line = f.readline()
        if not header_line:
            f.close()
            return None, "empty_gz", None
        headers = header_line.rstrip("\n").split("\t")
        col_idx = {name: i for i, name in enumerate(headers)}
        for rc in required_cols:
            if rc not in col_idx:
                f.close()
                return None, f"missing_required_column:{rc}", None

        def _row_iter():
            for line in f:
                parts = line.rstrip("\n").split("\t")
                row = {}
                # Some lines might have fewer columns; guard accesses
                for name in headers:
                    idx = col_idx.get(name)
                    if idx is not None and idx < len(parts):
                        row[name] = parts[idx]
                    else:
                        row[name] = ""
                yield row
            f.close()

        return headers, None, _row_iter()
    except FileNotFoundError:
        return None, "missing_file", None
    except Exception as e:
        return None, f"gz_read_error:{e}", None


def _canonical_pair(a: str, b: str) -> Tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _recompute_counts_and_processed(
    gz_path: Path,
    schema: dict
) -> Tuple[Optional[Dict[Tuple[str, str], int]], Optional[int], Optional[str]]:
    required_columns = schema.get("required_columns", [])
    filter_title_types = schema.get("filter_title_types", [])
    cols, err, it = _iter_title_basics_rows_gz(gz_path, required_columns)
    if err or it is None:
        return None, None, err

    pair_counts: Dict[Tuple[str, str], int] = {}
    processed_titles = 0
    for row in it:
        try:
            title_type = row.get("titleType", "")
            if title_type not in filter_title_types:
                continue
            genres_field = row.get("genres", "")
            if not genres_field or genres_field == r"\N":
                continue
            raw_genres = [g.strip() for g in genres_field.split(",") if g.strip() and g.strip() != r"\N"]
            # Ensure at least two distinct genres
            uniq_genres = sorted(set(raw_genres))
            if len(uniq_genres) < 2:
                continue
            processed_titles += 1
            # Generate unordered canonical pairs without repetition
            for i in range(len(uniq_genres)):
                for j in range(i + 1, len(uniq_genres)):
                    pair = (uniq_genres[i], uniq_genres[j])  # uniq_genres sorted lexicographically
                    pair_counts[pair] = pair_counts.get(pair, 0) + 1
        except Exception:
            # Any malformed row should cause a recomputation failure
            return None, None, "row_parse_error"
    return pair_counts, processed_titles, None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "raw_dataset_present": 0.0,
        "manifest_valid": 0.0,
        "genre_pair_stats_valid": 0.0,
        "pair_counts_recomputed_match": 0.0,
        "processed_title_count_match": 0.0,
        "theme_rollup_valid": 0.0,
        "scripts_present": 0.0,
        "validation_report_present": 0.0,
    }

    # Paths
    raw_path = workspace / "data" / "raw" / "title.basics.tsv.gz"
    manifest_path = workspace / "output" / "manifest.json"
    genre_pairs_csv = workspace / "output" / "genre_pair_stats.csv"
    theme_rollup_csv = workspace / "output" / "theme_pair_rollup.csv"
    validation_md = workspace / "output" / "validation_report.md"
    schema_path = workspace / "input" / "schema_title_basics.json"
    themes_path = workspace / "input" / "themes.json"
    run_script = workspace / "scripts" / "run_pipeline.sh"
    validate_script = workspace / "scripts" / "validate.sh"

    # raw_dataset_present
    try:
        if raw_path.exists() and raw_path.is_file() and raw_path.stat().st_size > 0:
            scores["raw_dataset_present"] = 1.0
    except Exception:
        scores["raw_dataset_present"] = 0.0

    # Load schema and themes (for later)
    schema, schema_err = _safe_load_json(schema_path)
    themes, themes_err = _safe_load_json(themes_path)

    # Manifest validation
    manifest, man_err = _safe_load_json(manifest_path)
    manifest_ok = True
    if manifest is None:
        manifest_ok = False
    else:
        # Required fields and basic types
        required_keys = ["source", "downloaded_at", "raw_file_sha256", "raw_bytes", "processed_title_count", "pair_rows"]
        for k in required_keys:
            if k not in manifest:
                manifest_ok = False
                break
        if manifest_ok:
            if manifest.get("source") != "IMDb Datasets title.basics.tsv.gz":
                manifest_ok = False
            else:
                # downloaded_at ISO8601
                if not _parse_iso8601(manifest.get("downloaded_at", "")):
                    manifest_ok = False
                # raw_bytes and sha256 match actual file if present
                sha_ok = True
                if raw_path.exists():
                    sha, nbytes, sha_err = _sha256_of_file(raw_path)
                    if sha is None or nbytes is None:
                        sha_ok = False
                    else:
                        if manifest.get("raw_file_sha256") != sha:
                            sha_ok = False
                        if manifest.get("raw_bytes") != nbytes:
                            sha_ok = False
                # pair_rows equals number of rows in genre_pair_stats.csv
                pr_ok = True
                if genre_pairs_csv.exists():
                    reader, f_handle, rdr_err = _safe_open_csv_dict_reader(genre_pairs_csv)
                    if reader is None:
                        pr_ok = False
                    else:
                        count_rows = 0
                        try:
                            for _ in reader:
                                count_rows += 1
                            f_handle.close()
                        except Exception:
                            pr_ok = False
                        if manifest.get("pair_rows") != count_rows:
                            pr_ok = False
                manifest_ok = manifest_ok and sha_ok and pr_ok
    scores["manifest_valid"] = 1.0 if manifest_ok else 0.0

    # genre_pair_stats_valid
    gps_valid = True
    gps_pairs = []  # list of tuples (genre_a, genre_b, pair_count)
    if not genre_pairs_csv.exists():
        gps_valid = False
    else:
        reader, f_handle, rdr_err = _safe_open_csv_dict_reader(genre_pairs_csv)
        if reader is None:
            gps_valid = False
        else:
            expected_header = ["genre_a", "genre_b", "pair_count", "median_runtime_minutes", "adult_share"]
            # Validate exact header order
            if reader.fieldnames != expected_header:
                gps_valid = False
            else:
                seen_pairs = set()
                prev_count = None
                try:
                    for row in reader:
                        a = (row.get("genre_a") or "").strip()
                        b = (row.get("genre_b") or "").strip()
                        pc_raw = (row.get("pair_count") or "").strip()
                        adult_share_raw = (row.get("adult_share") or "").strip()
                        # Canonical order a <= b
                        if not a or not b or _canonical_pair(a, b) != (a, b):
                            gps_valid = False
                            break
                        # pair_count integer >= 1
                        try:
                            pc = int(pc_raw)
                        except Exception:
                            gps_valid = False
                            break
                        if pc < 1:
                            gps_valid = False
                            break
                        # adult_share in [0,1]
                        try:
                            as_val = float(adult_share_raw)
                        except Exception:
                            gps_valid = False
                            break
                        if not (0.0 <= as_val <= 1.0):
                            gps_valid = False
                            break
                        # No duplicates
                        key = (a, b)
                        if key in seen_pairs:
                            gps_valid = False
                            break
                        seen_pairs.add(key)
                        # Non-increasing pair_count
                        if prev_count is not None and pc > prev_count:
                            gps_valid = False
                            break
                        prev_count = pc if prev_count is None else min(prev_count, pc)
                        gps_pairs.append((a, b, pc))
                except Exception:
                    gps_valid = False
                finally:
                    try:
                        f_handle.close()
                    except Exception:
                        pass
            # Row count <= 200
            if gps_valid and len(gps_pairs) > 200:
                gps_valid = False
    scores["genre_pair_stats_valid"] = 1.0 if gps_valid else 0.0

    # Recompute pair counts and processed title count, if possible
    recompute_ok = False
    processed_match_ok = False
    pair_counts: Dict[Tuple[str, str], int] = {}
    processed_titles = None
    if schema and schema_err is None and raw_path.exists() and gps_valid and len(gps_pairs) > 0:
        pair_counts, processed_titles, rc_err = _recompute_counts_and_processed(raw_path, schema)
        if rc_err is None and pair_counts is not None and processed_titles is not None:
            # Compare counts for all pairs in CSV
            all_match = True
            for (a, b, pc) in gps_pairs:
                if pair_counts.get((a, b), 0) != pc:
                    all_match = False
                    break
            recompute_ok = all_match

            # Compare processed_title_count in manifest
            if manifest is not None and "processed_title_count" in manifest and isinstance(manifest.get("processed_title_count"), int):
                processed_match_ok = (manifest.get("processed_title_count") == processed_titles)
    scores["pair_counts_recomputed_match"] = 1.0 if recompute_ok else 0.0
    scores["processed_title_count_match"] = 1.0 if processed_match_ok else 0.0

    # theme_rollup_valid
    theme_valid = True
    if not theme_rollup_csv.exists():
        theme_valid = False
    else:
        reader, f_handle, rdr_err = _safe_open_csv_dict_reader(theme_rollup_csv)
        if reader is None:
            theme_valid = False
        else:
            expected_header = ["theme", "rank", "genre_a", "genre_b", "pair_count"]
            if reader.fieldnames != expected_header:
                theme_valid = False
            else:
                # Build set of top pairs from genre_pair_stats.csv
                top_pairs_set = set((a, b) for (a, b, _) in gps_pairs) if gps_valid else set()
                # Load themes
                if themes is None or themes_err is not None or not isinstance(themes, dict):
                    theme_valid = False
                else:
                    # Normalize themes genre sets
                    theme_genres: Dict[str, set] = {}
                    for k, v in themes.items():
                        try:
                            theme_genres[k] = set([str(x) for x in v])
                        except Exception:
                            theme_valid = False
                            break
                    # Validate rows
                    by_theme: Dict[str, List[Tuple[int, str, str, int]]] = {}
                    try:
                        for row in reader:
                            th = (row.get("theme") or "").strip()
                            rk_raw = (row.get("rank") or "").strip()
                            a = (row.get("genre_a") or "").strip()
                            b = (row.get("genre_b") or "").strip()
                            pc_raw = (row.get("pair_count") or "").strip()
                            # Theme must be known
                            if th not in theme_genres:
                                theme_valid = False
                                break
                            # rank integer starting at 1
                            try:
                                rk = int(rk_raw)
                            except Exception:
                                theme_valid = False
                                break
                            # pair_count integer
                            try:
                                pc = int(pc_raw)
                            except Exception:
                                theme_valid = False
                                break
                            # Pair canonical and subset of top-200
                            if _canonical_pair(a, b) != (a, b):
                                theme_valid = False
                                break
                            if (a, b) not in top_pairs_set:
                                theme_valid = False
                                break
                            # Both genres in theme set
                            if a not in theme_genres[th] or b not in theme_genres[th]:
                                theme_valid = False
                                break
                            by_theme.setdefault(th, []).append((rk, a, b, pc))
                    except Exception:
                        theme_valid = False
                    # Per-theme constraints
                    if theme_valid:
                        for th, rows in by_theme.items():
                            # Up to top 5
                            if len(rows) > 5:
                                theme_valid = False
                                break
                            # Ranks must be 1..N with no gaps
                            ranks = sorted([rk for (rk, _, _, _) in rows])
                            if ranks != list(range(1, len(rows) + 1)):
                                theme_valid = False
                                break
                            # pair_count non-increasing by rank order
                            rows_sorted_by_rank = sorted(rows, key=lambda x: x[0])
                            prev_pc = None
                            for (rk, a, b, pc) in rows_sorted_by_rank:
                                if prev_pc is not None and pc > prev_pc:
                                    theme_valid = False
                                    break
                                prev_pc = pc if prev_pc is None else min(prev_pc, pc)
                            if not theme_valid:
                                break
            try:
                if f_handle:
                    f_handle.close()
            except Exception:
                pass
    scores["theme_rollup_valid"] = 1.0 if theme_valid else 0.0

    # scripts_present
    scripts_ok = True
    for p in [run_script, validate_script]:
        try:
            if not p.exists() or not p.is_file():
                scripts_ok = False
                break
            text, err = _safe_read_text_nonempty(p)
            if err is not None:
                scripts_ok = False
                break
            # Must start with shebang
            first_line = text.splitlines()[0].strip() if text else ""
            if not first_line.startswith("#!"):
                scripts_ok = False
                break
        except Exception:
            scripts_ok = False
            break
    scores["scripts_present"] = 1.0 if scripts_ok else 0.0

    # validation_report_present
    val_text, val_err = _safe_read_text_nonempty(validation_md)
    if val_text is not None and val_text.strip():
        scores["validation_report_present"] = 1.0
    else:
        scores["validation_report_present"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    # Maintain insertion order of keys
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()