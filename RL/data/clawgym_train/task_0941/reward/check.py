import json
import os
import sys
import csv
import re

def to_number(val):
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, bool) or val is None:
        return None
    s = str(val).strip()
    if s == "":
        return None
    # Remove currency symbols and commas
    s_clean = re.sub(r'[,\s]', '', s)
    s_clean = re.sub(r'^\$','', s_clean)
    # Percent handling is not needed for arithmetic here
    try:
        if re.match(r'^-?\d+$', s_clean):
            return float(int(s_clean))
        if re.match(r'^-?\d+\.\d*$', s_clean):
            return float(s_clean)
    except Exception:
        return None
    return None

def parse_bool(val):
    if isinstance(val, bool):
        return val
    if val is None:
        return None
    s = str(val).strip().lower()
    if s in ('true','yes','y','1'):
        return True
    if s in ('false','no','n','0'):
        return False
    return None

def parse_scalar(s):
    # Remove surrounding quotes if any
    if isinstance(s, (int, float, bool)) or s is None:
        return s
    v = s.strip()
    if v.startswith('"') and v.endswith('"'):
        v = v[1:-1]
    elif v.startswith("'") and v.endswith("'"):
        v = v[1:-1]
    # booleans
    pb = parse_bool(v)
    if pb is not None:
        return pb
    # null
    if v.lower() in ('null','~','none'):
        return None
    # number
    n = to_number(v)
    if n is not None:
        # return int where appropriate
        if abs(n - int(n)) < 1e-9:
            return int(n)
        return n
    return v

