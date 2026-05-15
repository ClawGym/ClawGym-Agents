import json
import os
import sys
import csv
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        import json as _json
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return None

def parse_signals_csv(path):
    results = {}
    if not os.path.isfile(path):
        return results
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = [h.strip() for h in reader.fieldnames] if reader.fieldnames else []
        # Normalize header names to lower with simple mapping
        def norm(h):
            return h.strip().lower().replace(" ", "").replace("_", "")
        # Expected columns set
        # task_id, frequency, time cost, skill required, risk
        for row in reader:
            # Identify task id column
            task_id = None
            for k, v in row.items():
                if norm(k) in ("taskid", "task_id", "task"):
                    task_id = v.strip()
                    break
            if not task_id:
                continue
            rec = {}
            for k, v in row.items():
                nk = norm(k)
                if nk in ("frequency", "timecost", "timer", "time"):
                    try:
                        rec["frequency"] = int(str(v).strip())
                    except Exception:
                        pass
                if nk in ("timecost", "time_cost"):
                    try:
                        rec["time_cost"] = int(str(v).strip())
                    except Exception:
                        pass
                if nk == "timecost":
                    try:
                        rec["time_cost"] = int(str(v).strip())
                    except Exception:
                        pass
                if nk in ("skillrequired", "skill_req", "skill"):
                    try:
                        rec["skill_required"] = int(str(v).strip())
                    except Exception:
                        pass
                if nk == "risk":
                    try:
                        rec["risk"] = int(str(v).strip())
                    except Exception:
                        pass
                # also support explicit headers
                if k.strip() == "Frequency":
                    try:
                        rec["frequency"] = int(str(v).strip())
                    except Exception:
                        pass
                if k.strip() == "Time cost":
                    try:
                        rec["time_cost"] = int(str(v).strip())
                    except Exception:
                        pass
                if k.strip() == "Skill required":
                    try:
                        rec["skill_required"] = int(str(v).strip())
                    except Exception:
                        pass
                if k.strip() == "Risk":
                    try:
                        rec["risk"] = int(str(v).strip())
                    except Exception:
                        pass
            # Ensure fields exist
            if all(k in rec for k in ("frequency", "time_cost", "skill_required", "risk")):
                results[task_id] = rec
    return results

def compute_priority(rec):
    # Priority = Frequency × Time cost × (4 - Skill required) × (4 - Risk)
    try:
        freq = int(rec["frequency"])
        time_cost = int(rec["time_cost"])
        skill_req = int(rec["skill_required"])
        risk = int(rec["risk"])
        return int(freq * time_cost * (4 - skill_req) * (4 - risk))
    except Exception:
        return None

def parse_sections_bottlenecks(text):
    # Split by lines starting with "## "
    lines = text.splitlines()
    sections = []
    current_id = None
    current_lines = []
    for line in lines:
        if line.strip().startswith("## "):
            # store previous
            if current_id is not None:
                sections.append((current_id, "\n".join(current_lines).strip()))
            current_id = line.strip()[3:].strip()
            current_lines = []
        else:
            if current_id is not None:
                current_lines.append(line)
    if current_id is not None:
        sections.append((current_id, "\n".join(current_lines).strip()))
    return sections

def extract_priority_from_section(section_text):
    # Look for line starting with "Priority:" and extract integer
    for line in section_text.splitlines():
        if line.strip().lower().startswith("priority:"):
            val = line.split(":", 1)[1].strip()
            # Extract first integer in the string
            m = re.search(r"-?\d+", val)
            if m:
                try:
                    return int(m.group(0))
                except Exception:
                    pass
    return None

def section_has_required_fields(section_text):
    required_labels = ["What:", "Frequency:", "Time cost:", "Skill required:", "Risk:", "Priority:"]
    present = {label: False for label in required_labels}
    for line in section_text.splitlines():
        s = line.strip()
        for label in required_labels:
            if s.startswith(label):
                present[label] = True
    return all(present.values())

def find_proposal_blocks(text):
    # Split proposals by "Delegation opportunity" marker (allow emoji before)
    lines = text.splitlines()
    start_indices = []
    for i, line in enumerate(lines):
        if "Delegation opportunity" in line:
            start_indices.append(i)
    blocks = []
    for idx, start in enumerate(start_indices):
        end = start_indices[idx + 1] if idx + 1 < len(start_indices) else len(lines)
        block = "\n".join(lines[start:end]).strip()
        if block:
            blocks.append(block)
    return blocks

