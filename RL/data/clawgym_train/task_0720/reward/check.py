import csv
import json
import os
import sys
from collections import Counter, OrderedDict

def read_domains(domains_csv_path):
    domains = []
    try:
        with open(domains_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or "domain" not in reader.fieldnames:
                return []
            for row in reader:
                d = (row.get("domain") or "").strip()
                if d:
                    domains.append(d)
    except Exception:
        return []
    return domains

def read_ips(ips_csv_path):
    ips = []
    try:
        with open(ips_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or "ip" not in reader.fieldnames:
                return []
            for row in reader:
                ip = (row.get("ip") or "").strip()
                if ip:
                    ips.append(ip)
    except Exception:
        return []
    return ips

def parse_bool_str(s):
    if isinstance(s, bool):
        return s
    if s is None:
        return None
    v = str(s).strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    return None

def to_list(x):
    if isinstance(x, list):
        return x
    return []

def to_dict(x):
    if isinstance(x, dict):
        return x
    return {}

def extract_txt_strings(txt_items):
    vals = []
    for item in txt_items:
        if isinstance(item, str):
            vals.append(item)
        elif isinstance(item, dict):
            # Prefer 'value' if present, else stringify
            if "value" in item and isinstance(item["value"], str):
                vals.append(item["value"])
            else:
                try:
                    vals.append(json.dumps(item, sort_keys=True))
                except Exception:
                    vals.append(str(item))
        else:
            vals.append(str(item))
    return vals

def compute_top_geo_country(resolved_ip_geos):
    # Expects list of dicts with country_code
    codes = []
    for it in resolved_ip_geos:
        if not isinstance(it, dict):
            continue
        code = it.get("country_code")
        if isinstance(code, str):
            code = code.strip()
            if code:
                codes.append(code.upper())
    if not codes:
        return ""
    counts = Counter(codes)
    max_count = max(counts.values())
    # Return any of the top codes deterministically by alphabetical to keep deterministic choice
    top_codes = sorted([c for c, n in counts.items() if n == max_count])
    return top_codes[0] if top_codes else ""

def validate_findings_sections(text, headings):
    # Returns dict of heading -> bool (paragraph present after heading)
    lines = text.splitlines()
    # normalize heading check: consider markdown headings with any number of leading '#'
    indices = {}
    for idx, raw in enumerate(lines):
        s = raw.strip()
        if not s:
            continue
        normalized = s.lstrip("#").strip()
        if normalized in headings and normalized not in indices:
            indices[normalized] = idx
    results = {}
    for h in headings:
        ok = False
        if h in indices:
            start = indices[h] + 1
            # look for at least one non-empty non-heading line before next heading
            for j in range(start, len(lines)):
                s = lines[j].strip()
                if not s:
                    # blank line: skip, as paragraphs may start after blanks
                    continue
                # if we hit another heading line (one of required headings) stop
                if s.lstrip("#").strip() in headings:
                    break
                # found a non-empty line: consider as paragraph
                ok = True
                break
        results[h] = ok
    return results

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = OrderedDict()
    # Initialize all checks to False
    checks["report_exists"] = False
    checks["report_json_valid"] = False
    checks["report_has_entries_for_all_domains"] = False
    checks["report_schema_valid_min"] = False

    checks["summary_exists"] = False
    checks["summary_header_valid"] = False
    checks["summary_rows_cover_all_domains_exactly"] = False
    checks["summary_cross_checks_match_report"] = False

    checks["findings_exists"] = False
    checks["findings_word_count_ok"] = False
    checks["findings_sections_ok"] = False

    # Read reference inputs
    domains_csv = os.path.join(input_dir, "domains.csv")
    ips_csv = os.path.join(input_dir, "ips.csv")
    schema_json = os.path.join(input_dir, "schema.json")  # not strictly validated without jsonschema

    input_domains = read_domains(domains_csv)
    input_ips = read_ips(ips_csv)

    # Validate outputs under output/
    report_path = os.path.join(output_dir, "report.json")
    summary_path = os.path.join(output_dir, "summary.csv")
    findings_path = os.path.join(output_dir, "findings.md")

    report_data = None
    domain_to_entry = {}

    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_data = json.load(f)
            checks["report_json_valid"] = True
        except Exception:
            report_data = None

    # Build domain_to_entry map and validate presence per domain
    if checks["report_json_valid"]:
        entries = []
        if isinstance(report_data, list):
            entries = [e for e in report_data if isinstance(e, dict)]
        elif isinstance(report_data, dict):
            # Could be a map of domain -> entry object
            for k, v in report_data.items():
                if isinstance(v, dict):
                    entry = v
                    dom = entry.get("domain")
                    if not isinstance(dom, str) or not dom.strip():
                        dom = str(k)
                    entries.append(entry)
        # Build map by domain field
        for e in entries:
            dom = e.get("domain")
            if isinstance(dom, str):
                dom = dom.strip()
                if dom and dom not in domain_to_entry:
                    domain_to_entry[dom] = e

        if input_domains:
            if all(d in domain_to_entry and isinstance(domain_to_entry[d].get("domain"), str) and domain_to_entry[d].get("domain") == d for d in input_domains):
                checks["report_has_entries_for_all_domains"] = True

        # Minimal schema validation for required domains only
        schema_ok = True
        if checks["report_has_entries_for_all_domains"]:
            for d in input_domains:
                entry = domain_to_entry.get(d, {})
                # domain string
                if not isinstance(entry.get("domain"), str):
                    schema_ok = False
                    break
                # dns object with arrays and SOA object
                dns = to_dict(entry.get("dns"))
                for arr_key in ["A", "AAAA", "MX", "TXT", "NS", "CNAME"]:
                    if not isinstance(dns.get(arr_key), list):
                        schema_ok = False
                        break
                if not schema_ok:
                    break
                # SOA present as object (can be empty dict)
                if "SOA" not in dns or not isinstance(dns.get("SOA"), dict):
                    schema_ok = False
                    break
                # dmarc_txt array
                if not isinstance(entry.get("dmarc_txt"), list):
                    schema_ok = False
                    break
                # whois object with registrar string
                whois = entry.get("whois")
                if not isinstance(whois, dict) or not isinstance(whois.get("registrar"), str):
                    schema_ok = False
                    break
                # resolved_ip_geos array of objects with ip and country_code
                rig = entry.get("resolved_ip_geos")
                if not isinstance(rig, list):
                    schema_ok = False
                    break
                for it in rig:
                    if not isinstance(it, dict):
                        schema_ok = False
                        break
                    if not isinstance(it.get("ip"), str):
                        schema_ok = False
                        break
                    # country_code may be empty but must be a string if present
                    cc = it.get("country_code", "")
                    if not isinstance(cc, (str, type(None))):
                        schema_ok = False
                        break
                if not schema_ok:
                    break
                # reverse_ptr array of objects with ip and ptr
                rptr = entry.get("reverse_ptr")
                if not isinstance(rptr, list):
                    schema_ok = False
                    break
                for it in rptr:
                    if not isinstance(it, dict):
                        schema_ok = False
                        break
                    if not isinstance(it.get("ip"), str):
                        schema_ok = False
                        break
                    if not isinstance(it.get("ptr"), str):
                        schema_ok = False
                        break
                if not schema_ok:
                    break
        else:
            schema_ok = False
        checks["report_schema_valid_min"] = schema_ok

    # Validate summary.csv
    summary_rows = []
    header_expected = ["domain","total_dns_records","has_mx","spf_present","dkim_present","dmarc_present","rdap_registrar","top_geo_country"]
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames == header_expected:
                    checks["summary_header_valid"] = True
                # Collect rows
                for row in reader:
                    summary_rows.append(row)
        except Exception:
            pass

    # Rows cover all domains exactly once
    if checks["summary_header_valid"]:
        row_domains = [ (row.get("domain") or "").strip() for row in summary_rows if (row.get("domain") or "").strip() ]
        counts = Counter(row_domains)
        cover_ok = True
        # exact set equality and count 1
        if set(row_domains) != set(input_domains):
            cover_ok = False
        else:
            for d in input_domains:
                if counts.get(d,0) != 1:
                    cover_ok = False
                    break
        checks["summary_rows_cover_all_domains_exactly"] = cover_ok

    # Cross-check summary values against report.json
    if checks["summary_rows_cover_all_domains_exactly"] and checks["report_schema_valid_min"]:
        cross_ok = True
        # Map summary row per domain
        sum_map = { (row.get("domain") or "").strip(): row for row in summary_rows }
        for d in input_domains:
            entry = domain_to_entry.get(d)
            row = sum_map.get(d)
            if entry is None or row is None:
                cross_ok = False
                break

            dns = to_dict(entry.get("dns"))
            a_len = len(to_list(dns.get("A")))
            aaaa_len = len(to_list(dns.get("AAAA")))
            mx_len = len(to_list(dns.get("MX")))
            txt_list = to_list(dns.get("TXT"))
            ns_len = len(to_list(dns.get("NS")))
            cname_len = len(to_list(dns.get("CNAME")))
            soa_present = ("SOA" in dns and isinstance(dns.get("SOA"), dict))
            total_expected = a_len + aaaa_len + mx_len + len(txt_list) + ns_len + cname_len + (1 if soa_present else 0)

            # has_mx
            has_mx_expected = mx_len > 0

            # TXT and DMARC
            dmarc_txt = to_list(entry.get("dmarc_txt"))
            txt_strings = extract_txt_strings(txt_list) + extract_txt_strings(dmarc_txt)
            lower_txt = [s.lower() for s in txt_strings if isinstance(s, str)]
            spf_expected = any("v=spf1" in s for s in lower_txt)
            dkim_expected = any("v=dkim1" in s for s in lower_txt)
            dmarc_expected = any("v=dmarc1" in s for s in lower_txt) or len(dmarc_txt) > 0

            # registrar
            registrar_expected = (entry.get("whois") or {}).get("registrar", "")
            if not isinstance(registrar_expected, str):
                registrar_expected = ""

            # top geo country
            rig = to_list(entry.get("resolved_ip_geos"))
            top_geo_expected = compute_top_geo_country(rig)

            # Parse row values
            # total_dns_records
            try:
                total_from_csv = int((row.get("total_dns_records") or "").strip())
            except Exception:
                cross_ok = False
                break
            if total_from_csv != total_expected:
                cross_ok = False
                break

            # booleans
            has_mx_csv = parse_bool_str(row.get("has_mx"))
            spf_csv = parse_bool_str(row.get("spf_present"))
            dkim_csv = parse_bool_str(row.get("dkim_present"))
            dmarc_csv = parse_bool_str(row.get("dmarc_present"))
            if has_mx_csv is None or spf_csv is None or dkim_csv is None or dmarc_csv is None:
                cross_ok = False
                break
            if has_mx_csv != has_mx_expected or spf_csv != spf_expected or dkim_csv != dkim_expected or dmarc_csv != dmarc_expected:
                cross_ok = False
                break

            # registrar exact match (strip whitespace)
            registrar_csv = (row.get("rdap_registrar") or "").strip()
            if registrar_csv != (registrar_expected or "").strip():
                cross_ok = False
                break

            # top_geo_country: must match most frequent; allow case-insensitive; if none expected, require empty string
            top_geo_csv = (row.get("top_geo_country") or "").strip()
            if top_geo_expected == "":
                if top_geo_csv != "":
                    cross_ok = False
                    break
            else:
                if top_geo_csv.upper() != top_geo_expected.upper():
                    cross_ok = False
                    break

        checks["summary_cross_checks_match_report"] = cross_ok

    # Validate findings.md
    if os.path.isfile(findings_path):
        checks["findings_exists"] = True
        try:
            with open(findings_path, "r", encoding="utf-8") as f:
                findings_text = f.read()
        except Exception:
            findings_text = ""
        # word count
        words = [w for w in findings_text.split() if w.strip()]
        if len(words) >= 250:
            checks["findings_word_count_ok"] = True
        # sections
        headings = ["Methodology", "Key Findings", "Recommendations"]
        sec_result = validate_findings_sections(findings_text, headings)
        checks["findings_sections_ok"] = all(sec_result.get(h, False) for h in headings)

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if passed > 0 else 0.0

    # Ensure no-op baseline: if no outputs at all or required artifacts missing, keep reward 0.0
    # If none of the three main outputs exist, force 0.0
    if not (checks["report_exists"] or checks["summary_exists"] or checks["findings_exists"]):
        reward = 0.0

    result = OrderedDict()
    result["reward"] = round(reward, 6)
    # Append checks
    for k, v in checks.items():
        result[k] = v

    print(json.dumps(result))

if __name__ == "__main__":
    main()