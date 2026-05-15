import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames
            return rows, header
    except Exception:
        return None, None


def compute_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def file_size(path: Path) -> Optional[int]:
    try:
        return path.stat().st_size
    except Exception:
        return None


def list_files_recursive(base: Path) -> List[Path]:
    if not base.exists():
        return []
    result = []
    for p in base.rglob("*"):
        if p.is_file():
            result.append(p)
    return result


def parse_scalar(val: str) -> Any:
    v = val.strip()
    if v and not (v.startswith('"') or v.startswith("'")):
        if " #" in v:
            v = v.split(" #", 1)[0].strip()
        elif "#" in v and not v.startswith("#"):
            v = v.split("#", 1)[0].strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1]
    lower = v.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    return v


def parse_pipeline_yaml(text: str) -> Optional[Dict[str, Any]]:
    if text is None:
        return None
    maintainer = None
    time_window = {"start": None, "end": None}
    output = {"raw_dir": None, "out_dir": None}
    cache = {"enabled": None, "dir": None}
    sources: List[Dict[str, Any]] = []

    current_section: Optional[str] = None
    in_source_item = False
    current_source: Optional[Dict[str, Any]] = None

    lines = text.splitlines()
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if ":" in stripped and not stripped.startswith("- "):
            key, rest = stripped.split(":", 1)
            key = key.strip()
            rest_val = rest.strip()
            if rest_val == "":
                current_section = key
                if key != "sources":
                    in_source_item = False
                    current_source = None
                continue
            val = parse_scalar(rest_val)
            if current_section is None:
                if key == "maintainer":
                    maintainer = val
            elif current_section == "time_window":
                if key in time_window:
                    time_window[key] = val
            elif current_section == "output":
                if key in output:
                    output[key] = val
            elif current_section == "cache":
                if key in cache:
                    cache[key] = val
            elif current_section == "sources":
                if current_source is None:
                    current_source = {}
                    sources.append(current_source)
                current_source[key] = val
            continue

        if stripped.startswith("- "):
            if current_section == "sources":
                in_source_item = True
                after_dash = stripped[2:].strip()
                current_source = {}
                sources.append(current_source)
                if after_dash:
                    if ":" in after_dash:
                        skey, srest = after_dash.split(":", 1)
                        current_source[skey.strip()] = parse_scalar(srest.strip())
                continue

        if current_section == "sources" and in_source_item and current_source is not None:
            if ":" in stripped:
                skey, srest = stripped.split(":", 1)
                current_source[skey.strip()] = parse_scalar(srest.strip())
            continue

    result = {
        "maintainer": maintainer,
        "time_window": time_window,
        "output": output,
        "cache": cache,
        "sources": sources,
    }
    return result


def detect_dirs(workspace: Path) -> Tuple[Path, Path]:
    out_dir = workspace / "out"
    raw_dir = workspace / "data" / "raw"

    resolved_cfg_path = workspace / "out" / "resolved_config.json"
    rc = load_json(resolved_cfg_path)
    if isinstance(rc, dict):
        try:
            out_dir_str = rc.get("output", {}).get("out_dir")
            raw_dir_str = rc.get("output", {}).get("raw_dir")
            if isinstance(out_dir_str, str) and out_dir_str:
                out_dir = workspace / out_dir_str
            if isinstance(raw_dir_str, str) and raw_dir_str:
                raw_dir = workspace / raw_dir_str
            return raw_dir, out_dir
        except Exception:
            pass

    cfg_text = read_text(workspace / "config" / "pipeline.yaml")
    parsed = parse_pipeline_yaml(cfg_text) if cfg_text else None
    if isinstance(parsed, dict):
        out_dir_str = parsed.get("output", {}).get("out_dir")
        raw_dir_str = parsed.get("output", {}).get("raw_dir")
        if isinstance(out_dir_str, str) and out_dir_str:
            out_dir = workspace / out_dir_str
        if isinstance(raw_dir_str, str) and raw_dir_str:
            raw_dir = workspace / raw_dir_str
    return raw_dir, out_dir