def proposal_block_checks(block_text, expected_task_id):
    # Check all required lines and exact proposal line format
    lines = [l.strip() for l in block_text.splitlines() if l.strip() != ""]
    # Must contain "Delegation opportunity" anywhere in the block
    has_title = any("Delegation opportunity" in l for l in lines)
    has_i_noticed = any(l.startswith("I noticed:") for l in lines)
    has_pattern = any(l.startswith("Pattern:") for l in lines)
    # Proposal line exact
    expected_proposal_line = f"Proposal: I could handle {expected_task_id} without asking each time."
    has_proposal_line = expected_proposal_line in lines
    # Pilot and Then exact lines
    has_pilot = "Pilot: First 5x I'll do it and tell you after." in lines
    has_then = "Then: Full autonomy if you're happy." in lines
    has_question = any(l == "Want to try?" for l in lines)
    return all([has_title, has_i_noticed, has_pattern, has_proposal_line, has_pilot, has_then, has_question])

def parse_declines_json(path):
    data = read_json(path)
    declines = {}
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            tid = item.get("task_id") or item.get("task") or item.get("id")
            if tid:
                declines[tid] = {
                    "reason": item.get("reason"),
                    "declined_on": item.get("declined_on") or item.get("date") or item.get("declinedDate"),
                }
    elif isinstance(data, dict):
        # Could be mapping task_id -> details or an object with "declines": [...]
        if "declines" in data and isinstance(data["declines"], list):
            for item in data["declines"]:
                if not isinstance(item, dict):
                    continue
                tid = item.get("task_id") or item.get("task") or item.get("id")
                if tid:
                    declines[tid] = {
                        "reason": item.get("reason"),
                        "declined_on": item.get("declined_on") or item.get("date") or item.get("declinedDate"),
                    }
        else:
            for tid, item in data.items():
                if isinstance(item, dict):
                    declines[tid] = {
                        "reason": item.get("reason"),
                        "declined_on": item.get("declined_on") or item.get("date") or item.get("declinedDate"),
                    }
    return declines

