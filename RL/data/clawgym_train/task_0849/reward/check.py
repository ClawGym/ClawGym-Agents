import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

def slugify(name: str) -> str:
    # Lowercase, replace non-alphanumerics with hyphens, collapse, trim
    s = name.lower()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    s = re.sub(r'-{2,}', '-', s).strip('-')
    return s

def read_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def list_md_files(dir_path: str) -> List[str]:
    if not os.path.isdir(dir_path):
        return []
    files = []
    for root, _, filenames in os.walk(dir_path):
        for fn in filenames:
            if fn.lower().endswith(".md"):
                files.append(os.path.join(root, fn))
    return files

def load_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def extract_frontmatter(text: str) -> Tuple[Optional[str], Optional[str]]:
    # Returns (frontmatter_text, body_text)
    # frontmatter delimited by first '---' line and next '---'
    lines = text.splitlines()
    if not lines:
        return None, None
    if lines[0].strip() != "---":
        return None, None
    # find closing ---
    try:
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break
        if end_idx is None:
            return None, None
        fm = "\n".join(lines[1:end_idx])
        body = "\n".join(lines[end_idx+1:])
        return fm, body
    except Exception:
        return None, None

def parse_inline_list(val: str) -> List[str]:
    # Parses YAML-like inline list: [a, b, 'c d']
    inner = val.strip()
    if inner.startswith('[') and inner.endswith(']'):
        inner = inner[1:-1].strip()
        if not inner:
            return []
        parts = []
        buf = ""
        in_quote = False
        quote_char = ''
        for ch in inner:
            if ch in ['"', "'"]:
                if not in_quote:
                    in_quote = True
                    quote_char = ch
                elif quote_char == ch:
                    in_quote = False
                else:
                    buf += ch
            elif ch == ',' and not in_quote:
                parts.append(buf.strip())
                buf = ""
            else:
                buf += ch
        if buf.strip():
            parts.append(buf.strip())
        return [strip_quotes(p).strip() for p in parts if p is not None]
    return []

def strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s

def parse_frontmatter_to_dict(fm: str) -> Dict[str, Any]:
    """
    Minimal YAML parser for simple key: value and key: lists (inline [..] or multi-line with "- ").
    Returns dict with strings, numbers, or lists of strings.
    """
    result: Dict[str, Any] = {}
    lines = fm.splitlines()
    i = 0
    current_key = None
    while i < len(lines):
        line = lines[i]
        # Skip empty/comment lines
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        if re.match(r'^\s*-\s', line):
            # Bare list item without a key: ignore (malformed)
            i += 1
            continue
        m = re.match(r'^\s*([A-Za-z0-9_\-]+)\s*:\s*(.*)$', line)
        if m:
            key = m.group(1).strip()
            val = m.group(2).rstrip()
            current_key = key
            # If value looks like inline list
            if val.strip().startswith('[') and val.strip().endswith(']'):
                result[key] = parse_inline_list(val.strip())
                i += 1
                continue
            # If value is empty, might be start of multi-line list or nested map
            if val.strip() == "":
                # Look ahead for list items
                j = i + 1
                items: List[str] = []
                while j < len(lines):
                    nxt = lines[j]
                    if re.match(r'^\s*-\s+(.*)$', nxt):
                        item_val = re.match(r'^\s*-\s+(.*)$', nxt).group(1)
                        items.append(strip_quotes(item_val.strip()))
                        j += 1
                    elif not nxt.strip():
                        j += 1
                    else:
                        break
                if items:
                    result[key] = items
                    i = j
                    continue
                else:
                    # No items; set to empty string
                    result[key] = ""
                    i += 1
                    continue
            # Otherwise treat as scalar
            sval = strip_quotes(val.strip())
            # Try to coerce number
            if re.fullmatch(r'-?\d+(\.\d+)?', sval):
                try:
                    if '.' in sval:
                        num = float(sval)
                    else:
                        num = int(sval)
                    result[key] = num
                except Exception:
                    result[key] = sval
            else:
                result[key] = sval
            i += 1
            continue
        else:
            i += 1
            continue
    return result

