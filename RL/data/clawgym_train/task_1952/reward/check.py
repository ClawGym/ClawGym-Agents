import json
import csv
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _parse_simple_yaml_config(text: str) -> Dict[str, Any]:
    """
    Very small YAML parser tailored to the provided config.yaml structure.
    Handles:
      - top-level simple keys: values (strings, booleans, empty)
      - data: list of mappings with keys: dataset, url, expected_hash, hash_func
    """
    cfg: Dict[str, Any] = {}
    data_list: List[Dict[str, Any]] = []
    in_data = False
    current_item: Optional[Dict[str, Any]] = None

    def _parse_value(val: str) -> Any:
        s = val.strip()
        if s == "" or s == "null" or s == "None":
            return None
        if s.lower() == "true":
            return True
        if s.lower() == "false":
            return False
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1]
        return s

    lines = text.splitlines()
    for line in lines:
        raw = line
        if "#" in line:
            # ignore inline comments after a space-#; keep it simple
            pass
        if not line.strip():
            continue
        # detect data section
        if not in_data:
            m = re.match(r'^(\w+):\s*(.*)$', line.strip())
            if m:
                key, val = m.group(1), m.group(2)
                if key == "data":
                    in_data = True
                    cfg["data"] = data_list
                    continue
                else:
                    cfg[key] = _parse_value(val)
                    continue
        else:
            # inside data:
            if line.strip().startswith("- "):
                # start a new item
                if current_item:
                    data_list.append(current_item)
                current_item = {}
                # could be "- dataset: value" on same line
                after = line.strip()[2:]
                if after:
                    m2 = re.match(r'^(\w+):\s*(.*)$', after)
                    if m2 and current_item is not None:
                        k2, v2 = m2.group(1), m2.group(2)
                        current_item[k2] = _parse_value(v2)
                continue
            else:
                # nested key under current item
                m3 = re.match(r'^\s+(\w+):\s*(.*)$', line)
                if m3 and current_item is not None:
                    k3, v3 = m3.group(1), m3.group(2)
                    current_item[k3] = _parse_value(v3)
                else:
                    # leaving data section if indentation resets and not matching
                    pass
    if in_data and current_item:
        data_list.append(current_item)
    return cfg


