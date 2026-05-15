import json
import os
import re
import sys
import csv

def read_file_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_jsonl(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                    items.append(obj)
                except Exception:
                    return None
        return items
    except Exception:
        return None

def parse_commands_lines(path):
    try:
        lines = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.rstrip("\n").strip()
                if s == "":
                    continue
                lines.append(s)
        return lines
    except Exception:
        return None

def is_base58_like(s, min_len=32, max_len=44):
    # Allowed Base58 chars (Bitcoin alphabet): 123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz
    # Excludes 0, O, I, l
    if not isinstance(s, str):
        return False
    if len(s) < min_len or len(s) > max_len:
        return False
    return re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]+", s) is not None

def parse_wallet_plan_yaml(path):
    """
    Minimal ad-hoc parser for expected wallet plan shape:
    wallets:
      - name: <string>
        words: <int>
        chains:
          - evm
          - solana
        indexes:
          - 0
          - 1
    Supports inline lists: chains: [evm, solana], indexes: [0, 1]
    Returns list of dicts: {name, words, chains:[], indexes:[]}
    """
    text = read_file_text(path)
    if text is None:
        return []

    # Normalize tabs to spaces
    lines_raw = text.replace("\t", "  ").splitlines()
    # strip comments (# ...), naive: remove trailing inline comments preceded by space or start of line
    lines = []
    for ln in lines_raw:
        if "#" in ln:
            hash_idx = ln.find("#")
            # keep content before '#' only if there is a space or start (naive)
            content = ln[:hash_idx]
        else:
            content = ln
        lines.append(content.rstrip())

    # Find 'wallets:' line
    wallets_idx = None
    wallets_indent = None
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        m = re.match(r"^(\s*)wallets\s*:\s*$", ln)
        if m:
            wallets_idx = i
            wallets_indent = len(m.group(1))
            break
    if wallets_idx is None:
        return []

    wallets = []
    current_wallet = None
    wallet_item_indent = None
    list_mode_key = None
    list_mode_indent = None

    i = wallets_idx + 1
    while i < len(lines):
        raw = lines[i]
        if raw.strip() == "":
            i += 1
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        content = raw.strip()

        # If dedented back to wallets level or less, stop parsing wallets
        if indent <= wallets_indent and not content.startswith("- "):
            # finalize last wallet
            if current_wallet is not None:
                # defaults
                if "indexes" not in current_wallet or not current_wallet["indexes"]:
                    current_wallet["indexes"] = [0, 1]
                wallets.append(current_wallet)
                current_wallet = None
            break

        # New wallet item
        if content.startswith("- ") and indent > wallets_indent:
            # Determine wallet item indent on first item
            if wallet_item_indent is None:
                wallet_item_indent = indent
            # If this is a sibling wallet item at wallet_item_indent
            if indent == wallet_item_indent:
                # close previous wallet
                if current_wallet is not None:
                    if "indexes" not in current_wallet or not current_wallet["indexes"]:
                        current_wallet["indexes"] = [0, 1]
                    wallets.append(current_wallet)
                # start new wallet
                current_wallet = {}
                list_mode_key = None
                list_mode_indent = None
                # Check if "- name: value" inline
                after_dash = content[2:].strip()
                if after_dash:
                    # Could be "name: foo"
                    kv = after_dash.split(":", 1)
                    if len(kv) == 2:
                        k = kv[0].strip()
                        v = kv[1].strip()
                        if current_wallet is not None:
                            if k == "name":
                                current_wallet["name"] = v
                            elif k == "words":
                                try:
                                    current_wallet["words"] = int(v)
                                except Exception:
                                    pass
                            elif k in ("chains", "indexes"):
                                parsed = parse_inline_list(v)
                                if parsed is not None:
                                    current_wallet[k] = parsed
                                else:
                                    # enter list mode
                                    list_mode_key = k
                                    list_mode_indent = indent + 2
                    # else ignore
            else:
                # It might be a list item for a list field within wallet
                if list_mode_key and list_mode_indent is not None and indent >= list_mode_indent:
                    item_val = content[2:].strip()
                    if current_wallet is not None:
                        if list_mode_key == "chains":
                            current_wallet.setdefault("chains", [])
                            if item_val:
                                current_wallet["chains"].append(clean_scalar(item_val))
                        elif list_mode_key == "indexes":
                            current_wallet.setdefault("indexes", [])
                            try:
                                current_wallet["indexes"].append(int(item_val))
                            except Exception:
                                pass
                # else ignore
        else:
            # Key: value under a wallet
            if current_wallet is None:
                i += 1
                continue
            # end list mode if dedented
            if list_mode_key and (indent <= (list_mode_indent or 0)):
                list_mode_key = None
                list_mode_indent = None

            kv = content.split(":", 1)
            if len(kv) == 2:
                k = kv[0].strip()
                v = kv[1].strip()
                if k == "name":
                    current_wallet["name"] = v
                elif k == "words":
                    try:
                        current_wallet["words"] = int(v)
                    except Exception:
                        pass
                elif k in ("chains", "indexes"):
                    parsed = parse_inline_list(v)
                    if parsed is not None:
                        if k == "chains":
                            current_wallet["chains"] = [clean_scalar(x) for x in parsed]
                        else:
                            # indexes as int
                            indices = []
                            for x in parsed:
                                try:
                                    indices.append(int(x))
                                except Exception:
                                    pass
                            current_wallet["indexes"] = indices
                        list_mode_key = None
                        list_mode_indent = None
                    else:
                        # list starts on subsequent lines
                        list_mode_key = k
                        list_mode_indent = indent + 2
            # else ignore non key lines
        i += 1

    # finalize last wallet at EOF
    if current_wallet is not None:
        if "indexes" not in current_wallet or not current_wallet["indexes"]:
            current_wallet["indexes"] = [0, 1]
        wallets.append(current_wallet)

    # Normalize and defaults
    normalized = []
    for w in wallets:
        name = w.get("name", "").strip()
        words = w.get("words", None)
        chains = [c.strip().lower() for c in w.get("chains", []) if isinstance(c, str)]
        idxs = w.get("indexes", [0, 1])
        if not idxs:
            idxs = [0, 1]
        normalized.append({
            "name": name,
            "words": words,
            "chains": chains,
            "indexes": idxs
        })
    return normalized

