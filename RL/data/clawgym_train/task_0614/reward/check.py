import json
import os
import re
import sys
import csv

def read_text(p):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(p):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_simple_yaml_kv_numbers(p):
    # Minimal YAML parser for flat key: value pairs (numbers). Ignores comments and blank lines.
    text = read_text(p)
    if text is None:
        return None
    result = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # handle inline comments
        if "#" in s:
            s = s.split("#", 1)[0].strip()
        if ":" not in s:
            continue
        k, v = s.split(":", 1)
        key = k.strip()
        val = v.strip()
        if val == "":
            continue
        # remove quotes if any
        if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
            val = val[1:-1]
        try:
            num = float(val)
            result[key] = num
        except ValueError:
            # try int
            try:
                numi = int(val)
                result[key] = float(numi)
            except ValueError:
                # Not a number, return as string to allow later comparison if needed
                result[key] = val
    return result

def parse_versions_file(p):
    text = read_text(p)
    if text is None:
        return None
    pre = None
    post = None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" in s:
            k, v = s.split("=", 1)
            k = k.strip().lower()
            v = v.strip()
            if k == "pre":
                pre = v
            elif k == "post":
                post = v
    if pre and post:
        return {"pre": pre, "post": post}
    return None

def load_csv(p):
    try:
        with open(p, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None

def load_tsv(p):
    try:
        with open(p, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None

def is_number(x):
    try:
        float(x)
        return True
    except Exception:
        return False

def in_0_1(x):
    try:
        xf = float(x)
        return 0.0 <= xf <= 1.0
    except Exception:
        return False

def is_int_str(x):
    try:
        xi = int(str(x))
        return True
    except Exception:
        return False

def word_count(s):
    # count words by whitespace
    tokens = re.findall(r"\b\w+\b", s)
    return len(tokens)

def extract_section(markdown_text, heading):
    # Returns content between the given H2 heading line and the next H2 or end
    # heading should be like "## Executive Summary"
    pattern = re.compile(r"^##\s+.*", re.MULTILINE)
    matches = list(pattern.finditer(markdown_text))
    start_idx = None
    end_idx = len(markdown_text)
    for i, m in enumerate(matches):
        if markdown_text[m.start():m.end()].strip() == heading:
            start_idx = m.end()
            # find next heading after this
            if i + 1 < len(matches):
                end_idx = matches[i+1].start()
            break
    if start_idx is None:
        return None
    return markdown_text[start_idx:end_idx]

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "all_files_present": False,
        "summary_json_valid": False,
        "summary_versions_match": False,
        "summary_weights_match": False,
        "summary_top_clusters_valid": False,
        "summary_positive_signals_valid": False,
        "summary_backlog_overview_valid": False,
        "summary_release_risk_refs_valid": False,
        "clusters_csv_valid": False,
        "clusters_platform_coverage": False,
        "backlog_tsv_valid": False,
        "backlog_refs_valid": False,
        "backlog_min_rows": False,
        "trend_json_valid": False,
        "trend_versions_match": False,
        "trend_refs_valid": False,
        "trend_exclusive_categories": False,
        "trend_has_reg_or_emerged": False,
        "report_has_sections": False,
        "report_mentions_versions": False,
        "report_length_ok": False,
        "report_risk_section_refs": False,
    }

    # Required files
    summary_path = os.path.join(output_dir, "summary.json")
    clusters_path = os.path.join(output_dir, "clusters.csv")
    backlog_path = os.path.join(output_dir, "backlog.tsv")
    trend_path = os.path.join(output_dir, "trend_comparison.json")
    report_path = os.path.join(output_dir, "report.md")

    required = [summary_path, clusters_path, backlog_path, trend_path, report_path]
    if all(os.path.isfile(p) for p in required):
        checks["all_files_present"] = True

    # Load inputs for cross-checks
    versions = parse_versions_file(os.path.join(input_dir, "versions.txt"))
    weights = parse_simple_yaml_kv_numbers(os.path.join(input_dir, "weights.yaml"))
    platforms = read_json(os.path.join(input_dir, "platforms.json"))

    # Pre-parse clusters.csv to build set of cluster_ids
    clusters_fieldnames, clusters_rows = (None, None)
    clusters_ids_set = set()
    clusters_platforms_seen = set()
    summary_data = None
    trend_data = None
    report_text = None

    # Validate clusters.csv
    if os.path.isfile(clusters_path):
        clusters_fieldnames, clusters_rows = load_csv(clusters_path)
        header_expected = ["cluster_id","theme","product_area","platform","version","frequency","severity_score","recency_score","sample_review_ids"]
        if clusters_fieldnames == header_expected and clusters_rows is not None and len(clusters_rows) > 0:
            # Validate each row
            valid_rows = True
            for row in clusters_rows:
                cid = row.get("cluster_id","")
                theme = row.get("theme","")
                product_area = row.get("product_area","")
                platform = row.get("platform","")
                version = row.get("version","")
                freq = row.get("frequency","")
                sev = row.get("severity_score","")
                rec = row.get("recency_score","")
                # Basic validations
                if not re.fullmatch(r"C\d{3}", cid or ""):
                    valid_rows = False
                    break
                if not theme or not product_area:
                    valid_rows = False
                    break
                # platform must be among allowed platforms (if available)
                if isinstance(platforms, list):
                    if platform not in platforms:
                        valid_rows = False
                        break
                else:
                    # If platforms.json missing or malformed, do not award positive credit here
                    valid_rows = False
                    break
                # version must match either versions.txt pre/post if available; otherwise cannot pass
                if isinstance(versions, dict):
                    if version not in (versions.get("pre"), versions.get("post")):
                        valid_rows = False
                        break
                else:
                    valid_rows = False
                    break
                if not is_int_str(freq) or int(freq) < 1:
                    valid_rows = False
                    break
                if not is_number(sev) or not in_0_1(sev):
                    valid_rows = False
                    break
                if not is_number(rec) or not in_0_1(rec):
                    valid_rows = False
                    break
                # sample_review_ids may be empty or semicolon-separated list
                # No strict validation needed beyond being a string
                clusters_ids_set.add(cid)
                clusters_platforms_seen.add(platform)
            if valid_rows:
                checks["clusters_csv_valid"] = True
                # platform coverage: at least one row per platform listed in platforms.json
                if isinstance(platforms, list) and len(platforms) > 0:
                    missing = [p for p in platforms if p not in clusters_platforms_seen]
                    checks["clusters_platform_coverage"] = (len(missing) == 0)

    # Validate summary.json
    if os.path.isfile(summary_path):
        summary_data = read_json(summary_path)
        if isinstance(summary_data, dict):
            required_keys = ["version_pre","version_post","scoring_weights","top_pain_point_clusters","positive_signals","backlog_overview","release_risk"]
            if all(k in summary_data for k in required_keys):
                # versions match
                if isinstance(versions, dict):
                    if summary_data.get("version_pre") == versions.get("pre") and summary_data.get("version_post") == versions.get("post"):
                        checks["summary_versions_match"] = True
                # scoring weights match exactly
                sw = summary_data.get("scoring_weights")
                if isinstance(weights, dict) and isinstance(sw, dict):
                    # Extract keys frequency, severity, recency as floats
                    try:
                        sf = float(sw.get("frequency"))
                        ss = float(sw.get("severity"))
                        sr = float(sw.get("recency"))
                        wf = float(weights.get("frequency"))
                        ws = float(weights.get("severity"))
                        wr = float(weights.get("recency"))
                        if ("frequency" in sw and "severity" in sw and "recency" in sw
                            and abs(sf - wf) < 1e-9 and abs(ss - ws) < 1e-9 and abs(sr - wr) < 1e-9):
                            checks["summary_weights_match"] = True
                    except Exception:
                        pass
                # top_pain_point_clusters validation
                tpc = summary_data.get("top_pain_point_clusters")
                tpc_ok = False
                if isinstance(tpc, list) and len(tpc) >= 1:
                    items_ok = True
                    for it in tpc:
                        if not isinstance(it, dict):
                            items_ok = False
                            break
                        cid = it.get("cluster_id")
                        theme = it.get("theme")
                        pa = it.get("product_area")
                        freq = it.get("frequency")
                        sev = it.get("severity_score")
                        rec = it.get("recency_score")
                        plats = it.get("platforms")
                        if not (isinstance(cid, str) and re.fullmatch(r"C\d{3}", cid or "")):
                            items_ok = False
                            break
                        if not (isinstance(theme, str) and theme.strip()):
                            items_ok = False
                            break
                        if not (isinstance(pa, str) and pa.strip()):
                            items_ok = False
                            break
                        if not (isinstance(freq, int) and freq >= 1):
                            items_ok = False
                            break
                        try:
                            sevf = float(sev)
                            recf = float(rec)
                        except Exception:
                            items_ok = False
                            break
                        if not (0.0 <= sevf <= 1.0 and 0.0 <= recf <= 1.0):
                            items_ok = False
                            break
                        if not (isinstance(plats, list) and all(isinstance(x, str) for x in plats)):
                            items_ok = False
                            break
                    if items_ok:
                        tpc_ok = True
                if tpc_ok:
                    checks["summary_top_clusters_valid"] = True

                # positive_signals
                ps = summary_data.get("positive_signals")
                ps_ok = False
                if isinstance(ps, list):
                    ps_ok = True
                    for it in ps:
                        if not isinstance(it, dict):
                            ps_ok = False
                            break
                        if "signal" not in it or "supporting_examples" not in it:
                            ps_ok = False
                            break
                        if not isinstance(it["signal"], str):
                            ps_ok = False
                            break
                        if not isinstance(it["supporting_examples"], list) or not all(isinstance(x, str) for x in it["supporting_examples"]):
                            ps_ok = False
                            break
                if ps_ok:
                    checks["summary_positive_signals_valid"] = True

                # backlog_overview
                bo = summary_data.get("backlog_overview")
                bo_ok = False
                if isinstance(bo, dict):
                    needed = ["bugs","features","P0","P1","P2","P3"]
                    if all(k in bo for k in needed):
                        try:
                            vals = [int(bo[k]) for k in needed]
                            if all(v >= 0 for v in vals):
                                bo_ok = True
                        except Exception:
                            bo_ok = False
                if bo_ok:
                    checks["summary_backlog_overview_valid"] = True

                # release_risk
                rr = summary_data.get("release_risk")
                rr_ok = False
                if isinstance(rr, list):
                    ok = True
                    for it in rr:
                        if not isinstance(it, dict):
                            ok = False
                            break
                        risk = it.get("risk")
                        cid = it.get("cluster_id")
                        evid = it.get("evidence_review_ids")
                        if not (isinstance(risk, str) and risk.strip()):
                            ok = False
                            break
                        if not (isinstance(cid, str) and re.fullmatch(r"C\d{3}", cid or "")):
                            ok = False
                            break
                        if not (isinstance(evid, list) and all(isinstance(x, str) for x in evid)):
                            ok = False
                            break
                        # cross-check with clusters.csv if available
                        if checks["clusters_csv_valid"]:
                            if cid not in clusters_ids_set:
                                ok = False
                                break
                    if ok:
                        rr_ok = True
                if rr_ok:
                    checks["summary_release_risk_refs_valid"] = True

                # If we've reached here, summary.json structure is okay
                checks["summary_json_valid"] = True

    # Validate backlog.tsv
    backlog_fieldnames, backlog_rows = (None, None)
    if os.path.isfile(backlog_path):
        backlog_fieldnames, backlog_rows = load_tsv(backlog_path)
        header_expected = ["cluster_id","type","priority","title","rationale"]
        if backlog_fieldnames == header_expected and backlog_rows is not None and len(backlog_rows) > 0:
            # Validate each row
            valid_rows = True
            for row in backlog_rows:
                cid = row.get("cluster_id","")
                typ = row.get("type","")
                prio = row.get("priority","")
                title = row.get("title","")
                rationale = row.get("rationale","")
                if not re.fullmatch(r"C\d{3}", cid or ""):
                    valid_rows = False
                    break
                if typ not in {"bug","feature"}:
                    valid_rows = False
                    break
                if prio not in {"P0","P1","P2","P3"}:
                    valid_rows = False
                    break
                if not title or not rationale:
                    valid_rows = False
                    break
            if valid_rows:
                checks["backlog_tsv_valid"] = True
                # references must exist in clusters.csv
                if checks["clusters_csv_valid"]:
                    all_refs_ok = all(row["cluster_id"] in clusters_ids_set for row in backlog_rows)
                    checks["backlog_refs_valid"] = all_refs_ok
                # at least 5 rows
                if len(backlog_rows) >= 5:
                    checks["backlog_min_rows"] = True

    # Validate trend_comparison.json
    if os.path.isfile(trend_path):
        trend_data = read_json(trend_path)
        if isinstance(trend_data, dict):
            req_keys = ["version_pre","version_post","emerged_clusters","regressed_clusters","improved_clusters","stable_clusters"]
            if all(k in trend_data for k in req_keys):
                arrays_ok = all(isinstance(trend_data[k], list) for k in ["emerged_clusters","regressed_clusters","improved_clusters","stable_clusters"])
                versions_ok = False
                if isinstance(versions, dict):
                    if trend_data.get("version_pre") == versions.get("pre") and trend_data.get("version_post") == versions.get("post"):
                        versions_ok = True
                        checks["trend_versions_match"] = True
                # refs valid
                refs_ok = False
                exclusive_ok = False
                has_reg_or_emerged = False
                if arrays_ok and checks["clusters_csv_valid"]:
                    all_ids = []
                    all_good = True
                    for k in ["emerged_clusters","regressed_clusters","improved_clusters","stable_clusters"]:
                        ids = trend_data.get(k, [])
                        # valid format
                        for cid in ids:
                            if not isinstance(cid, str) or not re.fullmatch(r"C\d{3}", cid or ""):
                                all_good = False
                                break
                            if cid not in clusters_ids_set:
                                all_good = False
                                break
                        if not all_good:
                            break
                        all_ids.extend(ids)
                    if all_good:
                        refs_ok = True
                        # exclusive categories (no duplicates across arrays)
                        exclusive_ok = len(all_ids) == len(set(all_ids))
                        # at least one in emerged or regressed
                        has_reg_or_emerged = (len(trend_data.get("emerged_clusters", [])) > 0) or (len(trend_data.get("regressed_clusters", [])) > 0)
                if arrays_ok and versions_ok:
                    checks["trend_json_valid"] = True
                if refs_ok:
                    checks["trend_refs_valid"] = True
                if exclusive_ok:
                    checks["trend_exclusive_categories"] = True
                if has_reg_or_emerged:
                    checks["trend_has_reg_or_emerged"] = True

    # Validate report.md
    if os.path.isfile(report_path):
        report_text = read_text(report_path) or ""
        # Required H2 headings verbatim
        required_headings = [
            "## Executive Summary",
            "## Top Pain Points",
            "## Positive Signals",
            "## Backlog Recommendations",
            "## Release Risk and Regressions",
            "## Methodology & Assumptions",
        ]
        has_sections = all(h in report_text for h in required_headings)
        if has_sections:
            checks["report_has_sections"] = True
        # Mention both version labels exactly from versions.txt
        if isinstance(versions, dict):
            if versions["pre"] in report_text and versions["post"] in report_text:
                checks["report_mentions_versions"] = True
        # Word count between 500 and 900 inclusive
        wc = word_count(report_text)
        if 500 <= wc <= 900:
            checks["report_length_ok"] = True
        # In Release Risk section: include at least one literal cluster_id and at least one review_id-like token
        rr_section = extract_section(report_text, "## Release Risk and Regressions")
        if rr_section is not None:
            has_cluster_id = re.search(r"\bC\d{3}\b", rr_section) is not None
            # review_id-like: alphanumeric length>=6 containing at least one letter and one digit
            has_review_like = re.search(r"\b(?=[A-Za-z0-9]{6,}\b)(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9]+\b", rr_section) is not None
            if has_cluster_id and has_review_like:
                checks["report_risk_section_refs"] = True

    # Compute reward
    # If required files missing, reward must be 0.0
    if not checks["all_files_present"]:
        reward = 0.0
    else:
        # Average of all boolean checks
        bool_values = list(checks.values())
        # Convert to ints (True=1, False=0)
        total = len(bool_values)
        score = sum(1 for v in bool_values if v)
        reward = score / total if total > 0 else 0.0

    # Output single JSON line
    out = {"reward": float(reward)}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()