def _extract_requirements_lines(text: str) -> List[Tuple[int, str]]:
    res = []
    for idx, line in enumerate(text.splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        res.append((idx, s))
    return res


def _compute_expected_patterns(workspace: Path) -> Dict[str, Any]:
    # Load input files content if present
    pipeline_path = workspace / "input" / "pipeline.py"
    config_path = workspace / "input" / "config.yaml"
    manifest_path = workspace / "input" / "experiment_manifest.csv"
    reqs_path = workspace / "input" / "requirements.txt"

    pipeline_text = _read_text(pipeline_path) or ""
    config_text = _read_text(config_path) or ""
    manifest_rows = _read_csv_dicts(manifest_path) or []
    reqs_text = _read_text(reqs_path) or ""

    cfg = _parse_simple_yaml_config(config_text) if config_text else {}

    # Expected issues / patterns deduced from actual inputs
    expected = {
        "network_tls_verify_false_code": {
            "category": "network_tls",
            "file": str(pipeline_path),
            "evidence_substrs": ["verify=False"],
            "present": "verify=False" in pipeline_text,
        },
        "network_tls_ssl_verify_false_config": {
            "category": "network_tls",
            "file": str(config_path),
            "evidence_substrs": ["ssl_verify", "false"],
            "present": ("ssl_verify" in config_text and re.search(r"ssl_verify:\s*false", config_text) is not None),
        },
        "dynamic_code_eval": {
            "category": "dynamic_code",
            "file": str(pipeline_path),
            "evidence_substrs": ["eval("],
            "present": "eval(" in pipeline_text,
        },
        "weak_hash_md5_code": {
            "category": "weak_hash",
            "file": str(pipeline_path),
            "evidence_substrs": ["hashlib.md5("],
            "present": "hashlib.md5(" in pipeline_text,
        },
        "weak_hash_md5_config": {
            "category": "weak_hash",
            "file": str(config_path),
            "evidence_substrs": ["hash_function", "md5"],
            "present": ("hash_function" in cfg and str(cfg.get("hash_function")).lower() == "md5"),
        },
        "secret_exposure_api_key": {
            "category": "secret_exposure",
            "file": str(config_path),
            "evidence_substrs": ["api_key", str(cfg.get("api_key")) if cfg.get("api_key") else "api_key"],
            "present": bool(cfg.get("api_key")),
        },
        "reproducibility_missing_seed": {
            "category": "reproducibility",
            "file": str(pipeline_path),
            "evidence_substrs": ["np.random.rand", "random_seed"],
            "present": ("np.random.rand" in pipeline_text) or (cfg.get("random_seed") in (None, "", "null")),
        },
    }

    # Dependency pinning expectations
    req_lines = _extract_requirements_lines(reqs_text)
    dep_expectations = []
    for (lineno, line) in req_lines:
        # exact pin if contains '==' and not extras like environment markers; treat strictly
        pinned = "==" in line
        if not pinned:
            dep_expectations.append({
                "category": "dependency_pinning",
                "file": str(reqs_path),
                "line": lineno,
                "requirement_line": line,
                "present": True,
            })
    expected["dependency_issues"] = dep_expectations

    # Metadata extraction from config and manifest
    cfg_data = []
    if isinstance(cfg.get("data"), list):
        for item in cfg["data"]:
            dataset = str(item.get("dataset")) if item.get("dataset") is not None else None
            url = str(item.get("url")) if item.get("url") is not None else None
            expected_hash = str(item.get("expected_hash")) if item.get("expected_hash") is not None else None
            hash_func = str(item.get("hash_func")) if item.get("hash_func") is not None else None
            if dataset and url and expected_hash and hash_func:
                cfg_data.append({
                    "dataset": dataset,
                    "url": url,
                    "expected_hash": expected_hash,
                    "hash_func": hash_func,
                    "source": "config",
                })

    man_data = []
    for row in manifest_rows:
        ds = (row.get("dataset") or "").strip()
        url = (row.get("url") or "").strip()
        eh = (row.get("expected_hash") or "").strip()
        hf = (row.get("hash_func") or "").strip()
        if ds and url and eh and hf:
            man_data.append({
                "dataset": ds,
                "url": url,
                "expected_hash": eh,
                "hash_func": hf,
                "source": "manifest",
            })

    # Build normalized expected datasets allowing 'both' conflicts to use either source values
    cfg_by_ds = {r["dataset"]: r for r in cfg_data}
    man_by_ds = {r["dataset"]: r for r in man_data}
    all_ds = set(cfg_by_ds.keys()) | set(man_by_ds.keys())
    normalized_expected_variants: Dict[str, List[Dict[str, str]]] = {}
    for ds in sorted(all_ds):
        if ds in cfg_by_ds and ds in man_by_ds:
            # both: create acceptable variants using config or manifest fields
            c = cfg_by_ds[ds]
            m = man_by_ds[ds]
            variants = []
            for pick in (c, m):
                variants.append({
                    "dataset": ds,
                    "url": pick["url"],
                    "expected_hash": pick["expected_hash"],
                    "hash_func": pick["hash_func"],
                    "source": "both",
                })
            # also if config and manifest values are equal, only one variant effectively
            # store unique variants
            uniq = []
            seen = set()
            for v in variants:
                key = (v["dataset"], v["url"], v["expected_hash"], v["hash_func"], v["source"])
                if key not in seen:
                    uniq.append(v)
                    seen.add(key)
            normalized_expected_variants[ds] = uniq
        elif ds in cfg_by_ds:
            c = cfg_by_ds[ds]
            normalized_expected_variants[ds] = [{
                "dataset": ds,
                "url": c["url"],
                "expected_hash": c["expected_hash"],
                "hash_func": c["hash_func"],
                "source": "config",
            }]
        else:
            m = man_by_ds[ds]
            normalized_expected_variants[ds] = [{
                "dataset": ds,
                "url": m["url"],
                "expected_hash": m["expected_hash"],
                "hash_func": m["hash_func"],
                "source": "manifest",
            }]

    # Metadata inconsistency expectations
    metadata_issues = []
    # presence mismatches
    only_manifest = sorted(set(man_by_ds.keys()) - set(cfg_by_ds.keys()))
    only_config = sorted(set(cfg_by_ds.keys()) - set(man_by_ds.keys()))
    for ds in only_manifest:
        metadata_issues.append({
            "type": "presence_only_manifest",
            "dataset": ds,
            "category": "metadata_consistency",
            "evidence_substrs": [ds],
            "present": True,
        })
    for ds in only_config:
        metadata_issues.append({
            "type": "presence_only_config",
            "dataset": ds,
            "category": "metadata_consistency",
            "evidence_substrs": [ds],
            "present": True,
        })
    # field conflicts and hash-length sanity
    def _hash_len_ok(hf: str, hexd: str) -> bool:
        if not hf or not hexd:
            return False
        if re.fullmatch(r'[0-9a-fA-F]+', hexd) is None:
            return False
        if hf.lower() == "md5":
            return len(hexd) == 32
        if hf.lower() == "sha256":
            return len(hexd) == 64
        return True

    for ds in sorted(set(cfg_by_ds.keys()) & set(man_by_ds.keys())):
        c = cfg_by_ds[ds]
        m = man_by_ds[ds]
        # conflicts on expected_hash or hash_func
        if (c["expected_hash"] != m["expected_hash"]) or (c["hash_func"].lower() != m["hash_func"].lower()):
            metadata_issues.append({
                "type": "field_conflict",
                "dataset": ds,
                "category": "metadata_consistency",
                "evidence_substrs": [ds, c["expected_hash"], m["expected_hash"]],
                "present": True,
            })
        # hash-length sanity for each source
        if not _hash_len_ok(c["hash_func"], c["expected_hash"]):
            metadata_issues.append({
                "type": "hash_length_mismatch_config",
                "dataset": ds,
                "category": "metadata_consistency",
                "evidence_substrs": [ds, c["hash_func"], c["expected_hash"]],
                "present": True,
            })
        if not _hash_len_ok(m["hash_func"], m["expected_hash"]):
            metadata_issues.append({
                "type": "hash_length_mismatch_manifest",
                "dataset": ds,
                "category": "metadata_consistency",
                "evidence_substrs": [ds, m["hash_func"], m["expected_hash"]],
                "present": True,
            })

    expected["normalized_expected_variants"] = normalized_expected_variants
    expected["metadata_issues"] = metadata_issues

    return expected


def _load_risk_report(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
    report = _read_json(path)
    if not isinstance(report, dict):
        return None, None, None
    issues = report.get("issues")
    summary = report.get("summary")
    if not isinstance(issues, list):
        return report, None, summary if isinstance(summary, dict) else None
    return report, issues, summary if isinstance(summary, dict) else None


def _issues_have_required_fields(issues: List[Dict[str, Any]]) -> bool:
    required = {"id", "category", "severity", "file", "location", "description", "evidence", "recommendation"}
    severities = {"low", "medium", "high"}
    seen_ids = set()
    for it in issues:
        if not isinstance(it, dict):
            return False
        if not required.issubset(it.keys()):
            return False
        if it.get("severity") not in severities:
            return False
        iid = it.get("id")
        if iid in seen_ids:
            return False
        seen_ids.add(iid)
    return True


def _find_issue(issues: List[Dict[str, Any]], category: str, file_substr: Optional[str], evidence_substrs: List[str]) -> bool:
    for it in issues:
        if it.get("category") != category:
            continue
        if file_substr and file_substr not in str(it.get("file", "")):
            continue
        ev = str(it.get("evidence", ""))
        ok = True
        for sub in evidence_substrs:
            if sub and sub not in ev:
                ok = False
                break
        if not ok:
            # allow some to be in description if not in evidence
            desc = str(it.get("description", ""))
            ok2 = True
            for sub in evidence_substrs:
                if sub and (sub not in ev and sub not in desc):
                    ok2 = False
                    break
            if not ok2:
                continue
        return True
    return False


def _summary_matches(summary: Dict[str, Any], issues: List[Dict[str, Any]]) -> Tuple[bool, bool, bool]:
    total_ok = False
    by_cat_ok = False
    by_sev_ok = False
    # compute counts
    by_cat: Dict[str, int] = {}
    by_sev: Dict[str, int] = {}
    for it in issues:
        by_cat[it.get("category")] = by_cat.get(it.get("category"), 0) + 1
        by_sev[it.get("severity")] = by_sev.get(it.get("severity"), 0) + 1
    total = len(issues)

    # try to find total
    def _iter_numbers(d: Any) -> List[int]:
        nums = []
        if isinstance(d, dict):
            for v in d.values():
                nums.extend(_iter_numbers(v))
        elif isinstance(d, list):
            for v in d:
                nums.extend(_iter_numbers(v))
        elif isinstance(d, int):
            nums.append(d)
        return nums

    nums = _iter_numbers(summary)
    if total in nums:
        total_ok = True

    # try category dict(s)
    def _find_dict_match(d: Any, target: Dict[str, int]) -> bool:
        if isinstance(d, dict):
            # keys could be strings to ints
            if all(isinstance(k, str) and isinstance(v, int) for k, v in d.items()):
                # ensure all target items appear with equal counts (allow missing categories that are zero)
                ok = True
                for k, v in target.items():
                    if d.get(k) != v:
                        ok = False
                        break
                if ok:
                    return True
            for v in d.values():
                if _find_dict_match(v, target):
                    return True
        elif isinstance(d, list):
            for v in d:
                if _find_dict_match(v, target):
                    return True
        return False

    by_cat_ok = _find_dict_match(summary, by_cat)
    by_sev_ok = _find_dict_match(summary, by_sev)
    return total_ok, by_cat_ok, by_sev_ok


def _load_normalized_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    # Ensure required columns exactly
    required_cols = ["dataset", "url", "expected_hash", "hash_func", "source"]
    header_ok = True
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None or header != required_cols:
                header_ok = False
    except Exception:
        header_ok = False
    if not header_ok:
        return None
    # Ensure all rows have only required keys
    for r in rows:
        if set(r.keys()) != set(required_cols):
            return None
    return rows


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "outputs_risk_report_exists_and_parseable": 0.0,
        "risk_report_has_required_issue_fields": 0.0,
        "risk_report_includes_verify_false_in_code": 0.0,
        "risk_report_includes_ssl_verify_false_in_config": 0.0,
        "risk_report_includes_dynamic_code_issue": 0.0,
        "risk_report_includes_weak_hash_in_code": 0.0,
        "risk_report_includes_weak_hash_in_config": 0.0,
        "risk_report_includes_secret_exposure": 0.0,
        "risk_report_includes_reproducibility_seed_issue": 0.0,
        "risk_report_includes_dependency_issue_requests": 0.0,
        "risk_report_includes_dependency_issue_pyyaml_ge": 0.0,
        "risk_report_includes_dependency_issue_pandas": 0.0,
        "risk_report_includes_metadata_presence_setC": 0.0,
        "risk_report_includes_metadata_conflict_setB_expected_hash": 0.0,
        "risk_report_includes_metadata_hash_length_mismatch_setB": 0.0,
        "risk_report_summary_total_matches": 0.0,
        "risk_report_summary_category_counts_match": 0.0,
        "risk_report_summary_severity_counts_match": 0.0,
        "findings_csv_exists_and_matches_ids": 0.0,
        "normalized_datasets_exists_and_matches": 0.0,
    }

    # Paths
    outputs_dir = workspace / "outputs"
    risk_report_path = outputs_dir / "risk_report.json"
    findings_csv_path = outputs_dir / "findings.csv"
    normalized_csv_path = outputs_dir / "normalized_datasets.csv"

    # Compute expectations from inputs
    expected = _compute_expected_patterns(workspace)

    # Load risk report
    report, issues, summary = _load_risk_report(risk_report_path)
    if report is not None and isinstance(issues, list):
        scores["outputs_risk_report_exists_and_parseable"] = 1.0
        if _issues_have_required_fields(issues):
            scores["risk_report_has_required_issue_fields"] = 1.0

        # Check core expected issues if present in inputs
        # verify=False in code
        exp = expected.get("network_tls_verify_false_code", {})
        if exp.get("present") and _find_issue(issues, exp["category"], exp["file"], exp["evidence_substrs"]):
            scores["risk_report_includes_verify_false_in_code"] = 1.0

        # ssl_verify: false in config
        exp = expected.get("network_tls_ssl_verify_false_config", {})
        if exp.get("present") and _find_issue(issues, exp["category"], exp["file"], exp["evidence_substrs"]):
            scores["risk_report_includes_ssl_verify_false_in_config"] = 1.0

        # dynamic code eval
        exp = expected.get("dynamic_code_eval", {})
        if exp.get("present") and _find_issue(issues, exp["category"], exp["file"], exp["evidence_substrs"]):
            scores["risk_report_includes_dynamic_code_issue"] = 1.0

        # weak hash in code
        exp = expected.get("weak_hash_md5_code", {})
        if exp.get("present") and _find_issue(issues, exp["category"], exp["file"], exp["evidence_substrs"]):
            scores["risk_report_includes_weak_hash_in_code"] = 1.0

        # weak hash in config
        exp = expected.get("weak_hash_md5_config", {})
        if exp.get("present") and _find_issue(issues, exp["category"], exp["file"], ["hash_function", "md5"]):
            scores["risk_report_includes_weak_hash_in_config"] = 1.0

        # secret exposure
        exp = expected.get("secret_exposure_api_key", {})
        ev_subs = ["api_key"]
        if isinstance(exp.get("evidence_substrs"), list):
            ev_subs = list(exp["evidence_substrs"])
        if exp.get("present") and _find_issue(issues, exp["category"], exp["file"], ev_subs):
            scores["risk_report_includes_secret_exposure"] = 1.0

        # reproducibility
        exp = expected.get("reproducibility_missing_seed", {})
        if exp.get("present") and _find_issue(issues, exp["category"], None, ["np.random"]):
            scores["risk_report_includes_reproducibility_seed_issue"] = 1.0
        elif exp.get("present") and _find_issue(issues, exp["category"], str(workspace / "input" / "config.yaml"), ["random_seed"]):
            scores["risk_report_includes_reproducibility_seed_issue"] = 1.0

        # dependency pinning: search for issues per requirement line
        dep_issues_expect = expected.get("dependency_issues", [])
        # Build a helper to find in issues based on evidence containing the raw requirement line
        def _has_dep_issue(requirement_line: str) -> bool:
            for it in issues:
                if it.get("category") != "dependency_pinning":
                    continue
                if str(workspace / "input" / "requirements.txt") not in str(it.get("file", "")):
                    continue
                ev = str(it.get("evidence", "")) + " " + str(it.get("description", ""))
                if requirement_line in ev:
                    return True
            return False

        # Infer particular lines present
        req_text = _read_text(workspace / "input" / "requirements.txt") or ""
        req_lines = _extract_requirements_lines(req_text)
        req_map = {line: lineno for lineno, line in req_lines}
        # requests (unpinned)
        if "requests" in req_map and _has_dep_issue("requests"):
            scores["risk_report_includes_dependency_issue_requests"] = 1.0
        # PyYAML>=5.1 (loose)
        if "PyYAML>=5.1" in req_map and _has_dep_issue("PyYAML>=5.1"):
            scores["risk_report_includes_dependency_issue_pyyaml_ge"] = 1.0
        # pandas (unpinned)
        if "pandas" in req_map and _has_dep_issue("pandas"):
            scores["risk_report_includes_dependency_issue_pandas"] = 1.0

        # metadata issues from expectations
        # presence only manifest: setC in provided inputs
        for mi in expected.get("metadata_issues", []):
            if mi.get("type") == "presence_only_manifest":
                ds = mi["dataset"]
                if _find_issue(issues, "metadata_consistency", None, [ds]):
                    scores["risk_report_includes_metadata_presence_setC"] = 1.0
                break

        # conflict for setB expected_hash
        conflict_checked = False
        for mi in expected.get("metadata_issues", []):
            if mi.get("type") == "field_conflict" and mi.get("dataset") == "setB":
                subs = [mi["dataset"]]
                subs.extend(mi.get("evidence_substrs", [])[1:])  # include hash values if present
                if _find_issue(issues, "metadata_consistency", None, subs):
                    scores["risk_report_includes_metadata_conflict_setB_expected_hash"] = 1.0
                conflict_checked = True
                break
        if not conflict_checked:
            # fallback: look for any metadata_consistency issue mentioning setB and both files
            if _find_issue(issues, "metadata_consistency", None, ["setB"]):
                scores["risk_report_includes_metadata_conflict_setB_expected_hash"] = 1.0

        # hash length mismatch for setB in config
        for mi in expected.get("metadata_issues", []):
            if mi.get("type") == "hash_length_mismatch_config" and mi.get("dataset") == "setB":
                subs = [mi["dataset"]]
                subs.extend([s for s in mi.get("evidence_substrs", []) if s])
                if _find_issue(issues, "metadata_consistency", str(workspace / "input" / "config.yaml"), subs):
                    scores["risk_report_includes_metadata_hash_length_mismatch_setB"] = 1.0
                break

        # summary checks
        if isinstance(summary, dict):
            total_ok, by_cat_ok, by_sev_ok = _summary_matches(summary, issues)
            scores["risk_report_summary_total_matches"] = 1.0 if total_ok else 0.0
            scores["risk_report_summary_category_counts_match"] = 1.0 if by_cat_ok else 0.0
            scores["risk_report_summary_severity_counts_match"] = 1.0 if by_sev_ok else 0.0
    else:
        # couldn't load issues; keep scores at 0
        pass

    # findings CSV: existence and matches ids from risk report
    findings_rows = _read_csv_dicts(findings_csv_path)
    if findings_rows is not None and isinstance(issues, list):
        # Check columns contain at least id, category, severity, file, location, description
        required_cols = {"id", "category", "severity", "file", "location", "description"}
        header_ok = True
        try:
            with findings_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header is None:
                    header_ok = False
                else:
                    header_set = set(header)
                    if not required_cols.issubset(header_set):
                        header_ok = False
        except Exception:
            header_ok = False

        if header_ok:
            # Map issues by id
            json_by_id = {str(it.get("id")): it for it in issues}
            csv_by_id = {str(r.get("id")): r for r in findings_rows if r.get("id") is not None}
            # All JSON issues must appear in CSV with same id and matching key fields
            all_ok = True
            for iid, it in json_by_id.items():
                r = csv_by_id.get(iid)
                if r is None:
                    all_ok = False
                    break
                for k in ["category", "severity", "file", "location", "description"]:
                    if str(r.get(k)) != str(it.get(k)):
                        all_ok = False
                        break
                if not all_ok:
                    break
            if all_ok:
                scores["findings_csv_exists_and_matches_ids"] = 1.0

    # normalized datasets
    norm_rows = _load_normalized_csv(normalized_csv_path)
    if norm_rows is not None:
        # Build by dataset from normalized rows; require exactly one row per dataset
        # and source in {config, manifest, both}
        valid_sources = {"config", "manifest", "both"}
        by_ds_norm: Dict[str, Dict[str, str]] = {}
        structure_ok = True
        for r in norm_rows:
            if r.get("source") not in valid_sources:
                structure_ok = False
                break
            ds = r.get("dataset")
            if not ds or ds in by_ds_norm:
                structure_ok = False
                break
            by_ds_norm[ds] = r
        if structure_ok:
            # Compare with expected variants: accept if for each dataset, the row matches any acceptable variant exactly
            exp_variants = expected.get("normalized_expected_variants", {})
            all_match = True
            # Must match exactly the same set of datasets
            if set(by_ds_norm.keys()) != set(exp_variants.keys()):
                all_match = False
            else:
                for ds, row in by_ds_norm.items():
                    variants = exp_variants.get(ds, [])
                    if not variants:
                        all_match = False
                        break
                    # row must match one variant exactly on all fields
                    matched = False
                    for v in variants:
                        if (
                            row.get("dataset") == v.get("dataset")
                            and row.get("url") == v.get("url")
                            and row.get("expected_hash") == v.get("expected_hash")
                            and row.get("hash_func") == v.get("hash_func")
                            and row.get("source") == v.get("source")
                        ):
                            matched = True
                            break
                    if not matched:
                        all_match = False
                        break
            if all_match:
                scores["normalized_datasets_exists_and_matches"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()