def parse_simple_yaml(text):
    # A very small YAML subset parser supporting dicts, lists, scalars.
    # Indentation with spaces only. No tabs supported.
    lines = text.splitlines()
    # Remove comments and empty lines but keep indentation
    processed = []
    for line in lines:
        raw = line.rstrip('\n\r')
        # strip comments not inside quotes (simple heuristic)
        l = raw
        # find unquoted hash
        quoted = False
        new_line = []
        i = 0
        while i < len(l):
            ch = l[i]
            if ch in ['"',"'"]:
                q = ch
                new_line.append(ch)
                i += 1
                while i < len(l):
                    new_line.append(l[i])
                    if l[i] == q and l[i-1] != '\\':
                        i += 1
                        break
                    i += 1
                continue
            if ch == '#':
                # treat as comment start
                break
            new_line.append(ch)
            i += 1
        s = "".join(new_line).rstrip()
        if s.strip() == "":
            continue
        processed.append(s)

    def indent_level(s):
        return len(s) - len(s.lstrip(' '))

    root = {}
    stack = [( -1, root, None )]  # (indent, container, current_key_for_dict_waiting_value)
    for s in processed:
        ind = indent_level(s)
        content = s[ind:]
        # Adjust stack to current indent
        while stack and ind <= stack[-1][0]:
            stack.pop()
        parent_container = stack[-1][1]

        if content.startswith('- '):
            # list item
            item_str = content[2:].strip()
            # ensure parent is a list; if parent is dict waiting for list, create list
            if isinstance(parent_container, dict):
                # This happens if previous line was "key:" and created {}
                # In that case, there should be a key placeholder in stack[-1][2]
                # But our representation keeps (indent, container, None). If dict was just created,
                # parent already exists. Find the most recent key added with None value? Not tracked.
                # Better: If dict is empty or last key has None, create a list at a placeholder key.
                # We'll try: if stack[-1] has a key placeholder in tuple third element; if None, we cannot resolve.
                # To make robust, we introduce behavior: if parent is dict and last_pushed_key exists in the top frame.
                pass

            # If parent is not list, create or convert a pending key to list
            if isinstance(parent_container, dict):
                # Create a new list under a special pending key marker saved earlier
                # We need to know which key we are populating. To handle this, we will assume
                # the previous line was a key with no value and created an empty dict under that key.
                # We cannot deduce which key; to support common YAML like "items:" followed by list,
                # we adjust earlier when creating dict on "key:" to actually create a list placeholder.
                # To support that, we will inspect if parent_container has a single key mapping to a special marker.
                # Workaround: look for any key in parent_container that is a special object "__PENDING_LIST__"
                pending_key = None
                for k,v in list(parent_container.items())[::-1]:
                    if v == "__PENDING_LIST__":
                        pending_key = k
                        break
                if pending_key is not None:
                    parent_container[pending_key] = []
                    parent_container = parent_container[pending_key]
                    # update the stack to reflect real container
                    stack[-1] = (stack[-1][0], stack[-1][1], None)
                else:
                    # No pending list, create or convert: if there is any key with value [] we can use it.
                    # Otherwise, cannot attach list - create anonymous list not allowed. Fallback: create key "items".
                    parent_container["items"] = parent_container.get("items", [])
                    parent_container = parent_container["items"]
            if not isinstance(parent_container, list):
                # If still not a list, make it one
                tmp_list = []
                # If parent was list, ok; otherwise, replace?
                parent_container = tmp_list

            # Determine if list item is scalar or starts a dict like "key: value"
            if ': ' in item_str or item_str.endswith(':'):
                # dict item
                item_dict = {}
                if item_str.endswith(':'):
                    key = item_str[:-1].strip()
                    item_dict[key] = {}
                    parent_container.append(item_dict)
                    # push new dict for further keys
                    stack.append((ind, item_dict, None))
                else:
                    k, v = item_str.split(':', 1)
                    key = k.strip()
                    val = parse_scalar(v.strip())
                    item_dict[key] = val
                    parent_container.append(item_dict)
                    # push this item_dict for deeper nested lines
                    stack.append((ind, item_dict, None))
            else:
                val = parse_scalar(item_str)
                parent_container.append(val)
                # push nothing for scalars
        else:
            # key: value or key:
            if ':' in content:
                k, v = content.split(':', 1)
                key = k.strip()
                v = v.strip()
                if v == "":
                    # New mapping or a list pending
                    # We need to guess if next indented lines are list or dict; mark pending list
                    # For now, create an empty dict; if later we see a list item, we will convert via "__PENDING_LIST__"
                    # Place a special marker for pending list
                    parent_container[key] = "__PENDING_LIST__"
                    # push a temporary dict container; we will replace when content appears
                    # But to support immediate dict children on next lines, replace marker with {} when first non-list child appears
                    temp_container = {}
                    # Store both parent and a small shadow of where to put children
                    # Save a placeholder frame with container as parent_container and remember key for pending type
                    stack.append((ind, { "_parent": parent_container, "_key": key, "_type": "pending" }, None))
                else:
                    val = parse_scalar(v)
                    # If parent frame is pending, materialize it
                    if isinstance(parent_container, dict):
                        # Check if it's a pending frame on the stack
                        if stack and isinstance(stack[-1][1], dict) and stack[-1][1].get("_type") == "pending":
                            # If we are still within pending, convert marker to dict since we saw a kv child
                            pending_info = stack[-1][1]
                            p = pending_info["_parent"]
                            pkey = pending_info["_key"]
                            if p.get(pkey) == "__PENDING_LIST__":
                                p[pkey] = {}
                            # Replace top of stack to actual dict container
                            stack[-1] = (stack[-1][0], p[pkey], None)
                            parent_container = stack[-1][1]
                    parent_container[key] = val
            else:
                # Invalid line; ignore
                pass

            # After handling, if the just-added key had empty value (":") we pushed a pending marker; that's handled above.

            # If we added a dict under pending marker earlier and now encounter deeper indent, the loop will push frames accordingly.
            # For proper nested dict support when key: (empty) then sub-keys follow, we need to ensure that when we encounter first child key (non-list),
            # we materialize pending marker to dict as above.

    # Cleanup pending markers by converting any "__PENDING_LIST__" to empty list
    def cleanup(obj):
        if isinstance(obj, dict):
            keys = list(obj.keys())
            for k in keys:
                v = obj[k]
                if v == "__PENDING_LIST__":
                    obj[k] = []
                else:
                    obj[k] = cleanup(v)
        elif isinstance(obj, list):
            return [cleanup(v) for v in obj]
        return obj

    cleaned = cleanup(root)
    return cleaned

def read_yaml_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
        data = parse_simple_yaml(text)
        return data
    except Exception:
        return None

def read_json_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def read_csv_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = [ {k.strip(): v.strip() for k,v in row.items()} for row in reader ]
        return rows
    except Exception:
        return None

def read_jsonl_file(path):
    rows = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    rows.append(json.loads(s))
                except Exception:
                    return None
        return rows
    except Exception:
        return None

