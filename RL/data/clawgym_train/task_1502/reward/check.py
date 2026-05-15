import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows: List[Dict[str, str]] = []
            for row in reader:
                # Normalize keys by stripping whitespace
                normalized = {}
                for k, v in row.items():
                    nk = k.strip() if isinstance(k, str) else k
                    nv = v.strip() if isinstance(v, str) else v
                    normalized[nk] = nv
                rows.append(normalized)
            return headers, rows
    except Exception:
        return None, None


def _is_domain(token: str) -> bool:
    if not token or not isinstance(token, str):
        return False
    t = token.strip()
    # Reject URLs or paths
    if "/" in t or "://" in t or " " in t:
        return False
    # Basic domain regex: label(s).tld
    # Permit subdomains like www.discogs.com
    return bool(re.match(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", t))


def _parse_bool_string(val: str) -> Optional[bool]:
    if val is None:
        return None
    s = str(val).strip().lower()
    if s == "true":
        return True
    if s == "false":
        return False
    return None


def _parse_int_str(val: str) -> Optional[int]:
    if val is None:
        return None
    s = str(val).strip()
    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s)
        except Exception:
            return None
    return None


def _parse_config_yaml_minimal(text: str) -> Optional[Dict]:
    if not text:
        return None
    # Extract minimal keys by regex from YAML
    result = {}
    try:
        # min_sources_per_track
        m = re.search(r"min_sources_per_track\s*:\s*(\d+)", text)
        if m:
            result["min_sources_per_track"] = int(m.group(1))
        # exclude_if_no_source
        m = re.search(r"exclude_if_no_source\s*:\s*(true|false)", text, flags=re.IGNORECASE)
        if m:
            result["exclude_if_no_source"] = m.group(1).strip().lower() == "true"
        # top_k
        m = re.search(r"top_k\s*:\s*(\d+)", text)
        if m:
            result["top_k"] = int(m.group(1))
        # fields_required: capture list items following the key
        fields_required = []
        fr_match = re.search(r"fields_required\s*:\s*(?:\n|\r\n)([\s\S]+?)(?:\n\S|\Z)", text)
        # The above attempts to capture until next unindented key or end
        if fr_match:
            block = fr_match.group(1)
            for line in block.splitlines():
                if re.match(r"^\s*-\s*", line):
                    item = re.sub(r"^\s*-\s*", "", line).strip()
                    if item:
                        fields_required.append(item)
                elif line.strip() == "":
                    continue
                else:
                    # Stop if non-list content appears
                    break
            if fields_required:
                result["fields_required"] = fields_required
        # If none found, attempt a simpler capture of hyphens after the key line
        if "fields_required" not in result:
            lines = text.splitlines()
            capture = False
            fields_required = []
            base_indent = None
            for line in lines:
                if re.match(r"^\s*fields_required\s*:\s*$", line):
                    capture = True
                    base_indent = None
                    continue
                if capture:
                    if line.strip() == "":
                        continue
                    if base_indent is None:
                        m2 = re.match(r"^(\s*)-", line)
                        if m2:
                            base_indent = len(m2.group(1))
                    if re.match(r"^\s*-\s*", line):
                        item = re.sub(r"^\s*-\s*", "", line).strip()
                        if item:
                            fields_required.append(item)
                    else:
                        # likely next key
                        break
            if fields_required:
                result["fields_required"] = fields_required
        return result if result else None
    except Exception:
        return None


def _load_seed(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    seed_path = workspace / "input" / "seed_tracks.csv"
    headers, rows = _safe_read_csv(seed_path)
    return rows, headers


def _load_config(workspace: Path) -> Optional[Dict]:
    cfg_path = workspace / "input" / "scoring_config.yaml"
    text = _safe_read_text(cfg_path)
    if text is None:
        return None
    return _parse_config_yaml_minimal(text)


def _load_metadata(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    md_path = workspace / "output" / "track_metadata.csv"
    headers, rows = _safe_read_csv(md_path)
    return rows, headers


def _load_ranked(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    rp_path = workspace / "output" / "ranked_playlist.csv"
    headers, rows = _safe_read_csv(rp_path)
    return rows, headers


def _safe_read_jsonl(path: Path) -> Optional[List[Dict]]:
    try:
        out = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict):
                    out.append(obj)
                else:
                    return None
        return out
    except Exception:
        return None


def _fraction(numer: int, denom: int) -> float:
    if denom <= 0:
        return 0.0
    if numer < 0:
        numer = 0
    if numer > denom:
        numer = denom
    return float(numer) / float(denom)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "metadata_file_exists": 0.0,
        "metadata_required_columns_present": 0.0,
        "metadata_rows_set_match_seed": 0.0,
        "metadata_order_matches_seed": 0.0,
        "metadata_field_formats_valid": 0.0,
        "sources_domains_valid": 0.0,
        "sources_min_count_compliance": 0.0,
        "evidence_file_exists": 0.0,
        "evidence_jsonl_structure_valid": 0.0,
        "evidence_coverage_per_track_fields": 0.0,
        "evidence_sources_match_metadata_sources": 0.0,
        "logs_validate_before_exists": 0.0,
        "logs_validate_after_exists_and_newer": 0.0,
        "after_validation_compliance": 0.0,
        "ranked_playlist_exists": 0.0,
        "ranked_playlist_structure_valid": 0.0,
        "ranked_playlist_sorted_correctly": 0.0,
        "ranked_playlist_subset_and_fields_match_metadata": 0.0,
        "ranked_playlist_top_k_enforced": 0.0,
        "summary_report_exists": 0.0,
        "summary_sections_present": 0.0,
    }

    # Load inputs
    seed_rows, seed_headers = _load_seed(workspace)
    config = _load_config(workspace)
    md_rows, md_headers = _load_metadata(workspace)

    # Metadata existence
    if md_rows is not None and md_headers is not None:
        scores["metadata_file_exists"] = 1.0

    # Required columns in metadata
    required_cols = ["track_title", "artist", "album", "release_year", "duration_seconds", "benjamin_involved", "sources"]
    if md_headers is not None:
        missing_cols = [c for c in required_cols if c not in md_headers]
        if len(missing_cols) == 0:
            scores["metadata_required_columns_present"] = 1.0

    # Compare rows with seed
    if seed_rows is not None and md_rows is not None:
        seed_keys = [(r.get("track_title", "").strip(), r.get("artist", "").strip(), r.get("album", "").strip()) for r in seed_rows]
        md_keys = [(r.get("track_title", "").strip(), r.get("artist", "").strip(), r.get("album", "").strip()) for r in md_rows]
        # Set match
        if set(seed_keys) == set(md_keys) and len(seed_keys) == len(md_keys):
            scores["metadata_rows_set_match_seed"] = 1.0
        # Order match
        if seed_keys == md_keys:
            scores["metadata_order_matches_seed"] = 1.0

    # Field formats validity
    if md_rows is not None and md_headers is not None and all(c in md_headers for c in required_cols):
        valid_count = 0
        total = len(md_rows)
        for r in md_rows:
            # release_year 4-digit
            ry = r.get("release_year", "")
            year_int = _parse_int_str(ry)
            ry_ok = year_int is not None and re.fullmatch(r"\d{4}", str(ry).strip()) is not None and 1800 <= year_int <= 2100
            # duration_seconds positive int
            ds = r.get("duration_seconds", "")
            ds_int = _parse_int_str(ds)
            ds_ok = ds_int is not None and ds_int > 0
            # benjamin_involved true/false strict
            bi = r.get("benjamin_involved", "")
            bi_parsed = _parse_bool_string(bi)
            bi_ok = bi_parsed is not None
            # sources present non-empty semicolon-separated
            srcs = r.get("sources", "")
            src_ok = isinstance(srcs, str) and srcs.strip() != ""
            if ry_ok and ds_ok and bi_ok and src_ok:
                valid_count += 1
        scores["metadata_field_formats_valid"] = _fraction(valid_count, total if md_rows is not None else 0)

    # Sources domains validity and min count compliance
    min_sources = None
    if config and "min_sources_per_track" in config:
        min_sources = config["min_sources_per_track"]
    if md_rows is not None and "sources" in (md_headers or []):
        dom_valid_count = 0
        min_count_ok = 0
        total = len(md_rows)
        for r in md_rows:
            srcs_field = r.get("sources", "") or ""
            tokens = [t.strip() for t in srcs_field.split(";") if t.strip() != ""]
            # validate all tokens are domains
            if tokens and all(_is_domain(t) for t in tokens):
                dom_valid_count += 1
            # min count compliance
            if min_sources is not None:
                if len(tokens) >= int(min_sources):
                    min_count_ok += 1
            else:
                # If no config, can't assert; keep 0
                pass
        scores["sources_domains_valid"] = _fraction(dom_valid_count, total if md_rows is not None else 0)
        if min_sources is not None:
            scores["sources_min_count_compliance"] = _fraction(min_count_ok, total if md_rows is not None else 0)

    # Evidence checks
    evidence_path = workspace / "output" / "evidence.jsonl"
    evidence_text_list = None
    if evidence_path.exists():
        evidence_text_list = _safe_read_jsonl(evidence_path)
        scores["evidence_file_exists"] = 1.0
    # Structure validity
    evidence_valid = False
    if evidence_text_list is not None:
        # Validate each object
        valid_objs = 0
        for obj in evidence_text_list:
            if not isinstance(obj, dict):
                continue
            fields = {"track_title", "artist", "field", "value", "source_domain"}
            if not fields.issubset(set(obj.keys())):
                continue
            if obj.get("field") not in {"release_year", "duration_seconds", "benjamin_involved"}:
                continue
            if not isinstance(obj.get("track_title"), str) or not isinstance(obj.get("artist"), str):
                continue
            if not _is_domain(str(obj.get("source_domain", ""))):
                continue
            valid_objs += 1
        evidence_valid = (valid_objs == len(evidence_text_list)) and (len(evidence_text_list) > 0)
        scores["evidence_jsonl_structure_valid"] = 1.0 if evidence_valid else 0.0

    # Coverage per track/fields
    if seed_rows is not None and evidence_text_list is not None:
        # Map: (title, artist) -> fields set
        coverage = {}
        for obj in evidence_text_list:
            if not isinstance(obj, dict):
                continue
            key = (str(obj.get("track_title", "")).strip(), str(obj.get("artist", "")).strip())
            fld = obj.get("field")
            sdom = str(obj.get("source_domain", "")).strip()
            if key not in coverage:
                coverage[key] = {"fields": set(), "domains": set()}
            if fld in {"release_year", "duration_seconds", "benjamin_involved"}:
                coverage[key]["fields"].add(fld)
            if _is_domain(sdom):
                coverage[key]["domains"].add(sdom)
        covered = 0
        for r in seed_rows:
            key = (r.get("track_title", "").strip(), r.get("artist", "").strip())
            if key in coverage and coverage[key]["fields"] == {"release_year", "duration_seconds", "benjamin_involved"}:
                covered += 1
        scores["evidence_coverage_per_track_fields"] = _fraction(covered, len(seed_rows) if seed_rows is not None else 0)

    # Evidence sources vs metadata sources: every source in metadata must appear at least once in evidence for that track
    if md_rows is not None and evidence_text_list is not None:
        evidence_domains_by_track = {}
        for obj in evidence_text_list:
            if not isinstance(obj, dict):
                continue
            key = (str(obj.get("track_title", "")).strip(), str(obj.get("artist", "")).strip())
            sdom = str(obj.get("source_domain", "")).strip()
            if _is_domain(sdom):
                evidence_domains_by_track.setdefault(key, set()).add(sdom)
        ok = 0
        total = len(md_rows)
        for r in md_rows:
            key = (r.get("track_title", "").strip(), r.get("artist", "").strip())
            md_srcs = [t.strip() for t in (r.get("sources", "") or "").split(";") if t.strip() != ""]
            if key in evidence_domains_by_track:
                ev_set = evidence_domains_by_track[key]
                # All metadata listed sources should appear in evidence for that track
                if all(s in ev_set for s in md_srcs):
                    ok += 1
        scores["evidence_sources_match_metadata_sources"] = _fraction(ok, total if md_rows is not None else 0)

    # Logs existence and order
    before_log = workspace / "output" / "logs" / "validate_before.txt"
    after_log = workspace / "output" / "logs" / "validate_after.txt"
    if before_log.exists():
        try:
            if before_log.stat().st_size > 0:
                scores["logs_validate_before_exists"] = 1.0
        except Exception:
            pass
    if after_log.exists():
        try:
            if after_log.stat().st_size > 0:
                # check mtime ordering if before exists
                if before_log.exists():
                    try:
                        before_mtime = before_log.stat().st_mtime
                        after_mtime = after_log.stat().st_mtime
                        scores["logs_validate_after_exists_and_newer"] = 1.0 if after_mtime >= before_mtime else 0.0
                    except Exception:
                        scores["logs_validate_after_exists_and_newer"] = 1.0
                else:
                    scores["logs_validate_after_exists_and_newer"] = 1.0
        except Exception:
            pass

    # After validation compliance (all required fields present and min sources met)
    if md_rows is not None and md_headers is not None and config is not None:
        required_fields = config.get("fields_required", [])
        have_all_required = True
        for rf in required_fields:
            if rf not in md_headers:
                have_all_required = False
                break
        rows_ok = 0
        if have_all_required:
            total = len(md_rows)
            for r in md_rows:
                missing = False
                # Required field presence and parseability similar to earlier checks
                if "release_year" in required_fields:
                    ry = r.get("release_year", "")
                    year_int = _parse_int_str(ry)
                    if not (year_int is not None and re.fullmatch(r"\d{4}", str(ry).strip()) and 1800 <= year_int <= 2100):
                        missing = True
                if "duration_seconds" in required_fields:
                    ds = r.get("duration_seconds", "")
                    ds_int = _parse_int_str(ds)
                    if not (ds_int is not None and ds_int > 0):
                        missing = True
                if "benjamin_involved" in required_fields:
                    bi = r.get("benjamin_involved", "")
                    if _parse_bool_string(bi) is None:
                        missing = True
                # sources compliance
                if config.get("exclude_if_no_source", False):
                    min_sources_cfg = config.get("min_sources_per_track", 0)
                    srcs_field = r.get("sources", "") or ""
                    tokens = [t.strip() for t in srcs_field.split(";") if t.strip() != ""]
                    if len(tokens) < int(min_sources_cfg):
                        missing = True
                if not missing:
                    rows_ok += 1
            scores["after_validation_compliance"] = 1.0 if rows_ok == total else 0.0
        else:
            scores["after_validation_compliance"] = 0.0

    # Ranked playlist checks
    rk_rows, rk_headers = _load_ranked(workspace)
    if rk_rows is not None and rk_headers is not None:
        scores["ranked_playlist_exists"] = 1.0

    # Structure valid
    rk_required_cols = ["rank", "score", "track_title", "artist", "album", "release_year", "duration_seconds", "benjamin_involved"]
    if rk_headers is not None:
        if all(c in rk_headers for c in rk_required_cols):
            # All rows parsable types
            all_rows_ok = True
            for i, r in enumerate(rk_rows or []):
                # rank sequential check later; here parseability
                if _parse_int_str(r.get("rank", "")) is None:
                    all_rows_ok = False
                    break
                try:
                    float(str(r.get("score", "")).strip())
                except Exception:
                    all_rows_ok = False
                    break
                if _parse_int_str(r.get("release_year", "")) is None:
                    all_rows_ok = False
                    break
                if _parse_int_str(r.get("duration_seconds", "")) is None:
                    all_rows_ok = False
                    break
                if _parse_bool_string(r.get("benjamin_involved", "")) is None:
                    all_rows_ok = False
                    break
            scores["ranked_playlist_structure_valid"] = 1.0 if all_rows_ok and (rk_rows is not None and len(rk_rows) > 0) else 0.0

    # Sorted correctly by score desc; tie-breakers: duration descending, then title alphabetical ascending
    if rk_rows is not None and rk_headers is not None and scores["ranked_playlist_structure_valid"] > 0:
        try:
            # Sequential rank check
            ranks = [int(r.get("rank", "0")) for r in rk_rows]
            sequential = ranks == list(range(1, len(ranks) + 1))
            # Sorting check
            ok_sort = True
            for i in range(1, len(rk_rows)):
                prev = rk_rows[i - 1]
                cur = rk_rows[i]
                prev_score = float(str(prev.get("score", "")).strip())
                cur_score = float(str(cur.get("score", "")).strip())
                prev_dur = int(str(prev.get("duration_seconds", "")).strip())
                cur_dur = int(str(cur.get("duration_seconds", "")).strip())
                prev_title = str(prev.get("track_title", "")).strip()
                cur_title = str(cur.get("track_title", "")).strip()
                # Must be non-increasing score
                if cur_score > prev_score + 1e-12:
                    ok_sort = False
                    break
                if abs(cur_score - prev_score) <= 1e-12:
                    # tie-breaker: higher duration first
                    if cur_dur > prev_dur:
                        ok_sort = False
                        break
                    if cur_dur == prev_dur:
                        # alphabetical by title ascending
                        if cur_title < prev_title:
                            ok_sort = False
                            break
            scores["ranked_playlist_sorted_correctly"] = 1.0 if (ok_sort and sequential) else 0.0
        except Exception:
            scores["ranked_playlist_sorted_correctly"] = 0.0

    # Ranked playlist subset of metadata and fields match metadata for included rows
    if rk_rows is not None and md_rows is not None and md_headers is not None and rk_headers is not None:
        # Build metadata lookup
        md_map = {}
        for r in md_rows:
            key = (r.get("track_title", "").strip(), r.get("artist", "").strip())
            md_map[key] = r
        match_count = 0
        for r in rk_rows:
            key = (r.get("track_title", "").strip(), r.get("artist", "").strip())
            md = md_map.get(key)
            if not md:
                continue
            # Compare album, release_year, duration_seconds, benjamin_involved
            try:
                if str(r.get("album", "")).strip() != str(md.get("album", "")).strip():
                    continue
                if int(str(r.get("release_year", "")).strip()) != int(str(md.get("release_year", "")).strip()):
                    continue
                if int(str(r.get("duration_seconds", "")).strip()) != int(str(md.get("duration_seconds", "")).strip()):
                    continue
                rb = _parse_bool_string(r.get("benjamin_involved", ""))
                mb = _parse_bool_string(md.get("benjamin_involved", ""))
                if rb is None or mb is None or rb != mb:
                    continue
                match_count += 1
            except Exception:
                continue
        scores["ranked_playlist_subset_and_fields_match_metadata"] = _fraction(match_count, len(rk_rows) if rk_rows is not None else 0)

    # Enforce top_k and eligibility
    if rk_rows is not None and md_rows is not None and config is not None:
        try:
            top_k = int(config.get("top_k", 0))
        except Exception:
            top_k = 0
        exclude_if_no_source = bool(config.get("exclude_if_no_source", False))
        min_sources_cfg = int(config.get("min_sources_per_track", 0)) if "min_sources_per_track" in config else 0
        eligible = 0
        for r in md_rows:
            ok_row = True
            if exclude_if_no_source:
                srcs_field = r.get("sources", "") or ""
                tokens = [t.strip() for t in srcs_field.split(";") if t.strip() != ""]
                if len(tokens) < min_sources_cfg:
                    ok_row = False
            if ok_row:
                eligible += 1
        rk_len = len(rk_rows)
        expected_len = min(top_k, eligible) if top_k > 0 else eligible
        scores["ranked_playlist_top_k_enforced"] = 1.0 if rk_len == expected_len else 0.0

        # Also ensure all ranked rows meet eligibility when exclude_if_no_source
        if exclude_if_no_source:
            all_meet = True
            for r in rk_rows:
                # Find matching metadata row
                key = (r.get("track_title", "").strip(), r.get("artist", "").strip())
                md_match = None
                for md in md_rows:
                    if (md.get("track_title", "").strip(), md.get("artist", "").strip()) == key:
                        md_match = md
                        break
                if md_match is None:
                    all_meet = False
                    break
                srcs_field = md_match.get("sources", "") or ""
                tokens = [t.strip() for t in srcs_field.split(";") if t.strip() != ""]
                if len(tokens) < min_sources_cfg:
                    all_meet = False
                    break
            # If any fail, mark top_k enforcement as failed (stricter)
            if not all_meet:
                scores["ranked_playlist_top_k_enforced"] = 0.0

    # Summary report checks
    summary_path = workspace / "output" / "summary.md"
    summary_text = _safe_read_text(summary_path) if summary_path.exists() else None
    if summary_text is not None:
        scores["summary_report_exists"] = 1.0
        # Sections presence:
        # (a) total tracks processed and excluded by validation rules
        has_total = bool(re.search(r"total\s+tracks?\s+processed.*\d+", summary_text, flags=re.IGNORECASE))
        has_excluded = bool(re.search(r"excluded.*validation.*\d+", summary_text, flags=re.IGNORECASE))
        # (b) explanation referencing scoring and config
        has_scoring_explain = ("scoring" in summary_text.lower()) and ("config" in summary_text.lower() or "input/scoring_config.yaml" in summary_text.lower())
        # (c) bullet list for top 3 tracks' scores
        top3_ok = False
        rk_top3_titles = []
        if _safe_read_csv(workspace / "output" / "ranked_playlist.csv")[1] is not None:
            _, rk_rows_tmp = _safe_read_csv(workspace / "output" / "ranked_playlist.csv")
            if rk_rows_tmp:
                for r in rk_rows_tmp[:3]:
                    rk_top3_titles.append(str(r.get("track_title", "")).strip())
        bullet_lines = [ln for ln in (summary_text.splitlines()) if re.match(r"^\s*[-*]\s+", ln)]
        # Check that at least three bullet lines mention top3 titles if available
        if rk_top3_titles:
            hits = 0
            for t in rk_top3_titles:
                found = any(t in bl for bl in bullet_lines)
                if found:
                    hits += 1
            top3_ok = hits >= min(3, len(rk_top3_titles))
        else:
            # If no ranked file, require at least 3 bullet points as a proxy
            top3_ok = len(bullet_lines) >= 3
        # (d) counts breakdown by benjamin_involved=true/false in ranked set
        has_breakdown_true = bool(re.search(r"benjamin_involved.*true.*\d+", summary_text, flags=re.IGNORECASE))
        has_breakdown_false = bool(re.search(r"benjamin_involved.*false.*\d+", summary_text, flags=re.IGNORECASE))
        all_sections = has_total and has_excluded and has_scoring_explain and top3_ok and has_breakdown_true and has_breakdown_false
        scores["summary_sections_present"] = 1.0 if all_sections else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()