def is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def parse_raw_jsonl_counts(raw_dir: Path) -> Tuple[Dict[Tuple[str, str], int], bool]:
    counts: Dict[Tuple[str, str], int] = {}
    ok = True
    if not raw_dir.exists():
        return counts, False
    for term_dir in sorted([p for p in raw_dir.iterdir() if p.is_dir()]):
        term = term_dir.name
        for fp in sorted(term_dir.glob("*.jsonl")):
            name = fp.name
            m = re.fullmatch(r"(\d{4})-(\d{2})\.jsonl", name)
            if not m:
                ok = False
                continue
            ym = f"{m.group(1)}-{m.group(2)}"
            try:
                cnt = 0
                with fp.open("r", encoding="utf-8") as f:
                    for line in f:
                        s = line.strip()
                        if not s:
                            continue
                        try:
                            json.loads(s)
                            cnt += 1
                        except Exception:
                            ok = False
                counts[(term, ym)] = cnt
            except Exception:
                ok = False
                continue
    if len(counts) == 0:
        return counts, False
    return counts, ok


def parse_monthly_counts_csv(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], bool]:
    rows, header = parse_csv_dicts(path)
    if rows is None or header is None:
        return None, False
    expected_header = ["term", "year", "month", "doc_count"]
    if header != expected_header:
        return None, False
    parsed_rows: List[Dict[str, Any]] = []
    try:
        for r in rows:
            term = r.get("term")
            year_s = r.get("year")
            month_s = r.get("month")
            dc_s = r.get("doc_count")
            if term is None or year_s is None or month_s is None or dc_s is None:
                return None, False
            year = int(year_s)
            month = int(month_s)
            if not (1 <= month <= 12):
                return None, False
            doc_count = int(dc_s)
            if doc_count < 0:
                return None, False
            parsed_rows.append({"term": term, "year": year, "month": month, "doc_count": doc_count})
        return parsed_rows, True
    except Exception:
        return None, False


def aggregate_counts_from_rows(rows: List[Dict[str, Any]]) -> Tuple[Dict[Tuple[str, str], int], Dict[str, int], int]:
    per_tm: Dict[Tuple[str, str], int] = {}
    per_term: Dict[str, int] = {}
    total = 0
    for r in rows:
        term = r["term"]
        ym = f"{r['year']:04d}-{r['month']:02d}"
        c = r["doc_count"]
        per_tm[(term, ym)] = per_tm.get((term, ym), 0) + c
        per_term[term] = per_term.get(term, 0) + c
        total += c
    return per_tm, per_term, total