def get_expected_signals() -> List[Dict[str, Any]]:
    # Define the expected signals specification.
    return [
        {
            "target_name": "Seesaw",
            "target_category": "food",
            "city": "Shanghai",
            "signal_type": "price_change",
            "content_substrings": ["Americano", "32"],
            "severity": "notable",
            "neighborhood": "Yuyuan Road",
            "district": "Changning",
            "subcategory": "coffee",
            "price": 32,
            "price_unit": "CNY",
            "date": "2026-04-12T09:30:00+08:00",
            "filename_date": "20260412",
            "tags_contains": [],
            "suitable_for_contains": [],
        },
        {
            "target_name": "Bakery next to Changning Finance Park",
            "target_category": "food",
            "city": "Shanghai",
            "signal_type": "closure",
            "content_substrings": ["clos",],  # match "closed"/"closure"
            "severity": "important",
            "neighborhood": "Changning Finance Park",
            "district": "Changning",
            "date": "2026-04-12T10:05:00+08:00",
            "filename_date": "20260412",
            "tags_contains": [],
            "suitable_for_contains": [],
        },
        {
            "target_name": "BW Coffee",
            "target_category": "food",
            "city": "New York",
            "signal_type": "recommendation",
            "content_substrings": ["cold brew"],
            "severity": "info",
            "neighborhood": "East Village",
            "district": "Manhattan",
            "subcategory": "coffee",
            "date": "2026-04-12T16:20:00-04:00",
            "filename_date": "20260412",
            "tags_contains": [],
            "suitable_for_contains": [],
        },
        {
            "target_name": "Shanghai Metro Line 2",
            "target_category": "transport",
            "city": "Shanghai",
            "signal_type": "event",
            "content_substrings": ["jing", "nanjing west", "20"],
            "severity": "notable",
            "date": "2026-04-12T08:10:00+08:00",
            "filename_date": "20260412",
            "tags_contains": ["delay"],
            "suitable_for_contains": [],
        },
        {
            "target_name": "Green Bowl",
            "target_category": "food",
            "city": "Shanghai",
            "signal_type": "update",
            "content_substrings": ["vegetarian", "bento", "48"],
            "severity": "info",
            "neighborhood": "Yuyuan Road",
            "district": "Changning",
            "subcategory": "bento",
            "price": 48,
            "price_unit": "CNY",
            "date": "2026-04-11T12:45:00+08:00",
            "filename_date": "20260411",
            "tags_contains": [],
            "suitable_for_contains": ["vegetarian"],
        },
        {
            "target_name": "Pop-up ramen (3rd Ave near 10th St)",
            "target_category": "food",
            "city": "New York",
            "signal_type": "new_opening",
            "content_substrings": ["soft opening", "ramen", "3rd", "10th"],
            "severity": "info",
            "neighborhood": "East Village",
            "district": "Manhattan",
            "subcategory": "ramen",
            "date": "2026-04-11T18:00:00-04:00",
            "filename_date": "20260411",
            "tags_contains": [],
            "suitable_for_contains": [],
        },
    ]

