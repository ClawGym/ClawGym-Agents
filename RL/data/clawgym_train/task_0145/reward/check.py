import json
import os
import sys
import csv
import re
from datetime import datetime

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_jsonl(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    return None
                items.append(obj)
        return items
    except Exception:
        return None

def read_csv_dicts(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            return reader.fieldnames, rows
    except Exception:
        return None, None

def parse_simple_yaml(yaml_text):
    # Minimal YAML parser for a subset:
    # - mappings: key: value or key:
    # - nested via indentation (spaces)
    # - lists: key: then indented "- item" lines
    # - string scalars only
    # Returns dict or None on failure
    try:
        lines = yaml_text.splitlines()
        root = {}
        # Stack of (indent, path_list)
        stack = [(-1, [])]

        def get_container(root_obj, path):
            cur = root_obj
            for p in path:
                if p not in cur or not isinstance(cur[p], dict):
                    cur[p] = {}
                cur = cur[p]
            return cur

        def get_parent_and_key(path):
            if not path:
                return None, None
            parent_path = path[:-1]
            key = path[-1]
            parent = get_container(root, parent_path)
            return parent, key

        for raw in lines:
            if not raw.strip():
                continue
            # Ignore comment-only lines
            stripped = raw.lstrip(' ')
            if stripped.startswith('#'):
                continue

            indent = len(raw) - len(stripped)

            # Adjust stack based on indent
            while stack and indent <= stack[-1][0]:
                stack.pop()
            # parent path is on stack[-1]
            parent_path = stack[-1][1] if stack else []

            # Determine line type
            if re.match(r"^\-\s", stripped):
                # list item for the current mapping key at parent_path
                # The current list key is the last element of parent_path
                parent, key = get_parent_and_key(parent_path)
                if parent is None or key is None:
                    # List at root not supported in this minimal parser
                    return None
                # Ensure value at parent[key] is a list
                if key not in parent or not isinstance(parent[key], list):
                    parent[key] = []
                val = stripped[1:].strip()
                # Strip quotes if present
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                parent[key].append(val)
                # push list level for nested mappings under list items is not supported (not needed here)
                continue

            m = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", stripped)
            if m:
                key = m.group(1)
                val = m.group(2)
                container = get_container(root, parent_path)
                if val == "":
                    # start nested mapping context
                    # initialize as dict unless later list items appear (we'll convert when "- " encountered under this key)
                    if key not in container or not isinstance(container.get(key), (dict, list)):
                        container[key] = {}
                    # push this key context
                    stack.append((indent, parent_path + [key]))
                else:
                    # scalar value
                    sval = val.strip()
                    if (sval.startswith('"') and sval.endswith('"')) or (sval.startswith("'") and sval.endswith("'")):
                        sval = sval[1:-1]
                    container[key] = sval
                continue

            # If we reach here, unsupported syntax for this minimal parser
            return None

        return root
    except Exception:
        return None

def load_yaml_or_json(path):
    text = read_text(path)
    if text is None:
        return None
    # Try JSON first
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # Try minimal YAML
    obj = parse_simple_yaml(text)
    return obj

def normalize_space(s):
    return re.sub(r"\s+", " ", s or "").strip()

def word_count(s):
    return len(re.findall(r"\S+", s or ""))

def is_iso_date(s):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", s or ""):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False

def compute_expected_qualified(leads_rows):
    expected_ids = []
    allowed_locations = {"us", "usa", "united states", "canada"}
    allowed_roles = {"head of sales", "vp sales", "revops", "revops lead", "revops manager", "sales manager"}
    allowed_funding = {"seed", "series a", "series b"}

    for row in leads_rows:
        try:
            industry = (row.get("industry") or "").strip().lower()
            if not ("b2b" in industry and "saas" in industry):
                continue

            location = (row.get("location") or "").strip().lower()
            if location not in allowed_locations:
                continue

            role = (row.get("role") or "").strip().lower()
            if role not in allowed_roles:
                continue

            pain = (row.get("pain_signals") or "").strip()
            if len(pain) == 0:
                continue
            if "hiring freeze" in pain.lower():
                continue

            company_size_raw = (row.get("company_size") or "").strip()
            m = re.search(r"\d+", company_size_raw)
            size_val = int(m.group(0)) if m else 0

            funding = (row.get("funding") or "").strip().lower()
            has_budget = size_val >= 10 or funding in allowed_funding
            if not has_budget:
                continue

            email = (row.get("email") or "").strip()
            linkedin = (row.get("linkedin_url") or "").strip()
            reachable = (len(email) > 0) or (len(linkedin) > 0)
            if not reachable:
                continue

            lead_id = str(row.get("lead_id") or "").strip()
            if lead_id == "":
                continue

            expected_ids.append(lead_id)
        except Exception:
            continue
    return set(expected_ids)

def extract_nonstopword_tokens(text):
    stopwords = {
        'the','a','an','and','or','to','of','in','on','for','with','at','by','from','this','that',
        'is','are','was','were','be','been','it','as','about','into','over','after','before','up',
        'down','out','off','again','further','then','once','here','there','why','how','all','any',
        'both','each','few','more','most','other','some','such','no','nor','not','only','own',
        'same','so','than','too','very','s','t','can','will','just','don','should','now','you',
        'your','yours','their','they','them','our','we','i','me','my','mine','us','usa','united',
        'states','ca','canada','b2b','saas'
    }
    tokens = re.findall(r"[A-Za-z0-9\-']+", text or "")
    filtered = [t.lower() for t in tokens if t and t.lower() not in stopwords]
    return filtered

def contains_any_token(text, tokens):
    tl = text.lower()
    for tok in tokens:
        # match whole word
        if re.search(r"\b" + re.escape(tok) + r"\b", tl):
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        # ICP
        "icp_exists": False,
        "icp_valid_yaml": False,
        "icp_required_keys": False,
        "icp_industry_b2bsaas": False,
        "icp_company_size_range": False,
        "icp_roles_contains_required": False,
        "icp_disqualifiers_required": False,
        # Qualified leads CSV
        "qualified_exists": False,
        "qualified_headers_ok": False,
        "qualified_exact_match": False,
        # Outreach emails
        "emails_exists": False,
        "emails_count_match": False,
        "emails_length_ok_all": False,
        "emails_personalized_all": False,
        "emails_ask_all": False,
        # LinkedIn messages
        "linkedin_exists": False,
        "linkedin_count_match": False,
        "linkedin_conn_len_all": False,
        "linkedin_conn_specific_all": False,
        "linkedin_followup_len_all": False,
        "linkedin_followup_ask_all": False,
        # Sequence
        "sequence_exists": False,
        "sequence_count_match": False,
        "sequence_channels_ok_all": False,
        "sequence_day_offsets_ok_all": False,
        "sequence_email_final_exit_all": False,
        # Pipeline
        "pipeline_exists": False,
        "pipeline_headers_exact": False,
        "pipeline_rows_count_match": False,
        "pipeline_stage_contacted_all": False,
        "pipeline_dates_iso_all": False,
    }

    # Load input leads to compute expected
    leads_path = os.path.join(input_dir, "leads.csv")
    fieldnames, leads_rows = read_csv_dicts(leads_path)
    expected_ids = set()
    if fieldnames is not None and leads_rows is not None:
        expected_ids = compute_expected_qualified(leads_rows)

    # 1) Check ICP YAML
    icp_path = os.path.join(output_dir, "icp.yaml")
    if os.path.isfile(icp_path):
        checks["icp_exists"] = True
        icp_obj = load_yaml_or_json(icp_path)
        if isinstance(icp_obj, dict):
            checks["icp_valid_yaml"] = True
            # Required structure
            try:
                cp = icp_obj.get("company_profile", {})
                industry = cp.get("industry")
                company_size = cp.get("company_size")
                roles = cp.get("roles")
                locations = cp.get("locations")
                pain_signals = icp_obj.get("pain_signals")
                disqualifiers = icp_obj.get("disqualifiers")
                if (
                    isinstance(cp, dict) and isinstance(industry, str) and isinstance(company_size, str)
                    and isinstance(roles, list) and isinstance(locations, list)
                    and isinstance(pain_signals, list) and isinstance(disqualifiers, list)
                ):
                    checks["icp_required_keys"] = True

                    # Value checks
                    ind_norm = normalize_space(industry).lower()
                    if ind_norm == "b2b saas":
                        checks["icp_industry_b2bsaas"] = True

                    cs_norm = company_size.replace(" ", "")
                    if "10-200" in cs_norm:
                        checks["icp_company_size_range"] = True

                    req_roles = {"head of sales", "vp sales", "revops", "sales manager"}
                    roles_norm = {normalize_space(str(r)).lower() for r in roles}
                    if req_roles.issubset(roles_norm):
                        checks["icp_roles_contains_required"] = True

                    disq_norm = {normalize_space(str(d)).lower() for d in disqualifiers}
                    if "b2c" in disq_norm and "hiring freeze" in disq_norm:
                        checks["icp_disqualifiers_required"] = True
                # else remains False
            except Exception:
                pass

    # 2) qualified_leads.csv
    qualified_path = os.path.join(output_dir, "qualified_leads.csv")
    q_fieldnames, q_rows = read_csv_dicts(qualified_path)
    if q_fieldnames is not None and q_rows is not None:
        checks["qualified_exists"] = True
        required_cols = {"lead_id", "name", "company", "role"}
        if set(col.strip() for col in q_fieldnames).issuperset(required_cols):
            checks["qualified_headers_ok"] = True
        q_ids = [str(r.get("lead_id") or "").strip() for r in q_rows if str(r.get("lead_id") or "").strip() != ""]
        if set(q_ids) == expected_ids and len(q_ids) == len(expected_ids):
            checks["qualified_exact_match"] = True

    # 3) outreach_emails.jsonl
    emails_path = os.path.join(output_dir, "outreach_emails.jsonl")
    emails = parse_jsonl(emails_path)
    if emails is not None:
        checks["emails_exists"] = True
        # Must be exactly one per qualified lead
        email_ids = [str(e.get("lead_id") or "").strip() for e in emails if isinstance(e, dict)]
        if set(email_ids) == expected_ids and len(email_ids) == len(expected_ids):
            checks["emails_count_match"] = True

        # Prepare lead lookup by id
        leads_by_id = {}
        if leads_rows is not None:
            for r in leads_rows:
                lid = str(r.get("lead_id") or "").strip()
                leads_by_id[lid] = r

        length_ok = True
        personalized_ok = True
        ask_ok = True
        # Build regex for low-commitment ask
        ask_patterns = [
            r"(quick|worth an?)\s+10\s?-?\s?min(?:ute)?s?\s+(?:chat|call)",
            r"send over a quick example",
            r"worth a quick\s+(?:chat|call)"
        ]
        ask_re = re.compile("(" + ")|(".join(ask_patterns) + ")", re.IGNORECASE)

        for e in emails:
            if not isinstance(e, dict):
                length_ok = False
                personalized_ok = False
                ask_ok = False
                break
            body = e.get("body", "")
            if word_count(body) > 100:
                length_ok = False
            # Personalization check
            lid = str(e.get("lead_id") or "").strip()
            lead = leads_by_id.get(lid, {})
            company = (lead.get("company") or "").strip()
            recent_event = lead.get("recent_event") or ""
            pain_signals = lead.get("pain_signals") or ""
            tokens = extract_nonstopword_tokens(recent_event + " " + pain_signals)
            body_l = body.lower()
            personalized = False
            if company and company.lower() in body_l:
                personalized = True
            else:
                if contains_any_token(body, tokens):
                    personalized = True
            if not personalized:
                personalized_ok = False
            # Ask check
            if not ask_re.search(body or ""):
                ask_ok = False

        checks["emails_length_ok_all"] = length_ok
        checks["emails_personalized_all"] = personalized_ok
        checks["emails_ask_all"] = ask_ok

    # 4) linkedin_messages.jsonl
    linkedin_path = os.path.join(output_dir, "linkedin_messages.jsonl")
    linkedin_msgs = parse_jsonl(linkedin_path)
    if linkedin_msgs is not None:
        checks["linkedin_exists"] = True
        li_ids = [str(e.get("lead_id") or "").strip() for e in linkedin_msgs if isinstance(e, dict)]
        if set(li_ids) == expected_ids and len(li_ids) == len(expected_ids):
            checks["linkedin_count_match"] = True

        conn_len_ok = True
        conn_specific_ok = True
        follow_len_ok = True
        follow_ask_ok = True
        ask_patterns = [
            r"(quick|worth an?)\s+10\s?-?\s?min(?:ute)?s?\s+(?:chat|call)",
            r"send over a quick example",
            r"worth a quick\s+(?:chat|call)"
        ]
        ask_re = re.compile("(" + ")|(".join(ask_patterns) + ")", re.IGNORECASE)

        for e in linkedin_msgs:
            if not isinstance(e, dict):
                conn_len_ok = False
                conn_specific_ok = False
                follow_len_ok = False
                follow_ask_ok = False
                break
            cr = e.get("connection_request", "")
            fm = e.get("followup_message", "")
            if len(cr) > 240:
                conn_len_ok = False
            if not re.search(r"(post|job|review|podcast|comment|migration)", cr, re.IGNORECASE):
                conn_specific_ok = False
            if len(fm) > 450:
                follow_len_ok = False
            if not ask_re.search(fm or ""):
                follow_ask_ok = False

        checks["linkedin_conn_len_all"] = conn_len_ok
        checks["linkedin_conn_specific_all"] = conn_specific_ok
        checks["linkedin_followup_len_all"] = follow_len_ok
        checks["linkedin_followup_ask_all"] = follow_ask_ok

    # 5) sequence.jsonl
    seq_path = os.path.join(output_dir, "sequence.jsonl")
    sequences = parse_jsonl(seq_path)
    if sequences is not None:
        checks["sequence_exists"] = True
        seq_ids = [str(e.get("lead_id") or "").strip() for e in sequences if isinstance(e, dict)]
        if set(seq_ids) == expected_ids and len(seq_ids) == len(expected_ids):
            checks["sequence_count_match"] = True

        channels_ok = True
        days_ok = True
        final_exit_ok = True
        required_channels = {"linkedin_connect", "linkedin_message", "email", "linkedin_comment", "email_final"}

        for e in sequences:
            if not isinstance(e, dict):
                channels_ok = False
                days_ok = False
                final_exit_ok = False
                break
            touches = e.get("touches")
            if not isinstance(touches, list) or len(touches) != 5:
                channels_ok = False
                days_ok = False
                final_exit_ok = False
                continue
            chans = [t.get("channel") for t in touches if isinstance(t, dict)]
            if set(chans) != required_channels or len(set(chans)) != 5:
                channels_ok = False
            # day offsets
            try:
                offsets = [int(t.get("day_offset")) for t in touches]
                if offsets != sorted(offsets) or len(set(offsets)) != 5 or max(offsets) > 21:
                    days_ok = False
            except Exception:
                days_ok = False
            # email_final message
            ef = None
            for t in touches:
                if t.get("channel") == "email_final":
                    ef = t
                    break
            if not ef or not isinstance(ef.get("message"), str) or not re.search(r"(totally understand|no pressure)", ef.get("message"), re.IGNORECASE):
                final_exit_ok = False

        checks["sequence_channels_ok_all"] = channels_ok
        checks["sequence_day_offsets_ok_all"] = days_ok
        checks["sequence_email_final_exit_all"] = final_exit_ok

    # 6) pipeline.csv
    pipeline_path = os.path.join(output_dir, "pipeline.csv")
    p_fields, p_rows = read_csv_dicts(pipeline_path)
    if p_fields is not None and p_rows is not None:
        checks["pipeline_exists"] = True
        expected_headers = ["Lead Name", "Company", "Source", "Date First Contacted", "Last Touchpoint", "Stage", "Notes", "Next Action", "Next Action Date"]
        if p_fields == expected_headers:
            checks["pipeline_headers_exact"] = True
        # rows count equals number of qualified leads
        if len(p_rows) == len(expected_ids):
            checks["pipeline_rows_count_match"] = True
        # stage contacted
        stage_ok = True
        dates_ok = True
        for r in p_rows:
            if r.get("Stage") != "Contacted":
                stage_ok = False
            if not (is_iso_date(r.get("Date First Contacted")) and is_iso_date(r.get("Next Action Date"))):
                dates_ok = False
        checks["pipeline_stage_contacted_all"] = stage_ok
        checks["pipeline_dates_iso_all"] = dates_ok

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Ensure numeric within bounds
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()