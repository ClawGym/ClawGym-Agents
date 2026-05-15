import json
import os
import sys
import csv
import re

def read_nonempty_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f.read().splitlines()]
        return [ln for ln in lines if ln.strip() != ""]
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_domains_csv(path):
    domains = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # Expect a 'domain' header
            if reader.fieldnames is None or "domain" not in [h.lower() for h in reader.fieldnames]:
                return None
            # Map exact header name for 'domain'
            domain_key = None
            for h in reader.fieldnames:
                if h.lower() == "domain":
                    domain_key = h
                    break
            for row in reader:
                d = (row.get(domain_key) or "").strip()
                if d:
                    domains.append(d)
    except Exception:
        return None
    # Deduplicate while preserving order
    seen = set()
    uniq = []
    for d in domains:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq

def is_relative_output_path(p):
    if not isinstance(p, str):
        return False
    if p.startswith("/"):
        return False
    # normalize leading ./ if present
    norm = p.lstrip("./")
    return norm.startswith("output/")

def count_changelog_entries(md_text):
    # Find a line containing "changelog" (case-insensitive)
    lines = md_text.splitlines()
    idx = None
    for i, line in enumerate(lines):
        if re.search(r"\bchangelog\b", line, flags=re.IGNORECASE):
            idx = i
            break
    if idx is None:
        return 0
    # Collect up to next 30 lines or until next heading
    count = 0
    for j in range(idx + 1, min(len(lines), idx + 31)):
        l = lines[j].strip()
        if re.match(r"^#{1,6}\s", l):  # next markdown heading
            break
        # stop if strong section delimiter
        if re.match(r"^(-{3,}|={3,})$", l):
            break
        if l != "":
            count += 1
    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks
    checks = {
        # Wordlist checks
        "wordlist_exists": False,
        "wordlist_includes_base": False,
        "wordlist_added_count_at_least_10": False,
        "wordlist_line_count_ok": False,

        # Raw per-domain results
        "raw_files_exist_for_all_domains": False,
        "raw_files_valid_json_schema": False,
        "raw_files_no_dup_within": False,

        # Report checks
        "report_exists": False,
        "report_parsed": False,
        "report_domains_match": False,
        "report_scan_strategy_matches_settings": False,
        "report_discovered_counts_match": False,
        "report_artifacts_paths_valid": False,
        "report_wordlist_size_matches": False,
        "report_wordlist_added_exactly_10": False,
        "report_wordlist_added_valid": False,

        # Findings checks
        "findings_exists": False,
        "findings_mentions_auth_scope_domains": False,
        "findings_mentions_methods": False,
        "findings_has_next_steps": False,
        "findings_has_changelog_with_10_lines": False,
    }

    # Load reference inputs
    domains_csv = os.path.join(input_dir, "domains.csv")
    settings_json_path = os.path.join(input_dir, "settings.json")
    base_wordlist_path = os.path.join(input_dir, "custom_wordlist.txt")

    domains_list = load_domains_csv(domains_csv) or []
    domain_set_lower = set([d.strip().lower() for d in domains_list])

    settings = load_json(settings_json_path) or {}
    include_crtsh = settings.get("include_crtsh", None)
    settings_threads = settings.get("threads", None)
    settings_timeout = settings.get("timeout", None)

    base_wordlist = read_nonempty_lines(base_wordlist_path)
    base_set = set([x.strip().lower() for x in base_wordlist]) if base_wordlist is not None else set()
    base_n = len(base_set)

    # 1) Check output/wordlist.txt
    out_wordlist_path = os.path.join(output_dir, "wordlist.txt")
    if os.path.isfile(out_wordlist_path):
        checks["wordlist_exists"] = True
        out_lines = read_nonempty_lines(out_wordlist_path) or []
        out_set = set([x.strip().lower() for x in out_lines if x.strip() != ""])
        # Includes base
        if base_wordlist is not None and base_set.issubset(out_set):
            checks["wordlist_includes_base"] = True
        # Added count
        added_set = out_set - base_set
        if len(added_set) >= 10:
            checks["wordlist_added_count_at_least_10"] = True
        # Line count ok
        if len(out_set) >= base_n + 10:
            checks["wordlist_line_count_ok"] = True
    else:
        out_lines = []
        out_set = set()
        added_set = set()

    # 2) output/raw/<domain>.json checks
    raw_all_exist = True
    raw_schema_all_valid = True
    raw_nodup_all_valid = True
    raw_counts = {}
    for d in domains_list:
        raw_path = os.path.join(output_dir, "raw", f"{d}.json")
        if not os.path.isfile(raw_path):
            raw_all_exist = False
            raw_schema_all_valid = False
            raw_nodup_all_valid = False
            continue
        try:
            data = load_json(raw_path)
            if not isinstance(data, list):
                raw_schema_all_valid = False
                continue
            # Validate items if non-empty
            seen_subs = set()
            nodup_ok = True
            schema_ok = True
            for item in data:
                if not isinstance(item, dict):
                    schema_ok = False
                    break
                if "subdomain" not in item or "ips" not in item or "source" not in item:
                    schema_ok = False
                    break
                if not isinstance(item["subdomain"], str):
                    schema_ok = False
                    break
                if not isinstance(item["ips"], list):
                    schema_ok = False
                    break
                if not isinstance(item["source"], str) or item["source"] not in ("dns", "crt.sh"):
                    schema_ok = False
                    break
                sub_lc = item["subdomain"].lower()
                if sub_lc in seen_subs:
                    nodup_ok = False
                seen_subs.add(sub_lc)
            if not schema_ok:
                raw_schema_all_valid = False
            if not nodup_ok:
                raw_nodup_all_valid = False
            raw_counts[d] = len(data)
        except Exception:
            raw_schema_all_valid = False
    if domains_list:
        checks["raw_files_exist_for_all_domains"] = raw_all_exist
        # Only set these True if all corresponding files that exist are valid and all required files exist
        if raw_all_exist and raw_schema_all_valid:
            checks["raw_files_valid_json_schema"] = True
        if raw_all_exist and raw_nodup_all_valid:
            checks["raw_files_no_dup_within"] = True

    # 3) output/report.json checks
    report_path = os.path.join(output_dir, "report.json")
    report = None
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        report = load_json(report_path)
        if isinstance(report, dict):
            checks["report_parsed"] = True

    if checks["report_parsed"]:
        # scan_target_domains
        std = report.get("scan_target_domains")
        if isinstance(std, list):
            std_set = set([str(x).strip().lower() for x in std if isinstance(x, str)])
            if std_set == domain_set_lower and len(std_set) == len(domain_set_lower):
                checks["report_domains_match"] = True

        # scan_strategy
        strategy = report.get("scan_strategy", {})
        strategy_ok = True
        if not isinstance(strategy, dict):
            strategy_ok = False
        else:
            dns_bruteforce = strategy.get("dns_bruteforce", None)
            crtsh_lookup = strategy.get("crtsh_lookup", None)
            threads = strategy.get("threads", None)
            timeout = strategy.get("timeout", None)
            if dns_bruteforce is not True:
                strategy_ok = False
            # Must match settings.json
            if include_crtsh is None or crtsh_lookup is None or crtsh_lookup != include_crtsh:
                strategy_ok = False
            if not isinstance(threads, int) or settings_threads != threads:
                strategy_ok = False
            if not isinstance(timeout, int) or settings_timeout != timeout:
                strategy_ok = False
        checks["report_scan_strategy_matches_settings"] = strategy_ok

        # discovered_summary
        ds = report.get("discovered_summary", {})
        ds_ok = True
        if not isinstance(ds, dict):
            ds_ok = False
        else:
            for d in domains_list:
                if d not in ds or not isinstance(ds[d], int):
                    ds_ok = False
                    break
                # Compare to raw count if available
                expected_count = raw_counts.get(d, None)
                if expected_count is None:
                    # If raw missing, then fail
                    ds_ok = False
                    break
                if ds[d] != expected_count:
                    ds_ok = False
                    break
        checks["report_discovered_counts_match"] = ds_ok

        # artifacts.raw_results_paths
        artifacts_ok = True
        artifacts = report.get("artifacts", {})
        if not isinstance(artifacts, dict):
            artifacts_ok = False
        else:
            rrp = artifacts.get("raw_results_paths", {})
            if not isinstance(rrp, dict):
                artifacts_ok = False
            else:
                for d in domains_list:
                    p = rrp.get(d)
                    if not is_relative_output_path(p):
                        artifacts_ok = False
                        break
                    # verify path points to the raw file that exists
                    # Accepts both 'output/raw/<d>.json' or './output/raw/<d>.json'
                    full_p = os.path.join(workspace_root, p.lstrip("./"))
                    if not os.path.isfile(full_p):
                        artifacts_ok = False
                        break
                    # Also check it matches the corresponding path for this domain
                    expected = os.path.join(output_dir, "raw", f"{d}.json")
                    # Resolve symlinks/abspath
                    try:
                        if os.path.realpath(full_p) != os.path.realpath(expected):
                            artifacts_ok = False
                            break
                    except Exception:
                        artifacts_ok = False
                        break
        checks["report_artifacts_paths_valid"] = artifacts_ok

        # wordlist_size
        wl_size = report.get("wordlist_size", None)
        wl_size_ok = False
        out_wordlist_lines = read_nonempty_lines(out_wordlist_path) or []
        if isinstance(wl_size, int):
            if wl_size == len([ln for ln in out_wordlist_lines if ln.strip() != ""]):
                wl_size_ok = True
        checks["report_wordlist_size_matches"] = wl_size_ok

        # wordlist_added
        wa = report.get("wordlist_added", None)
        wa_exact10 = isinstance(wa, list) and len(wa) == 10
        checks["report_wordlist_added_exactly_10"] = wa_exact10

        wa_valid = False
        if isinstance(wa, list):
            # Validate each added item is not in base and is present in output wordlist
            all_ok = True
            for item in wa:
                if not isinstance(item, str) or item.strip() == "":
                    all_ok = False
                    break
                item_lc = item.strip().lower()
                if item_lc in base_set:
                    all_ok = False
                    break
                if item_lc not in (set([x.strip().lower() for x in out_wordlist_lines])):
                    all_ok = False
                    break
            # Cross-check size at minimum
            if len((set([x.strip().lower() for x in out_wordlist_lines])) - base_set) < 10:
                all_ok = False
            wa_valid = all_ok
        checks["report_wordlist_added_valid"] = wa_valid

        # Additional cross-check: wordlist size >= base + len(wa)
        # Not a separate flag, but ensure consistency by not altering an existing flag if this fails.

    # 4) output/findings.md checks
    findings_path = os.path.join(output_dir, "findings.md")
    findings_text = None
    if os.path.isfile(findings_path):
        checks["findings_exists"] = True
        try:
            with open(findings_path, "r", encoding="utf-8") as f:
                findings_text = f.read()
        except Exception:
            findings_text = None

    if findings_text is not None:
        text_lc = findings_text.lower()
        # mentions "authorized" and "scope" and each domain
        auth_scope_ok = ("authorized" in text_lc and "scope" in text_lc)
        if auth_scope_ok:
            for d in domains_list:
                if d.lower() not in text_lc:
                    auth_scope_ok = False
                    break
        checks["findings_mentions_auth_scope_domains"] = auth_scope_ok

        # mentions DNS and either "certificate transparency" or "crt.sh"
        methods_ok = (re.search(r"\bdns\b", text_lc) is not None) and (("certificate transparency" in text_lc) or ("crt.sh" in text_lc))
        checks["findings_mentions_methods"] = methods_ok

        # next steps
        checks["findings_has_next_steps"] = ("next steps" in text_lc)

        # changelog with at least 10 non-empty lines following
        cl_count = count_changelog_entries(findings_text)
        checks["findings_has_changelog_with_10_lines"] = (cl_count >= 10)

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks
        # Explicitly ensure 0.0 if no output artifacts found at all (no-op baseline)
        output_exists = os.path.isdir(output_dir) and any(True for _ in os.scandir(output_dir)) if os.path.isdir(output_dir) else False
        if not output_exists:
            reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()