def check_no_execution_claims(dir_path):
    banned = ["executed", "done", "completed"]
    if not os.path.isdir(dir_path):
        return True
    for root, _, files in os.walk(dir_path):
        for fn in files:
            if not any(fn.endswith(ext) for ext in (".txt", ".csv", ".json", ".jsonl", ".md", ".tsv", ".yaml", ".xml", ".html", ".py")):
                continue
            p = os.path.join(root, fn)
            try:
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read().lower()
                for b in banned:
                    if b in content:
                        return False
            except Exception:
                # If cannot read, be conservative and fail
                return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "outputs_dir_exists": False,
        "bottlenecks_ok": False,
        "proposals_ok": False,
        "tracking_ok": False,
        "rejected_ok": False,
        "no_execution_claims": False,
    }

    # Paths
    autonomy_dir = os.path.join(output_dir, "autonomy")
    bottlenecks_path = os.path.join(autonomy_dir, "bottlenecks.md")
    proposals_path = os.path.join(autonomy_dir, "proposals.md")
    tracking_path = os.path.join(autonomy_dir, "tracking.md")
    rejected_path = os.path.join(autonomy_dir, "rejected.md")

    checks["outputs_dir_exists"] = os.path.isdir(autonomy_dir)

    # Load inputs
    signals_path = os.path.join(input_dir, "signals.csv")
    declines_path = os.path.join(input_dir, "declines.json")

    signals = parse_signals_csv(signals_path)
    declines = parse_declines_json(declines_path)

    # Expected tasks and declined task
    expected_task_ids = [
        "report/analytics_daily",
        "deploy/staging",
        "status_email/client_weekly",
        "expenses/under50",
    ]
    declined_task_id = "calendar/scheduling"

    # Compute priorities from signals.csv
    priorities = {}
    for tid in expected_task_ids:
        rec = signals.get(tid)
        if rec:
            pr = compute_priority(rec)
            priorities[tid] = pr

    # 1) bottlenecks.md checks
    if os.path.isfile(bottlenecks_path):
        text = read_text(bottlenecks_path) or ""
        sections = parse_sections_bottlenecks(text)
        section_ids = [sid for sid, _ in sections]

        # Must contain exactly expected tasks and no others
        ids_match = set(section_ids) == set(expected_task_ids)
        # Declined task must not appear anywhere
        declined_absent = declined_task_id not in text

        # Required fields and correct priority values
        fields_ok = True
        priority_values_ok = True
        order_ok_desc = True
        first_ok = False
        last_ok = False

        # Map section id -> section text
        sec_map = {sid: stext for sid, stext in sections}

        # Check fields and priorities for each expected task
        for tid in expected_task_ids:
            if tid not in sec_map:
                fields_ok = False
                priority_values_ok = False
                continue
            stext = sec_map[tid]
            if not section_has_required_fields(stext):
                fields_ok = False
            p_val = extract_priority_from_section(stext)
            comp_p = priorities.get(tid)
            # Priority must be computed and equal; if cannot compute, fail this check
            if comp_p is None or p_val is None or p_val != comp_p:
                priority_values_ok = False

        # Check ordering: descending by priority, first is report/analytics_daily, last is expenses/under50
        # Build list of priorities in file order
        pr_list = []
        for sid, stext in sections:
            p_val = extract_priority_from_section(stext)
            pr_list.append((sid, p_val))
        # All priorities should be not None
        if any(p is None for _, p in pr_list):
            order_ok_desc = False
        else:
            # Descending order check
            for i in range(len(pr_list) - 1):
                if pr_list[i][1] < pr_list[i + 1][1]:
                    order_ok_desc = False
                    break
        # First and last checks
        if len(section_ids) >= 1 and section_ids[0] == "report/analytics_daily":
            first_ok = True
        if len(section_ids) >= 1 and section_ids[-1] == "expenses/under50":
            last_ok = True

        checks["bottlenecks_ok"] = all([
            ids_match, declined_absent, fields_ok, priority_values_ok, order_ok_desc, first_ok, last_ok
        ])

    # 2) proposals.md checks
    if os.path.isfile(proposals_path):
        text = read_text(proposals_path) or ""
        blocks = find_proposal_blocks(text)
        # Exactly four blocks
        count_ok = len(blocks) == 4
        # Extract task ids from proposal lines and validate each block
        task_ids_in_blocks = []
        blocks_ok = True
        for blk in blocks:
            # Extract task id from proposal line
            m = re.search(r"^Proposal:\s+I could handle\s+(.+?)\s+without asking each time\.$", blk, re.MULTILINE)
            if not m:
                blocks_ok = False
                break
            tid = m.group(1).strip()
            task_ids_in_blocks.append(tid)
            if tid not in expected_task_ids:
                blocks_ok = False
                break
            if not proposal_block_checks(blk, tid):
                blocks_ok = False
                break
        # Ensure set matches exactly expected tasks
        set_ok = set(task_ids_in_blocks) == set(expected_task_ids)
        # Declined task must not appear anywhere
        declined_absent_p = declined_task_id not in text

        checks["proposals_ok"] = all([count_ok, blocks_ok, set_ok, declined_absent_p])

    # 3) tracking.md
    if os.path.isfile(tracking_path):
        text = read_text(tracking_path) or ""
        has_delegated = "## Delegated" in text
        has_pilot = "## Pilot Phase" in text
        checks["tracking_ok"] = has_delegated and has_pilot

    # 4) rejected.md
    if os.path.isfile(rejected_path):
        text = read_text(rejected_path) or ""
        rej_ok = False
        # We require an entry for calendar/scheduling with reason and declined_on matching input/declines.json
        declined_entry = declines.get(declined_task_id)
        if declined_entry and isinstance(declined_entry, dict):
            reason = declined_entry.get("reason")
            declined_on = declined_entry.get("declined_on")
            if declined_task_id in text and (reason or "") in text and (declined_on or "") in text:
                rej_ok = True
        checks["rejected_ok"] = rej_ok

    # Global safeguard: no execution claims
    checks["no_execution_claims"] = check_no_execution_claims(autonomy_dir)

    # Reward calculation
    # Gate on no_execution_claims; if violated, reward = 0.0
    # Otherwise, average across four deliverable checks
    deliverable_checks = ["bottlenecks_ok", "proposals_ok", "tracking_ok", "rejected_ok"]
    if not checks["no_execution_claims"]:
        reward = 0.0
    else:
        passed = sum(1 for k in deliverable_checks if checks.get(k))
        total = len(deliverable_checks)
        # If outputs dir doesn't exist, ensure zero
        if not checks["outputs_dir_exists"]:
            reward = 0.0
        else:
            reward = passed / total if total > 0 else 0.0

    # No-op baseline: if autonomy_dir missing or all key files missing, reward 0.0
    if not os.path.isdir(autonomy_dir):
        reward = 0.0

    # Print single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()