def parse_inline_list(v):
    # Parse inline list like [a, b, c]
    if not v:
        return None
    v = v.strip()
    if not (v.startswith("[") and v.endswith("]")):
        return None
    inner = v[1:-1].strip()
    if inner == "":
        return []
    parts = [p.strip() for p in inner.split(",")]
    return parts

def clean_scalar(s):
    # Remove surrounding quotes if present
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    return s

def load_addresses_csv(path):
    try:
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None, None
            header_clean = [h.strip() for h in header]
            for r in reader:
                if not r or all((c.strip() == "" for c in r)):
                    continue
                rows.append([c.strip() for c in r])
        return header_clean, rows
    except Exception:
        return None, None

def get_section_text(md_text, section_title, all_titles):
    # Return the text between section_title line and the next title line (or EOF)
    lines = md_text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == section_title:
            start = i + 1
            break
    if start is None:
        return None
    # find next title
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].strip() in all_titles:
            end = j
            break
    content = "\n".join(lines[start:end])
    return content

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_mnemonics_file": False,
        "mnemonics_count_match": False,
        "mnemonics_format_valid": False,

        "has_addresses_csv": False,
        "addresses_header_valid": False,
        "addresses_rows_cover_required": False,
        "addresses_formats_valid": False,

        "has_signatures_jsonl": False,
        "signatures_cover_all_messages": False,
        "signatures_format_valid": False,

        "has_security_audit": False,
        "security_audit_count_match": False,
        "security_audit_verdicts_correct": False,

        "has_team_report": False,
        "team_report_headings_present": False,
        "team_report_paths_under_output": False,

        "has_roster": False,
        "roster_has_team_leader": False,

        "openai_jsonl_exists": False,
        "openai_jsonl_count_ok": False,
        "openai_jsonl_format_valid": False,

        "alpaca_jsonl_exists": False,
        "alpaca_jsonl_count_ok": False,
        "alpaca_jsonl_format_valid": False,

        "optimization_report_exists": False,
        "optimization_report_fields_valid": False,

        "improvement_report_exists": False,
        "improvement_report_fields_valid": False,
    }

    # Load inputs
    wallet_plan_path = os.path.join(input_dir, "wallet_plan.yaml")
    messages_path = os.path.join(input_dir, "messages.jsonl")
    commands_path = os.path.join(input_dir, "commands.txt")
    feedback_seed_path = os.path.join(input_dir, "feedback_seed.json")

    wallets = parse_wallet_plan_yaml(wallet_plan_path)
    # Derive expected combos for addresses and indexes 0 and 1 at minimum
    expected_address_combos = set()
    for w in wallets:
        name = w.get("name", "")
        chains = w.get("chains", [])
        # ensure at least indexes 0 and 1
        expected_idxs = set([0, 1])
        for idx in w.get("indexes", []):
            expected_idxs.add(idx)
        # We require at least 0 and 1 to exist
        required_idxs = [0, 1]
        for ch in chains:
            for idx in required_idxs:
                expected_address_combos.add((name, ch, idx))

    # 1) Wallet mnemonics file
    mnemo_path = os.path.join(output_dir, "wallet_mnemonics.txt")
    if os.path.isfile(mnemo_path):
        checks["has_mnemonics_file"] = True
        try:
            with open(mnemo_path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f.read().splitlines() if ln.strip() != ""]
            wallet_count = len(wallets)
            if wallet_count > 0 and len(lines) == wallet_count:
                checks["mnemonics_count_match"] = True
            # Validate each line word count 12 or 24
            if lines:
                all_valid = True
                for ln in lines:
                    words = [w for w in ln.strip().split(" ") if w != ""]
                    if len(words) not in (12, 24):
                        all_valid = False
                        break
                if all_valid:
                    checks["mnemonics_format_valid"] = True
        except Exception:
            pass

    # 2) Addresses CSV
    addresses_path = os.path.join(output_dir, "addresses.csv")
    if os.path.isfile(addresses_path):
        checks["has_addresses_csv"] = True
        header, rows = load_addresses_csv(addresses_path)
        if header is not None and rows is not None:
            expected_header = ["wallet_name", "chain", "index", "address"]
            if [h.strip() for h in header] == expected_header:
                checks["addresses_header_valid"] = True

            # Build lookup for rows
            row_map = {}
            for r in rows:
                # handle rows with exactly 4 columns
                if len(r) < 4:
                    continue
                wname, chain, idx_str, addr = r[0], r[1], r[2], r[3]
                try:
                    idx = int(idx_str)
                except Exception:
                    continue
                key = (wname, chain.lower(), idx)
                row_map.setdefault(key, []).append(addr)

            # Coverage for required combos (0 and 1 per wallet per chain)
            if expected_address_combos:
                cover_ok = True
                for (wname, ch, idx) in expected_address_combos:
                    key = (wname, ch.lower(), idx)
                    if key not in row_map or len([a for a in row_map[key] if a]):
                        # intend to check presence; if exists with any non-empty address
                        pass
                    if key not in row_map:
                        cover_ok = False
                        break
                if cover_ok:
                    checks["addresses_rows_cover_required"] = True

            # Validate address formats
            def valid_addr(chain, addr):
                if not addr or not isinstance(addr, str):
                    return False
                ch = chain.lower()
                if ch == "evm":
                    return re.fullmatch(r"0x[a-fA-F0-9]{40}", addr) is not None
                elif ch == "solana":
                    return is_base58_like(addr, 32, 44) and not addr.lower().startswith("0x")
                elif ch == "bitcoin":
                    return addr.startswith("1") or addr.startswith("3") or addr.lower().startswith("bc1")
                elif ch == "cosmos":
                    return addr.startswith("cosmos1")
                elif ch == "tron":
                    return addr.startswith("T")
                else:
                    # Unknown chain; mark invalid
                    return False

            if rows:
                all_fmt_ok = True
                for r in rows:
                    if len(r) < 4:
                        all_fmt_ok = False
                        break
                    wname, chain, idx_str, addr = r[0], r[1], r[2], r[3]
                    if not valid_addr(chain, addr):
                        all_fmt_ok = False
                        break
                if all_fmt_ok:
                    checks["addresses_formats_valid"] = True

    # 3) Signatures JSONL
    sigs_path = os.path.join(output_dir, "signatures.jsonl")
    msgs = read_jsonl(messages_path)
    sigs = read_jsonl(sigs_path) if os.path.isfile(sigs_path) else None
    if os.path.isfile(sigs_path) and sigs is not None:
        checks["has_signatures_jsonl"] = True
        # Coverage: for each message in input, require one matching signature object
        cover = True
        fmt_ok = True
        # Build set for quick membership
        sig_keys = set()
        for s in sigs:
            # Ensure fields exist
            if not isinstance(s, dict):
                fmt_ok = False
                break
            required_fields = ["wallet_name", "chain", "index", "address", "message", "signature"]
            if not all(k in s for k in required_fields):
                fmt_ok = False
                break
            # signature non-empty; evm must start with 0x
            sig_val = s.get("signature")
            if not isinstance(sig_val, str) or sig_val.strip() == "":
                fmt_ok = False
                break
            ch = str(s.get("chain", "")).lower()
            if ch == "evm" and not sig_val.startswith("0x"):
                fmt_ok = False
                break
            # normalize key
            try:
                idx = int(s.get("index"))
            except Exception:
                fmt_ok = False
                break
            key = (str(s.get("wallet_name")), ch, idx, str(s.get("message")))
            sig_keys.add(key)
        if msgs is None:
            cover = False
        else:
            for m in msgs:
                if not isinstance(m, dict):
                    cover = False
                    break
                wname = str(m.get("wallet_name", ""))
                ch = str(m.get("chain", "")).lower()
                try:
                    idx = int(m.get("index", 0))
                except Exception:
                    cover = False
                    break
                msg_text = str(m.get("message", ""))
                key = (wname, ch, idx, msg_text)
                if key not in sig_keys:
                    cover = False
                    break
        if cover:
            checks["signatures_cover_all_messages"] = True
        if fmt_ok:
            checks["signatures_format_valid"] = True

    # 4) Security audit
    audit_path = os.path.join(output_dir, "security_audit.json")
    commands = parse_commands_lines(commands_path)
    audit = read_json(audit_path)
    if audit is not None and isinstance(audit, list):
        checks["has_security_audit"] = True
        # count match
        if commands is not None and len(audit) == len(commands):
            checks["security_audit_count_match"] = True
        # build map from input to verdict
        # allow duplicates: use list of verdicts per input
        verdict_map = {}
        for item in audit:
            if not isinstance(item, dict):
                continue
            inp = str(item.get("input", "")).strip()
            verdict = str(item.get("verdict", "")).strip()
            reason = item.get("reason", "")
            if inp not in verdict_map:
                verdict_map[inp] = []
            verdict_map[inp].append((verdict, reason))

        # evaluate deterministic rules
        rules_ok = True
        if commands is not None:
            for line in commands:
                expected = None
                # Rule 1: pipe to shell -> blocked
                if "| bash" in line:
                    expected = "blocked"
                # Rule 2: package installs -> warning
                elif re.match(r"^\s*pip\s+install\b", line) or ("npm install" in line):
                    expected = "warning"
                # Rule 3: plain github URL -> safe
                elif (("github.com" in line) and
                      (line.startswith("http://") or line.startswith("https://")) and
                      ("|" not in line and ";" not in line and "`" not in line and "$(" not in line)):
                    expected = "safe"

                if expected is not None:
                    entries = verdict_map.get(line, [])
                    # must have at least one matching verdict
                    if not any(v == expected for v, _ in entries):
                        rules_ok = False
                        break
                else:
                    # For lines without deterministic rule, ensure verdict is one of allowed if present
                    entries = verdict_map.get(line, [])
                    if entries:
                        if not all(v in ("safe", "warning", "blocked") for v, _ in entries):
                            rules_ok = False
                            break
            if rules_ok:
                checks["security_audit_verdicts_correct"] = True

    # 5) Team report and roster
    team_report_path = os.path.join(output_dir, "team", "team_creation_report.md")
    roster_path = os.path.join(output_dir, "team", "roster.json")
    md = read_file_text(team_report_path)
    if md is not None:
        checks["has_team_report"] = True
        required_headings = [
            "Confirmed Team Roles",
            "Agent Contracts",
            "Collaboration Workflow",
            "Stage Deliverables with Paths",
            "Protocol Summary",
            "Security Summary",
            "Team Leader Boundary Check"
        ]
        if all(h in md for h in required_headings):
            checks["team_report_headings_present"] = True
        # Check paths under "Stage Deliverables with Paths"
        section_text = get_section_text(md, "Stage Deliverables with Paths", required_headings)
        if section_text is not None:
            # Conditions:
            # - No absolute paths starting with "/"
            # - No external URLs
            # - Deliverable paths reference under "output/" (at least one occurrence; ideally all)
            no_abs = not re.search(r"(^|\s)/[^ \t\n]+", section_text)
            no_urls = ("http://" not in section_text) and ("https://" not in section_text)
            has_output_ref = ("output/" in section_text)
            if no_abs and no_urls and has_output_ref:
                checks["team_report_paths_under_output"] = True

    roster = read_json(roster_path)
    if roster is not None:
        checks["has_roster"] = True
        # Expect at least one role with id containing "team-leader"
        found_leader = False
        if isinstance(roster, dict):
            # Could be {"roles":[{"id":"..."}]}
            roles = []
            if "roles" in roster and isinstance(roster["roles"], list):
                roles = roster["roles"]
            else:
                # maybe the dict itself is a role map
                for v in roster.values():
                    if isinstance(v, dict):
                        roles.append(v)
            for r in roles:
                rid = str(r.get("id", ""))
                if "team-leader" in rid:
                    found_leader = True
                    break
        elif isinstance(roster, list):
            for r in roster:
                if isinstance(r, dict) and "id" in r and "team-leader" in str(r["id"]):
                    found_leader = True
                    break
        if found_leader:
            checks["roster_has_team_leader"] = True

    # 6) Feedback-driven improvement artifacts
    feedback_seed = read_json(feedback_seed_path)
    positive_neutral_correction_count = 0
    if feedback_seed is not None:
        # Expect array of feedback items, each with rating field
        items = []
        if isinstance(feedback_seed, list):
            items = feedback_seed
        elif isinstance(feedback_seed, dict):
            # if it has a top-level "items" or similar
            if isinstance(feedback_seed.get("items"), list):
                items = feedback_seed.get("items", [])
            else:
                # consider values that are lists
                for v in feedback_seed.values():
                    if isinstance(v, list):
                        items = v
                        break
        for it in items:
            if not isinstance(it, dict):
                continue
            rating = str(it.get("rating", "")).lower()
            if rating in ("positive", "neutral", "correction"):
                positive_neutral_correction_count += 1

    # openai.jsonl
    openai_path = os.path.join(output_dir, "training", "openai.jsonl")
    openai_items = read_jsonl(openai_path) if os.path.isfile(openai_path) else None
    if openai_items is not None:
        checks["openai_jsonl_exists"] = True
        if positive_neutral_correction_count == 0 or len(openai_items) >= positive_neutral_correction_count:
            checks["openai_jsonl_count_ok"] = True
        # format: each line has messages array with at least two elements
        fmt_ok = True
        for obj in openai_items:
            if not isinstance(obj, dict):
                fmt_ok = False
                break
            msgs = obj.get("messages")
            if not isinstance(msgs, list) or len(msgs) < 2:
                fmt_ok = False
                break
        if fmt_ok:
            checks["openai_jsonl_format_valid"] = True

    # alpaca.jsonl
    alpaca_path = os.path.join(output_dir, "training", "alpaca.jsonl")
    alpaca_items = read_jsonl(alpaca_path) if os.path.isfile(alpaca_path) else None
    if alpaca_items is not None:
        checks["alpaca_jsonl_exists"] = True
        if positive_neutral_correction_count == 0 or len(alpaca_items) >= positive_neutral_correction_count:
            checks["alpaca_jsonl_count_ok"] = True
        fmt_ok = True
        for obj in alpaca_items:
            if not isinstance(obj, dict):
                fmt_ok = False
                break
            if not isinstance(obj.get("instruction"), str):
                fmt_ok = False
                break
            # input may be empty string but must exist and be string
            if "input" not in obj or not isinstance(obj.get("input"), str):
                fmt_ok = False
                break
            if not isinstance(obj.get("output"), str):
                fmt_ok = False
                break
        if fmt_ok:
            checks["alpaca_jsonl_format_valid"] = True

    # optimization report
    optimization_path = os.path.join(output_dir, "optimization", "report.json")
    optimization = read_json(optimization_path)
    if optimization is not None:
        checks["optimization_report_exists"] = True
        if isinstance(optimization, dict):
            best = optimization.get("bestTemplate")
            suggestions = optimization.get("suggestions")
            if isinstance(best, str) and best.strip() != "" and isinstance(suggestions, list):
                checks["optimization_report_fields_valid"] = True

    # improvement report
    improvement_path = os.path.join(output_dir, "improvement", "report.json")
    improvement = read_json(improvement_path)
    if improvement is not None:
        checks["improvement_report_exists"] = True
        if isinstance(improvement, dict):
            trends = improvement.get("trends")
            summary = improvement.get("summary")
            latest_ok = False
            if isinstance(trends, dict) and isinstance(summary, dict):
                lqs = summary.get("latestQualityScore")
                if isinstance(lqs, (int, float)):
                    latest_ok = True
            if latest_ok:
                checks["improvement_report_fields_valid"] = True

    # Compute reward as average of passed checks (all are artifact-dependent)
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
    # No-op baseline: if output is empty or missing required artifacts, ensure reward 0.0
    # This naturally holds because no checks would pass.

    result = {"reward": float(round(reward, 6))}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()