def deep_search_key(obj, key_substring):
    # returns first numeric or string/int/float/bool value for a key that contains the substring
    if isinstance(obj, dict):
        for k, v in obj.items():
            if key_substring in str(k).lower():
                if isinstance(v, (int, float, str, bool)):
                    return v
                # else if dict or list, try to find numeric within
                inner = deep_search_key(v, key_substring)
                if inner is not None:
                    return inner
            inner = deep_search_key(v, key_substring)
            if inner is not None:
                return inner
    elif isinstance(obj, list):
        for it in obj:
            inner = deep_search_key(it, key_substring)
            if inner is not None:
                return inner
    return None

def find_constraints_values(constraints_yaml):
    # expected_size
    expected_size_val = deep_search_key(constraints_yaml, 'expected_size')
    expected_size = None
    if expected_size_val is not None:
        n = to_number(expected_size_val)
        if n is not None:
            expected_size = int(round(n))
    # budget cap
    budget_cap_val = deep_search_key(constraints_yaml, 'budget_cap')
    budget_cap = None
    if budget_cap_val is not None:
        n = to_number(budget_cap_val)
        if n is not None:
            budget_cap = float(n)
    # fallback: search "budget" then "cap"
    if budget_cap is None:
        budget_val = deep_search_key(constraints_yaml, 'budget')
        if budget_val is not None:
            n = to_number(budget_val)
            if n is not None:
                budget_cap = float(n)
    return expected_size, budget_cap

def find_registration_goal(marketing_targets_json):
    # look for registration_goal
    val = deep_search_key(marketing_targets_json, 'registration_goal')
    if val is not None:
        n = to_number(val)
        if n is not None:
            return int(round(n))
    # fallback: "registrations_goal" or "registrationtarget"
    for sub in ['registrations_goal','registrationtarget','target_registrations','target_registration']:
        val = deep_search_key(marketing_targets_json, sub)
        if val is not None:
            n = to_number(val)
            if n is not None:
                return int(round(n))
    return None

def sum_ticket_revenue_from_marketing(marketing_targets_json):
    # Traverse dict and sum any object that has price and qty fields
    def walk(obj):
        total = 0.0
        if isinstance(obj, dict):
            # If has price and qty
            if 'price' in obj and 'qty' in obj:
                p = to_number(obj.get('price'))
                q = to_number(obj.get('qty'))
                if p is not None and q is not None:
                    total += p * q
            for v in obj.values():
                total += walk(v)
        elif isinstance(obj, list):
            for it in obj:
                total += walk(it)
        return total
    return round(walk(marketing_targets_json), 2)

def sum_sponsorship_revenue_from_csv(sponsors_csv_rows):
    total = 0.0
    for row in sponsors_csv_rows or []:
        # find price and qty columns
        keys = {k.lower(): k for k in row.keys()}
        price = None
        qty = None
        # try typical names
        for pk in ['price','tier_price','sponsor_price','amount']:
            if pk in keys:
                price = to_number(row[keys[pk]])
                if price is not None:
                    break
        for qk in ['qty','quantity','expected_qty','expected_quantity','count']:
            if qk in keys:
                qty = to_number(row[keys[qk]])
                if qty is not None:
                    break
        if price is not None and qty is not None:
            total += price * qty
    return round(total, 2)

def find_venue_row_by_name(venues_rows, name):
    if not venues_rows or not name:
        return None
    name_norm = str(name).strip().lower()
    for row in venues_rows:
        row_name = row.get('name') or row.get('venue') or row.get('venue_name') or ''
        if str(row_name).strip().lower() == name_norm:
            return row
    # try substring match
    for row in venues_rows:
        row_name = row.get('name') or row.get('venue') or row.get('venue_name') or ''
        if name_norm in str(row_name).strip().lower():
            return row
    return None

def get_venue_fields(row):
    if not row:
        return None
    keys = {k.lower(): k for k in row.keys()}
    def getnum(cols):
        for c in cols:
            if c in keys:
                return to_number(row[keys[c]])
        return None
    def getstr(cols):
        for c in cols:
            if c in keys:
                return row[keys[c]]
        return None
    def getbool(cols):
        for c in cols:
            if c in keys:
                return parse_bool(row[keys[c]])
        return None
    capacity = getnum(['capacity','max_capacity'])
    wifi = getnum(['wifi_mbps','wifi','wifi_capacity_mbps'])
    ada = getbool(['ada','ada_compliant','accessible'])
    rental = getnum(['rental','rental_fee','venue_rental','rental_usd'])
    catering_pp = getnum(['catering_per_person','catering_pp','catering','catering_rate'])
    name = getstr(['name','venue','venue_name'])
    return {
        'name': name,
        'capacity': int(capacity) if capacity is not None else None,
        'wifi_mbps': float(wifi) if wifi is not None else None,
        'ada': ada if ada is not None else None,
        'rental': float(rental) if rental is not None else None,
        'catering_per_person': float(catering_pp) if catering_pp is not None else None
    }