def load_team_assignments(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    return parse_csv_dicts(path)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_values_updated": 0.0,
        "sources_reference_intact": 0.0,
        "runner_script_present_and_executable": 0.0,
        "raw_jsonl_structure_and_parsing": 0.0,
        "monthly_counts_csv_valid": 0.0,
        "assignments_summary_csv_valid": 0.0,
        "summary_json_valid": 0.0,
        "resolved_config_matches_pipeline": 0.0,
        "manifest_covers_files": 0.0,
    }

    cfg_path = workspace / "config" / "pipeline.yaml"
    cfg_text = read_text(cfg_path)
    parsed_cfg = parse_pipeline_yaml(cfg_text) if cfg_text else None
    config_ok = False
    if isinstance(parsed_cfg, dict):
        maintainer_ok = parsed_cfg.get("maintainer") == "Alex Carter"
        tw = parsed_cfg.get("time_window", {})
        tw_ok = isinstance(tw, dict) and tw.get("start") == "2019-01-01" and tw.get("end") == "2021-12-31"
        out = parsed_cfg.get("output", {})
        out_ok = isinstance(out, dict) and out.get("raw_dir") == "data/raw" and out.get("out_dir") == "out"
        cache = parsed_cfg.get("cache", {})
        cache_ok = isinstance(cache, dict) and cache.get("enabled") is True and cache.get("dir") == "data/cache"
        if maintainer_ok and tw_ok and out_ok and cache_ok:
            config_ok = True
            scores["config_values_updated"] = 1.0

        # Only award this check if the config has been updated to required values
        if config_ok:
            sources = parsed_cfg.get("sources")
            src_ok = False
            if isinstance(sources, list) and len(sources) >= 1 and isinstance(sources[0], dict):
                s0 = sources[0]
                src_ok = (
                    s0.get("name") == "FederalRegister"
                    and s0.get("domain") == "federalregister.gov"
                    and s0.get("endpoint") == "documents"
                )
            if src_ok:
                scores["sources_reference_intact"] = 1.0

    raw_dir, out_dir = detect_dirs(workspace)

    runner = workspace / "scripts" / "run.sh"
    if runner.exists():
        try:
            content = read_text(runner) or ""
            lines = content.splitlines()
            first_line = lines[0].lower() if lines else ""
            has_shebang = content.startswith("#!") or "bash" in first_line
            has_set_e = "set -e" in content or "set -eo" in content
            mentions_summary = "summary.json" in content
            executable = os.access(runner, os.X_OK)
            if has_shebang and has_set_e and mentions_summary and executable:
                scores["runner_script_present_and_executable"] = 1.0
        except Exception:
            pass

    raw_counts, raw_ok = parse_raw_jsonl_counts(raw_dir)
    if raw_ok:
        scores["raw_jsonl_structure_and_parsing"] = 1.0

    monthly_counts_path = out_dir / "monthly_counts.csv"
    mc_rows, mc_ok = parse_monthly_counts_csv(monthly_counts_path)
    monthly_counts_valid = False
    if mc_ok and mc_rows is not None:
        per_tm_from_csv, _per_term_from_csv, _total_from_csv = aggregate_counts_from_rows(mc_rows)
        per_tm_from_raw = raw_counts
        if len(per_tm_from_raw) > 0:
            csv_keys = set(per_tm_from_csv.keys())
            raw_keys = set(per_tm_from_raw.keys())
            if csv_keys == raw_keys:
                all_counts_match = all(per_tm_from_csv[k] == per_tm_from_raw[k] for k in raw_keys)
                if all_counts_match:
                    monthly_counts_valid = True
        else:
            monthly_counts_valid = (len(mc_rows) == 0)
    if monthly_counts_valid:
        scores["monthly_counts_csv_valid"] = 1.0

    assignments_csv_path = workspace / "input" / "team_assignments.csv"
    as_rows, as_header = load_team_assignments(assignments_csv_path)
    assignments_valid = False
    if as_rows is not None and as_header is not None:
        out_assign_path = out_dir / "assignments_summary.csv"
        out_rows, out_header = parse_csv_dicts(out_assign_path)
        if out_rows is not None and out_header is not None and out_header == ["assignee", "term", "total_docs_for_term", "share_of_all_docs"]:
            term_totals: Dict[str, int] = {}
            for (term, ym), c in raw_counts.items():
                term_totals[term] = term_totals.get(term, 0) + c
            total_all = sum(term_totals.values()) if term_totals else 0
            expected: Dict[Tuple[str, str], Tuple[int, float]] = {}
            for r in as_rows:
                assignee = r.get("assignee")
                term = r.get("term")
                if assignee is None or term is None:
                    expected = {}
                    break
                td = term_totals.get(term, 0)
                share = 0.0
                if total_all > 0:
                    share = round(td / total_all, 4)
                expected[(assignee, term)] = (td, share)
            if expected:
                actual: Dict[Tuple[str, str], Tuple[int, float]] = {}
                try:
                    for r in out_rows:
                        assignee = r.get("assignee")
                        term = r.get("term")
                        td_s = r.get("total_docs_for_term")
                        share_s = r.get("share_of_all_docs")
                        if None in (assignee, term, td_s, share_s):
                            raise ValueError("Missing fields in assignments_summary.csv")
                        td = int(td_s)
                        share = float(share_s)
                        actual[(assignee, term)] = (td, share)
                    if set(actual.keys()) == set(expected.keys()):
                        all_good = True
                        for k, (exp_td, exp_share) in expected.items():
                            act_td, act_share = actual[k]
                            if act_td != exp_td:
                                all_good = False
                                break
                            if abs(act_share - exp_share) > 0.0001:
                                all_good = False
                                break
                        if all_good:
                            assignments_valid = True
                except Exception:
                    assignments_valid = False
    if assignments_valid:
        scores["assignments_summary_csv_valid"] = 1.0

    summary_path = out_dir / "summary.json"
    summary = load_json(summary_path)
    summary_valid = False
    if isinstance(summary, dict):
        src_ok = summary.get("source") == "FederalRegister"
        tw_sum = summary.get("time_window", {})
        tw_cfg_ok = False
        if isinstance(parsed_cfg, dict):
            cfg_tw = parsed_cfg.get("time_window", {})
            if isinstance(cfg_tw, dict) and isinstance(tw_sum, dict):
                tw_cfg_ok = (tw_sum.get("start") == cfg_tw.get("start") and tw_sum.get("end") == cfg_tw.get("end"))
        term_totals: Dict[str, int] = {}
        for (term, _ym), c in raw_counts.items():
            term_totals[term] = term_totals.get(term, 0) + c
        total_all = sum(term_totals.values()) if term_totals else 0
        per_term_totals = summary.get("per_term_totals")
        total_docs_all_terms = summary.get("total_docs_all_terms")
        gen_at = summary.get("generated_at")
        per_term_ok = isinstance(per_term_totals, dict)
        totals_match = False
        if per_term_ok:
            subset_match = True
            for t, cnt in term_totals.items():
                if per_term_totals.get(t) != cnt:
                    subset_match = False
                    break
            totals_match = subset_match and (total_docs_all_terms == total_all)
        gen_ok = is_iso8601(gen_at) if isinstance(gen_at, str) else False
        if src_ok and tw_cfg_ok and per_term_ok and totals_match and gen_ok:
            summary_valid = True
    if summary_valid:
        scores["summary_json_valid"] = 1.0

    resolved_cfg_path = out_dir / "resolved_config.json"
    resolved = load_json(resolved_cfg_path)
    rc_valid = False
    if isinstance(resolved, dict) and isinstance(parsed_cfg, dict):
        try:
            rc_maint = resolved.get("maintainer")
            rc_tw = resolved.get("time_window", {})
            rc_out = resolved.get("output", {})
            rc_cache = resolved.get("cache", {})
            rc_src = resolved.get("source", {})
            c_maint = parsed_cfg.get("maintainer")
            c_tw = parsed_cfg.get("time_window", {})
            c_out = parsed_cfg.get("output", {})
            c_cache = parsed_cfg.get("cache", {})
            c_src_list = parsed_cfg.get("sources", [])
            c_src = c_src_list[0] if (isinstance(c_src_list, list) and c_src_list) else {}
            rc_ok = (
                rc_maint == c_maint
                and isinstance(rc_tw, dict)
                and rc_tw.get("start") == c_tw.get("start")
                and rc_tw.get("end") == c_tw.get("end")
                and isinstance(rc_out, dict)
                and rc_out.get("raw_dir") == c_out.get("raw_dir")
                and rc_out.get("out_dir") == c_out.get("out_dir")
                and isinstance(rc_cache, dict)
                and rc_cache.get("enabled") == c_cache.get("enabled")
                and rc_cache.get("dir") == c_cache.get("dir")
                and isinstance(rc_src, dict)
                and rc_src.get("name") == c_src.get("name")
                and rc_src.get("domain") == c_src.get("domain")
                and rc_src.get("endpoint") == c_src.get("endpoint")
            )
            if rc_ok:
                rc_valid = True
        except Exception:
            rc_valid = False
    if rc_valid:
        scores["resolved_config_matches_pipeline"] = 1.0

    manifest_path = out_dir / "manifest.json"
    manifest = load_json(manifest_path)
    manifest_valid = False
    if isinstance(manifest, list):
        manifest_index: Dict[str, Dict[str, Any]] = {}
        for entry in manifest:
            if not isinstance(entry, dict):
                manifest_index = {}
                break
            p = entry.get("path")
            b = entry.get("bytes")
            s = entry.get("sha256")
            if not isinstance(p, str) or not isinstance(b, int) or not isinstance(s, str):
                manifest_index = {}
                break
            manifest_index[p] = entry
        if manifest_index:
            expected_files: List[Path] = []
            if out_dir.exists():
                expected_files.extend(list_files_recursive(out_dir))
            if raw_dir.exists():
                expected_files.extend(list_files_recursive(raw_dir))
            all_ok = True
            for f in expected_files:
                try:
                    rel = f.relative_to(workspace).as_posix()
                except Exception:
                    rel = f.as_posix()
                entry = manifest_index.get(rel)
                if entry is None:
                    all_ok = False
                    break
                bytes_actual = file_size(f)
                sha_actual = compute_sha256(f)
                if bytes_actual is None or sha_actual is None:
                    all_ok = False
                    break
                if entry.get("bytes") != bytes_actual or entry.get("sha256") != sha_actual:
                    all_ok = False
                    break
            if expected_files and all_ok:
                manifest_valid = True
    if manifest_valid:
        scores["manifest_covers_files"] = 1.0

    return scores


def main() -> None:
        workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
        result = grade([], workspace_path)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()