def find_signal_by_name(signals: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    for s in signals:
        if isinstance(s, dict) and s.get("target_name") == name:
            return s
    return None

def content_contains_required(content: str, substrings: List[str]) -> bool:
    c = (content or "").lower()
    for sub in substrings:
        if sub.lower() not in c:
            return False
    return True

def list_contains_value(lst: Any, value: str) -> bool:
    if not isinstance(lst, list):
        return False
    for item in lst:
        try:
            if isinstance(item, str) and item.strip().lower() == value.lower():
                return True
        except Exception:
            continue
    return False

def compare_frontmatter_to_json(fm: Dict[str, Any], js: Dict[str, Any], required_keys: List[str], optional_keys_to_check: List[str]) -> bool:
    # Required keys must match exactly
    for k in required_keys:
        if k not in fm or k not in js:
            return False
        # Normalize types for comparison
        v_fm = fm[k]
        v_js = js[k]
        if isinstance(v_js, (int, float)) and isinstance(v_fm, (int, float)):
            if float(v_js) != float(v_fm):
                return False
        else:
            if str(v_js) != str(v_fm):
                return False
    # Optional keys: if present in js, they must match in fm (at least include the expected values)
    for k in optional_keys_to_check:
        if k in js:
            if k not in fm:
                return False
            v_js = js[k]
            v_fm = fm[k]
            if isinstance(v_js, list):
                # compare as sets of stringified items lowercase
                set_js = set([str(x).strip().lower() for x in v_js])
                set_fm = set([str(x).strip().lower() for x in v_fm]) if isinstance(v_fm, list) else set([str(v_fm).strip().lower()])
                if not set_js.issubset(set_fm) or not set_fm.issubset(set_js):
                    return False
            elif isinstance(v_js, (int, float)) and isinstance(v_fm, (int, float)):
                if float(v_js) != float(v_fm):
                    return False
            else:
                if str(v_js) != str(v_fm):
                    return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {}

    # Initialize all checks to False
    check_names = [
        "has_signals_json",
        "signals_json_is_array",
        "signals_count_exact",
        "signals_unique_targets",
        "seesaw_present",
        "seesaw_fields_match",
        "bakery_present",
        "bakery_fields_match",
        "bwcoffee_present",
        "bwcoffee_fields_match",
        "metro_present",
        "metro_fields_match",
        "greenbowl_present",
        "greenbowl_fields_match",
        "ramen_present",
        "ramen_fields_match",
        "md_dir_exists",
        "md_count_exact",
        "md_filenames_match",
        "fm_seesaw_matches_json",
        "fm_bakery_matches_json",
        "fm_bwcoffee_matches_json",
        "fm_metro_matches_json",
        "fm_greenbowl_matches_json",
        "fm_ramen_matches_json",
        "consent_exists",
        "consent_sentence_present",
        "consent_targets_bulleted",
    ]
    for n in check_names:
        checks[n] = False

    expected_list = get_expected_signals()

    # Load signals.json
    signals_path = os.path.join(output_dir, "signals.json")
    signals = read_json(signals_path)
    if signals is not None:
        checks["has_signals_json"] = True
        if isinstance(signals, list):
            checks["signals_json_is_array"] = True
            if len(signals) == 6:
                checks["signals_count_exact"] = True
                # Ensure unique target_names
                names = [s.get("target_name") for s in signals if isinstance(s, dict)]
                if len(names) == 6 and len(set(names)) == 6:
                    checks["signals_unique_targets"] = True

    # Validate each expected signal fields in JSON
    name_to_signal: Dict[str, Dict[str, Any]] = {}
    if checks["signals_json_is_array"]:
        for s in signals:
            if isinstance(s, dict) and "target_name" in s:
                name_to_signal[s["target_name"]] = s

    # Helper to validate fields
    def validate_signal_fields(exp: Dict[str, Any], actual: Dict[str, Any]) -> bool:
        if not isinstance(actual, dict):
            return False
        required_fields = ["target_name", "target_category", "city", "signal_type", "content", "severity", "date"]
        for k in required_fields:
            if k not in actual:
                return False
        # Exact matches for these
        if actual.get("target_name") != exp.get("target_name"):
            return False
        if actual.get("target_category") != exp.get("target_category"):
            return False
        if actual.get("city") != exp.get("city"):
            return False
        if actual.get("signal_type") != exp.get("signal_type"):
            return False
        if actual.get("severity") != exp.get("severity"):
            return False
        if actual.get("date") != exp.get("date"):
            return False
        # Content substring checks
        if not content_contains_required(str(actual.get("content", "")), exp.get("content_substrings", [])):
            return False
        # Optional expected fields checks if provided in expected
        # neighborhood
        if "neighborhood" in exp:
            if actual.get("neighborhood") != exp.get("neighborhood"):
                return False
        # district
        if "district" in exp:
            if actual.get("district") != exp.get("district"):
                return False
        # subcategory
        if "subcategory" in exp:
            if actual.get("subcategory") != exp.get("subcategory"):
                return False
        # price and price_unit
        if "price" in exp:
            if "price" not in actual:
                return False
            aval = actual.get("price")
            try:
                if float(aval) != float(exp.get("price")):
                    return False
            except Exception:
                return False
            if actual.get("price_unit") != exp.get("price_unit"):
                return False
        # tags contains
        for tag in exp.get("tags_contains", []):
            if not list_contains_value(actual.get("tags"), tag):
                return False
        # suitable_for contains
        for sf in exp.get("suitable_for_contains", []):
            if not list_contains_value(actual.get("suitable_for"), sf):
                return False
        return True

    # For each expected, set present and fields match checks
    for exp in expected_list:
        name = exp["target_name"]
        present_key = None
        match_key = None
        if name == "Seesaw":
            present_key = "seesaw_present"
            match_key = "seesaw_fields_match"
        elif name == "Bakery next to Changning Finance Park":
            present_key = "bakery_present"
            match_key = "bakery_fields_match"
        elif name == "BW Coffee":
            present_key = "bwcoffee_present"
            match_key = "bwcoffee_fields_match"
        elif name == "Shanghai Metro Line 2":
            present_key = "metro_present"
            match_key = "metro_fields_match"
        elif name == "Green Bowl":
            present_key = "greenbowl_present"
            match_key = "greenbowl_fields_match"
        elif name == "Pop-up ramen (3rd Ave near 10th St)":
            present_key = "ramen_present"
            match_key = "ramen_fields_match"
        if present_key and match_key:
            actual = name_to_signal.get(name)
            if actual is not None:
                checks[present_key] = True
                if validate_signal_fields(exp, actual):
                    checks[match_key] = True

    # MD files checks
    md_dir = os.path.join(output_dir, "for_github", "signals")
    md_files = list_md_files(md_dir)
    if os.path.isdir(md_dir):
        checks["md_dir_exists"] = True
    if md_files:
        # Count .md files exactly 6
        md_count = len([p for p in md_files if p.lower().endswith(".md")])
        if md_count == 6:
            checks["md_count_exact"] = True

    # Build expected filenames
    expected_filenames = {}
    for exp in expected_list:
        date_prefix = exp["filename_date"]
        slug = slugify(exp["target_name"])
        sigtype = exp["signal_type"]
        filename = f"{date_prefix}_{slug}_{sigtype}.md"
        expected_filenames[exp["target_name"]] = filename

    # Check filenames presence matches exactly the set
    existing_basenames = set([os.path.basename(p) for p in md_files])
    expected_basenames = set(expected_filenames.values())
    if existing_basenames == expected_basenames and len(existing_basenames) == 6:
        checks["md_filenames_match"] = True

    # Frontmatter vs JSON checks per file (mirror required + specified optional fields)
    def fm_match_for(exp: Dict[str, Any], json_signal: Dict[str, Any], checks_key: str) -> None:
        # If file missing, cannot pass
        fname = expected_filenames.get(exp["target_name"])
        if not fname:
            return
        fullpath = os.path.join(md_dir, fname)
        text = load_text(fullpath)
        if not text:
            return
        fm_text, body_text = extract_frontmatter(text)
        if not fm_text:
            return
        fm = parse_frontmatter_to_dict(fm_text)
        # Required fields
        required_keys = ["target_name", "target_category", "city", "signal_type", "content", "severity", "date"]
        # Optional keys to check (only if present in JSON)
        optional_keys = ["neighborhood", "district", "tags", "suitable_for", "price", "price_unit", "subcategory"]
        if compare_frontmatter_to_json(fm, json_signal, required_keys, optional_keys):
            checks[checks_key] = True

    # Only attempt if signals.json loaded correctly
    if checks["signals_json_is_array"]:
        # Map by name again
        for exp in expected_list:
            name = exp["target_name"]
            js = name_to_signal.get(name)
            if not js:
                continue
            if name == "Seesaw":
                fm_match_for(exp, js, "fm_seesaw_matches_json")
            elif name == "Bakery next to Changning Finance Park":
                fm_match_for(exp, js, "fm_bakery_matches_json")
            elif name == "BW Coffee":
                fm_match_for(exp, js, "fm_bwcoffee_matches_json")
            elif name == "Shanghai Metro Line 2":
                fm_match_for(exp, js, "fm_metro_matches_json")
            elif name == "Green Bowl":
                fm_match_for(exp, js, "fm_greenbowl_matches_json")
            elif name == "Pop-up ramen (3rd Ave near 10th St)":
                fm_match_for(exp, js, "fm_ramen_matches_json")

    # Consent message checks
    consent_path = os.path.join(output_dir, "consent_message.txt")
    consent_text = load_text(consent_path)
    if consent_text is not None:
        checks["consent_exists"] = True
        if "Would you like me to share it as a Signal on OpenBook so others can benefit?" in consent_text:
            checks["consent_sentence_present"] = True
        # Check bullet list contains all six target names
        lines = [ln.strip() for ln in consent_text.splitlines()]
        bullet_lines = [ln for ln in lines if ln.startswith("- ") or ln.startswith("* ")]
        bullets_text = "\n".join(bullet_lines)
        all_present = True
        needed_names = [exp["target_name"] for exp in expected_list]
        for nm in needed_names:
            if nm not in bullets_text:
                all_present = False
                break
        if all_present:
            checks["consent_targets_bulleted"] = True

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # If no outputs at all, ensure 0.0
    # Model no-op baseline: if output directory missing or empty relevant artifacts then reward is 0.0
    # If none of the three main artifacts exist, force zero
    main_artifacts = 0
    if checks["has_signals_json"]:
        main_artifacts += 1
    if checks["md_dir_exists"]:
        main_artifacts += 1
    if checks["consent_exists"]:
        main_artifacts += 1
    if main_artifacts == 0:
        reward = 0.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()