def get_nested(d, path_list):
    cur = d
    for key in path_list:
        if not isinstance(cur, dict):
            return None
        if key not in cur:
            # try alternative: if keys are strings maybe different case
            found = None
            for k in cur.keys():
                if str(k).lower() == str(key).lower():
                    found = k
                    break
            if found is None:
                return None
            key = found
        cur = cur.get(key)
    return cur

def sum_numeric_leaves(d, ignore_keys=None):
    if ignore_keys is None:
        ignore_keys = set()
    total = 0.0
    if isinstance(d, dict):
        for k, v in d.items():
            if str(k) in ignore_keys:
                continue
            if isinstance(v, (int, float)):
                total += float(v)
            elif isinstance(v, dict):
                total += sum_numeric_leaves(v, ignore_keys=ignore_keys)
            elif isinstance(v, list):
                for it in v:
                    total += sum_numeric_leaves(it, ignore_keys=ignore_keys)
    elif isinstance(d, list):
        for it in d:
            total += sum_numeric_leaves(it, ignore_keys=ignore_keys)
    return total

def list_len(obj):
    if isinstance(obj, list):
        return len(obj)
    return 0

def str_contains(s, *subs):
    if not isinstance(s, str):
        return False
    s_low = s.lower()
    return all(sub.lower() in s_low for sub in subs)

def approx_equal(a, b, tol=0.01):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def normalize_role(r):
    if not isinstance(r, str):
        return ""
    return " ".join(r.strip().lower().split())

def collect_team_roles(run_sheet):
    roles = set()
    team = get_nested(run_sheet, ['run_sheet','team'])
    if not team:
        team = get_nested(run_sheet, ['team'])
    if isinstance(team, list):
        for member in team:
            if isinstance(member, dict) and 'role' in member:
                roles.add(normalize_role(member['role']))
            elif isinstance(member, str):
                roles.add(normalize_role(member))
    return roles

def collect_timeline_actions(run_sheet):
    actions = []
    tl = get_nested(run_sheet, ['run_sheet','timeline'])
    if not tl:
        tl = get_nested(run_sheet, ['timeline'])
    if isinstance(tl, list):
        for item in tl:
            if isinstance(item, dict):
                act = item.get('action') or item.get('activity') or ''
                actions.append(str(act))
            elif isinstance(item, str):
                actions.append(item)
    return actions

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # Read inputs
    constraints = read_yaml_file(os.path.join(input_dir, "constraints.yaml"))
    venues = read_csv_file(os.path.join(input_dir, "venues.csv"))
    marketing_targets = read_json_file(os.path.join(input_dir, "marketing_targets.json"))
    sponsors = read_csv_file(os.path.join(input_dir, "sponsors.csv"))

    expected_size, budget_cap = (None, None)
    if constraints:
        expected_size, budget_cap = find_constraints_values(constraints)

    # Prepare checks
    checks = {}

    # 1) event_brief.yaml
    eb_path = os.path.join(output_dir, "event_brief.yaml")
    eb_exists = os.path.isfile(eb_path)
    checks['event_brief_exists'] = eb_exists
    eb_data = read_yaml_file(eb_path) if eb_exists else None
    checks['event_brief_parsed'] = eb_data is not None

    # event.format == "hybrid"
    eb_format_val = None
    if eb_data:
        eb_format_val = get_nested(eb_data, ['event','format'])
        if eb_format_val is None:
            eb_format_val = get_nested(eb_data, ['format'])
    checks['event_brief_format_hybrid'] = (str(eb_format_val).strip().lower() == 'hybrid') if eb_data else False

    # audience.expected_size equals constraints expected_size
    eb_expected_size = None
    if eb_data:
        eb_expected_size = get_nested(eb_data, ['event','audience','expected_size'])
        if eb_expected_size is None:
            eb_expected_size = deep_search_key(eb_data, 'expected_size')
        if isinstance(eb_expected_size, str):
            en = to_number(eb_expected_size)
            eb_expected_size = int(en) if en is not None else None
    checks['event_brief_expected_size_matches'] = (expected_size is not None and eb_expected_size == expected_size) if eb_data else False

    # budget.total equals budget cap
    eb_budget_total = None
    if eb_data:
        eb_budget_total = get_nested(eb_data, ['event','budget','total'])
        if eb_budget_total is None:
            eb_budget_total = get_nested(eb_data, ['budget','total'])
        if eb_budget_total is not None:
            eb_budget_total = float(eb_budget_total)
    checks['event_brief_budget_total_equals_cap'] = (budget_cap is not None and eb_budget_total is not None and abs(eb_budget_total - budget_cap) < 0.01) if eb_data else False

    # success_metrics contains metric tied to registration goal
    reg_goal = find_registration_goal(marketing_targets) if marketing_targets else None
    eb_success_metrics = []
    if eb_data:
        sm = get_nested(eb_data, ['event','success_metrics'])
        if sm is None:
            sm = get_nested(eb_data, ['success_metrics'])
        if isinstance(sm, list):
            eb_success_metrics = sm
    tied = False
    if eb_success_metrics and reg_goal is not None:
        for m in eb_success_metrics:
            if isinstance(m, dict):
                metric_name = m.get('metric') or ''
                target = m.get('target')
                target_num = None
                if target is not None:
                    tn = to_number(target)
                    if tn is not None:
                        target_num = int(round(tn))
                if 'registration' in str(metric_name).lower() and target_num == reg_goal:
                    tied = True
                    break
    checks['event_brief_success_metric_tied_to_registration_goal'] = tied

    # kill_criteria check for registration, speaker, sponsor mentions and at least 3 items
    eb_kill = []
    if eb_data:
        kc = get_nested(eb_data, ['event','kill_criteria'])
        if kc is None:
            kc = get_nested(eb_data, ['kill_criteria'])
        if isinstance(kc, list):
            eb_kill = [str(x) for x in kc]
    kc_ok = False
    if len(eb_kill) >= 3:
        has_reg = any('registration' in x.lower() for x in eb_kill)
        has_speaker = any('speaker' in x.lower() for x in eb_kill)
        has_sponsor = any('sponsor' in x.lower() for x in eb_kill)
        kc_ok = has_reg and has_speaker and has_sponsor
    checks['event_brief_kill_criteria_required_mentions'] = kc_ok

    # 2) venue_selection.yaml
    vs_path = os.path.join(output_dir, "venue_selection.yaml")
    vs_exists = os.path.isfile(vs_path)
    checks['venue_selection_exists'] = vs_exists
    vs_data = read_yaml_file(vs_path) if vs_exists else None
    checks['venue_selection_parsed'] = vs_data is not None

    vs_chosen_name = None
    if vs_data:
        vs_chosen_name = get_nested(vs_data, ['chosen_venue']) or get_nested(vs_data, ['venue','chosen_venue'])
        if isinstance(vs_chosen_name, dict):
            vs_chosen_name = vs_chosen_name.get('name') or None
    venue_row = find_venue_row_by_name(venues, vs_chosen_name) if (venues and vs_chosen_name) else None
    checks['venue_selection_chosen_exists_in_input'] = venue_row is not None

    venue_fields = get_venue_fields(venue_row) if venue_row else None
    # computed values
    wifi_required = (expected_size * 2) if (expected_size is not None) else None
    capacity_ok_calc = None
    wifi_ok_calc = None
    ada_ok_calc = None
    if venue_fields and expected_size is not None:
        capacity_ok_calc = (venue_fields['capacity'] is not None) and (venue_fields['capacity'] >= int(round(expected_size * 1.1)))
        wifi_ok_calc = (venue_fields['wifi_mbps'] is not None) and (wifi_required is not None) and (venue_fields['wifi_mbps'] >= wifi_required)
        ada_ok_calc = (venue_fields['ada'] is True)

    # check declared booleans and required mbps
    declared_capacity_ok = get_nested(vs_data, ['capacity_ok']) if vs_data else None
    declared_wifi_required = get_nested(vs_data, ['wifi_required_mbps']) if vs_data else None
    declared_wifi_ok = get_nested(vs_data, ['wifi_ok']) if vs_data else None
    declared_ada_ok = get_nested(vs_data, ['ada_ok']) if vs_data else None

    checks['venue_selection_wifi_required_correct'] = (wifi_required is not None and declared_wifi_required == wifi_required) if vs_data else False
    checks['venue_selection_capacity_ok_correct'] = (capacity_ok_calc is not None and parse_bool(declared_capacity_ok) == capacity_ok_calc) if vs_data else False
    checks['venue_selection_wifi_ok_correct'] = (wifi_ok_calc is not None and parse_bool(declared_wifi_ok) == wifi_ok_calc) if vs_data else False
    checks['venue_selection_ada_ok_correct'] = (ada_ok_calc is not None and parse_bool(declared_ada_ok) == ada_ok_calc) if vs_data else False

    # checklist summary aligning to must-haves: look for checklist or checklist_summary strings mentioning capacity, wifi, access
    checklist = None
    if vs_data:
        checklist = get_nested(vs_data, ['checklist']) or get_nested(vs_data, ['checklist_summary'])
    cl_ok = False
    if isinstance(checklist, list):
        items = [str(x).lower() for x in checklist]
        has_capacity = any('capacity' in x for x in items)
        has_wifi = any('wifi' in x for x in items)
        has_access = any('access' in x for x in items or [])
        cl_ok = has_capacity and has_wifi and has_access and len(items) >= 3
    checks['venue_selection_checklist_must_haves'] = cl_ok

    # justification length
    just = get_nested(vs_data, ['justification']) if vs_data else None
    checks['venue_selection_justification_len_ok'] = (isinstance(just, list) and len(just) >= 3 and len(just) <= 5)

    # red flags length and referencing non-chosen venue
    red_flags = get_nested(vs_data, ['red_flags']) if vs_data else None
    red_len_ok = isinstance(red_flags, list) and len(red_flags) >= 3
    ref_non_chosen = False
    if isinstance(red_flags, list) and venues:
        names = [ (row.get('name') or row.get('venue') or row.get('venue_name') or '').strip() for row in venues ]
        for rf in red_flags:
            s = str(rf)
            for nm in names:
                if nm and vs_chosen_name and nm.lower() != str(vs_chosen_name).strip().lower():
                    if nm.lower() in s.lower():
                        ref_non_chosen = True
                        break
            if ref_non_chosen:
                break
    checks['venue_selection_red_flags_len_ok'] = red_len_ok
    checks['venue_selection_red_flags_reference_others'] = ref_non_chosen

    # 3) budget.yaml
    b_path = os.path.join(output_dir, "budget.yaml")
    b_exists = os.path.isfile(b_path)
    checks['budget_exists'] = b_exists
    b_data = read_yaml_file(b_path) if b_exists else None
    checks['budget_parsed'] = b_data is not None

    budget_root = get_nested(b_data, ['budget']) if b_data else None
    checks['budget_structure_ok'] = (isinstance(budget_root, dict)
                                     and isinstance(budget_root.get('revenue'), dict)
                                     and isinstance(budget_root.get('expenses'), dict)
                                     and isinstance(budget_root.get('summary'), dict)) if b_data else False

    # revenue from marketing_targets.json
    expected_ticket_rev = sum_ticket_revenue_from_marketing(marketing_targets) if marketing_targets else None
    expected_sponsor_rev = sum_sponsorship_revenue_from_csv(sponsors) if sponsors else None

    # sum ticket_sales totals in budget.yaml
    ticket_sales_tot = None
    sponsor_tot = None
    revenue_total_summary = None
    if budget_root:
        ticket_sales = get_nested(budget_root, ['revenue','ticket_sales'])
        if isinstance(ticket_sales, dict):
            # sum any nested 'total' numeric
            subtotal = 0.0
            for v in ticket_sales.values():
                if isinstance(v, dict):
                    t = to_number(v.get('total'))
                    if t is not None:
                        subtotal += t
            ticket_sales_tot = round(subtotal, 2)
        sponsorship = get_nested(budget_root, ['revenue','sponsorship'])
        if isinstance(sponsorship, dict):
            subtotal = 0.0
            for v in sponsorship.values():
                if isinstance(v, dict):
                    t = to_number(v.get('total'))
                    if t is not None:
                        subtotal += t
            sponsor_tot = round(subtotal, 2)
        revenue_total_summary = to_number(get_nested(budget_root, ['summary','total_revenue']))

    checks['budget_ticket_sales_total_correct'] = (ticket_sales_tot is not None and expected_ticket_rev is not None and approx_equal(ticket_sales_tot, expected_ticket_rev)) if b_data else False
    checks['budget_sponsorship_total_correct'] = (sponsor_tot is not None and expected_sponsor_rev is not None and approx_equal(sponsor_tot, expected_sponsor_rev)) if b_data else False

    # expenses: venue.rental equals chosen venue rental; catering equals catering_per_person * expected_size
    exp_venue_rental = to_number(get_nested(budget_root, ['expenses','venue','rental'])) if budget_root else None
    exp_venue_catering = to_number(get_nested(budget_root, ['expenses','venue','catering'])) if budget_root else None
    venue_rental_expected = venue_fields['rental'] if venue_fields else None
    catering_expected = (venue_fields['catering_per_person'] * expected_size) if (venue_fields and expected_size is not None and venue_fields.get('catering_per_person') is not None) else None

    checks['budget_expenses_venue_rental_correct'] = (exp_venue_rental is not None and venue_rental_expected is not None and approx_equal(exp_venue_rental, venue_rental_expected)) if b_data else False
    checks['budget_expenses_catering_correct'] = (exp_venue_catering is not None and catering_expected is not None and approx_equal(exp_venue_catering, catering_expected)) if b_data else False

    # compute revenue sum from budget.yaml structure
    other_rev_sum = 0.0
    other_rev = get_nested(budget_root, ['revenue','other']) if budget_root else None
    if isinstance(other_rev, dict):
        for v in other_rev.values():
            num = to_number(v)
            if num is not None:
                other_rev_sum += float(num)
    b_revenue_sum = None
    if ticket_sales_tot is not None or sponsor_tot is not None:
        b_revenue_sum = (ticket_sales_tot or 0.0) + (sponsor_tot or 0.0) + other_rev_sum
    checks['budget_summary_total_revenue_correct'] = (b_revenue_sum is not None and revenue_total_summary is not None and approx_equal(b_revenue_sum, revenue_total_summary)) if b_data else False

    # expenses sum and summary
    expenses_total_summary = to_number(get_nested(budget_root, ['summary','total_expenses'])) if budget_root else None
    expenses_total_field = to_number(get_nested(budget_root, ['expenses','total_expenses'])) if budget_root else None
    # compute sum of all expenses numeric leaves excluding "total_expenses"
    exp_sum_calc = None
    if budget_root:
        exp_obj = get_nested(budget_root, ['expenses'])
        if isinstance(exp_obj, dict):
            exp_sum_calc = sum_numeric_leaves(exp_obj, ignore_keys={'total_expenses'})
    checks['budget_summary_total_expenses_correct'] = (exp_sum_calc is not None and expenses_total_summary is not None and approx_equal(exp_sum_calc, expenses_total_summary)) if b_data else False

    # net_result and ROI
    net_result_summary = to_number(get_nested(budget_root, ['summary','net_result'])) if budget_root else None
    roi_percentage_summary = to_number(get_nested(budget_root, ['summary','roi_percentage'])) if budget_root else None
    # cost per attendee
    cpa_summary = to_number(get_nested(budget_root, ['summary','cost_per_attendee'])) if budget_root else None

    net_calc = None
    roi_calc = None
    cpa_calc = None
    if revenue_total_summary is not None and expenses_total_summary is not None:
        net_calc = revenue_total_summary - expenses_total_summary
        if expenses_total_summary != 0:
            roi_calc = (net_calc / expenses_total_summary) * 100.0
    if expected_size is not None and expenses_total_summary is not None and expected_size != 0:
        cpa_calc = expenses_total_summary / expected_size

    checks['budget_summary_net_result_correct'] = (net_result_summary is not None and net_calc is not None and approx_equal(net_result_summary, net_calc)) if b_data else False
    checks['budget_summary_roi_percentage_correct'] = (roi_percentage_summary is not None and roi_calc is not None and abs(float(roi_percentage_summary) - float(roi_calc)) <= 0.1) if b_data else False
    checks['budget_cost_per_attendee_correct'] = (cpa_summary is not None and cpa_calc is not None and abs(float(cpa_summary) - float(cpa_calc)) <= 0.1) if b_data else False

    # total expenses within cap
    checks['budget_total_expenses_within_cap'] = (expenses_total_summary is not None and budget_cap is not None and float(expenses_total_summary) <= float(budget_cap)) if b_data else False

    # 4) run_sheet.yaml
    rs_path = os.path.join(output_dir, "run_sheet.yaml")
    rs_exists = os.path.isfile(rs_path)
    checks['run_sheet_exists'] = rs_exists
    rs_data = read_yaml_file(rs_path) if rs_exists else None
    checks['run_sheet_parsed'] = rs_data is not None

    required_roles = {
        normalize_role('Event Director'),
        normalize_role('Registration Lead'),
        normalize_role('AV/Tech Lead'),
        normalize_role('Speaker Liaison'),
        normalize_role('Catering Coordinator'),
        normalize_role('Social Media / Content'),
    }
    roles_present = collect_team_roles(rs_data) if rs_data else set()
    checks['run_sheet_required_roles_present'] = (required_roles.issubset(roles_present)) if rs_data else False

    actions = collect_timeline_actions(rs_data) if rs_data else []
    def has_action_contains(*subs):
        return any(str_contains(a, *subs) for a in actions)
    checks['run_sheet_has_av_setup'] = has_action_contains('av', 'setup') if rs_data else False
    checks['run_sheet_has_registration_setup'] = has_action_contains('registration', 'setup') if rs_data else False
    checks['run_sheet_has_opening_welcome'] = any(('welcome' in a.lower() or 'opening' in a.lower()) for a in actions) if rs_data else False
    checks['run_sheet_has_two_breaks'] = sum(1 for a in actions if 'break' in a.lower()) >= 2 if rs_data else False
    checks['run_sheet_has_lunch'] = any('lunch' in a.lower() for a in actions) if rs_data else False
    checks['run_sheet_has_closing'] = any('closing' in a.lower() or 'wrap-up' in a.lower() for a in actions) if rs_data else False
    # emergency_contacts includes venue_manager
    em = get_nested(rs_data, ['run_sheet','emergency_contacts']) or get_nested(rs_data, ['emergency_contacts']) if rs_data else None
    checks['run_sheet_has_venue_manager_contact'] = (isinstance(em, dict) and any(k for k in em.keys() if str(k).lower() == 'venue_manager')) if rs_data else False

    # 5) marketing_emails.jsonl
    me_path = os.path.join(output_dir, "marketing_emails.jsonl")
    me_exists = os.path.isfile(me_path)
    checks['marketing_emails_exists'] = me_exists
    me_rows = read_jsonl_file(me_path) if me_exists else None
    checks['marketing_emails_parsed'] = me_rows is not None
    checks['marketing_emails_min_four'] = (len(me_rows) >= 4) if me_rows is not None else False

    # verify keys present per line and validate types set
    required_types = {'save_the_date','early_bird','speaker_spotlight','last_chance'}
    type_counts = {t: 0 for t in required_types}
    keys_ok = True
    send_window_ok = True
    subject_ok = True
    if me_rows:
        for row in me_rows:
            if not all(k in row for k in ['type','subject','body','send_window']):
                keys_ok = False
                break
            # type counting
            rtype = row.get('type')
            if rtype in type_counts:
                type_counts[rtype] += 1
            # send_window allowed values
            sw = row.get('send_window')
            if sw not in ['T-90','T-75','T-60','T-7']:
                send_window_ok = False
            # subject checks per type
            subj = str(row.get('subject', ''))
            tlow = str(rtype).lower()
            s_ok = True
            if tlow == 'save_the_date':
                s_ok = ('save the date' in subj.lower())
            elif tlow == 'early_bird':
                s_ok = ('early bird' in subj.lower())
            elif tlow == 'speaker_spotlight':
                s_ok = (('is joining' in subj.lower()) or ('speaker' in subj.lower()))
            elif tlow == 'last_chance':
                s_ok = (('last chance' in subj.lower()) or ('spots left' in subj.lower()))
            subject_ok = subject_ok and s_ok
    checks['marketing_emails_keys_present'] = keys_ok if me_rows else False
    checks['marketing_emails_types_exactly_one_each'] = (all(type_counts[t] == 1 for t in required_types)) if me_rows else False
    checks['marketing_emails_send_window_values_ok'] = send_window_ok if me_rows else False
    checks['marketing_emails_subjects_match_indicative_phrases'] = subject_ok if me_rows else False

    # Compute reward: average of all boolean checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # Ensure baseline: if no outputs at all, reward must be 0.0 (checks already False)
    result = {"reward": float(round(reward, 6))}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()