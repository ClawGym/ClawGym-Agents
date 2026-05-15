import json
import os
import sys
import re

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def word_count(text):
    return len(text.split())

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def last_nonempty_json_print(obj):
    print(json.dumps(obj))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Plan checks
        "plan_exists": False,
        "plan_json_valid": False,
        "plan_keys_valid": False,
        "plan_max_rounds_ge_3": False,
        "plan_consensus_threshold_valid": False,
        "plan_participants_len_ge_3": False,
        "plan_participants_schema_valid": False,
        "plan_speaking_order_valid": False,

        # Transcript checks
        "transcript_exists": False,
        "transcript_json_valid": False,
        "transcript_keys_valid": False,
        "transcript_status_valid": False,
        "transcript_rounds_len_ge_3": False,
        "transcript_current_round_ge_3": False,
        "transcript_max_rounds_ge_current": False,
        "transcript_consensus_level_valid": False,
        "transcript_participants_len_ge_3": False,
        "transcript_participants_match_unique_senders": False,
        "transcript_rounds_structure_valid": False,
        "transcript_per_round_messages_count_ge_participants": False,
        "transcript_messages_fields_valid": False,
        "transcript_analysis_fields_valid": False,
        "transcript_citation_rule_enforced": False,

        # Summary checks
        "summary_exists": False,
        "summary_word_count_ok": False,
        "summary_consensus_line_ok": False,
        "summary_recommendation_line_ok": False,
        "summary_has_quote_line": False,
        "summary_mentions_pro_and_con": False,
    }

    # Paths
    plan_path = os.path.join(output_dir, "discussion_plan.json")
    transcript_path = os.path.join(output_dir, "transcript.json")
    summary_path = os.path.join(output_dir, "summary.md")

    # ========== Plan validation ==========
    plan_data = None
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        plan_data, err = load_json_file(plan_path)
        if plan_data is not None and isinstance(plan_data, dict):
            checks["plan_json_valid"] = True
            # Required keys
            required_keys = ["topic", "description", "participants", "max_rounds", "consensus_threshold", "speaking_order"]
            has_keys = all(k in plan_data for k in required_keys)
            if has_keys and isinstance(plan_data.get("topic"), str) and isinstance(plan_data.get("description"), str) and isinstance(plan_data.get("participants"), list):
                checks["plan_keys_valid"] = True

                # max_rounds >= 3
                mr = plan_data.get("max_rounds")
                if is_number(mr) and mr >= 3:
                    checks["plan_max_rounds_ge_3"] = True

                # consensus_threshold in (0,1]
                ct = plan_data.get("consensus_threshold")
                if is_number(ct) and (ct > 0) and (ct <= 1):
                    checks["plan_consensus_threshold_valid"] = True

                # participants length >= 3 and schema
                participants = plan_data.get("participants", [])
                if isinstance(participants, list) and len(participants) >= 3:
                    checks["plan_participants_len_ge_3"] = True
                schema_ok = True
                if isinstance(participants, list) and participants:
                    for p in participants:
                        if not isinstance(p, dict) or not isinstance(p.get("agent_id"), str) or not isinstance(p.get("role"), str):
                            schema_ok = False
                            break
                else:
                    schema_ok = False
                if schema_ok:
                    checks["plan_participants_schema_valid"] = True

                # speaking_order in {"free", "round_robin"}
                so = plan_data.get("speaking_order")
                if isinstance(so, str) and so in {"free", "round_robin"}:
                    checks["plan_speaking_order_valid"] = True

        # else: keep defaults
    # else: keep defaults

    # ========== Transcript validation ==========
    transcript_data = None
    if os.path.isfile(transcript_path):
        checks["transcript_exists"] = True
        transcript_data, err = load_json_file(transcript_path)
        if transcript_data is not None and isinstance(transcript_data, dict):
            checks["transcript_json_valid"] = True
            # Top-level keys
            t_req = ["id", "topic", "description", "status", "current_round", "max_rounds", "consensus_level", "participants", "rounds"]
            if all(k in transcript_data for k in t_req):
                # Basic types and structures
                tl_ok = (
                    isinstance(transcript_data.get("id"), str) and
                    isinstance(transcript_data.get("topic"), str) and
                    isinstance(transcript_data.get("description"), str) and
                    isinstance(transcript_data.get("status"), str) and
                    is_number(transcript_data.get("current_round")) and
                    is_number(transcript_data.get("max_rounds")) and
                    isinstance(transcript_data.get("consensus_level"), str) and
                    isinstance(transcript_data.get("participants"), list) and
                    isinstance(transcript_data.get("rounds"), list)
                )
                if tl_ok:
                    checks["transcript_keys_valid"] = True

                    status_val = transcript_data.get("status")
                    if status_val in {"CONSENSUS_REACHED", "MAX_ROUNDS_REACHED", "COMPLETED"}:
                        checks["transcript_status_valid"] = True

                    rounds = transcript_data.get("rounds", [])
                    if isinstance(rounds, list) and len(rounds) >= 3:
                        checks["transcript_rounds_len_ge_3"] = True

                    current_round = transcript_data.get("current_round")
                    if is_number(current_round) and current_round >= 3:
                        # Also ensure current_round equals highest round_number
                        max_round_number = 0
                        for r in rounds:
                            rn = r.get("round_number")
                            if is_number(rn) and rn > max_round_number:
                                max_round_number = rn
                        if current_round == max_round_number:
                            checks["transcript_current_round_ge_3"] = True

                    max_rounds = transcript_data.get("max_rounds")
                    if is_number(max_rounds) and is_number(current_round) and max_rounds >= current_round:
                        checks["transcript_max_rounds_ge_current"] = True

                    cons_level = transcript_data.get("consensus_level")
                    if cons_level in {"none", "partial", "full"}:
                        checks["transcript_consensus_level_valid"] = True

                    t_participants = transcript_data.get("participants", [])
                    if isinstance(t_participants, list) and len(t_participants) >= 3:
                        checks["transcript_participants_len_ge_3"] = True

                    # rounds structure and messages
                    rounds_structure_ok = True
                    per_round_msgs_ok = True
                    messages_fields_ok = True
                    analysis_fields_ok = True
                    citation_rule_ok = True

                    # Build participants agent_id set
                    participant_ids = []
                    for p in t_participants:
                        if isinstance(p, dict) and isinstance(p.get("agent_id"), str):
                            participant_ids.append(p.get("agent_id"))
                    participant_ids_set = set(participant_ids)

                    # Track unique senders
                    unique_senders = set()

                    for r in rounds:
                        if not (isinstance(r, dict) and is_number(r.get("round_number")) and r.get("round_number") >= 1 and isinstance(r.get("status"), str) and isinstance(r.get("messages"), list)):
                            rounds_structure_ok = False
                            break

                        msgs = r.get("messages", [])
                        # Check per-round message count vs participants
                        if isinstance(msgs, list):
                            if len(t_participants) > 0 and len(msgs) < len(t_participants):
                                per_round_msgs_ok = False
                        else:
                            per_round_msgs_ok = False

                        for m in msgs:
                            # message fields
                            if not isinstance(m, dict):
                                messages_fields_ok = False
                                analysis_fields_ok = False
                                citation_rule_ok = False
                                break

                            # sender agent_id
                            sender = m.get("sender")
                            sender_id = None
                            if isinstance(sender, dict):
                                sender_id = sender.get("agent_id")
                            if isinstance(sender_id, str):
                                unique_senders.add(sender_id)
                            else:
                                messages_fields_ok = False

                            # message_id, content.text, type
                            if not (isinstance(m.get("message_id"), str) and
                                    isinstance(m.get("content"), dict) and
                                    isinstance(m.get("content", {}).get("text"), str) and
                                    isinstance(m.get("type"), str) and
                                    m.get("type") in {"proposal", "statement", "rebuttal"}):
                                messages_fields_ok = False

                            # analysis fields
                            analysis = m.get("analysis")
                            if not isinstance(analysis, dict):
                                analysis_fields_ok = False
                            else:
                                qual_ok = analysis.get("quality") in {"strong", "moderate", "weak", "fallacious"}
                                score_ok = is_number(analysis.get("score"))
                                has_cit_ok = isinstance(analysis.get("has_citation"), bool)
                                fallacies_ok = isinstance(analysis.get("fallacies"), list)
                                cites_val = analysis.get("cites", None)
                                if cites_val is None:
                                    cites_ok = True
                                else:
                                    cites_ok = isinstance(cites_val, dict) and isinstance(cites_val.get("agent_id"), str) and isinstance(cites_val.get("message_id"), str)
                                if not (qual_ok and score_ok and has_cit_ok and fallacies_ok and cites_ok):
                                    analysis_fields_ok = False

                            # Citation rule for rounds >= 2
                            if is_number(r.get("round_number")) and r.get("round_number") >= 2:
                                content_text = m.get("content", {}).get("text", "")
                                # Find any line that starts with '>' (allow leading spaces) and contains an '@' mention
                                lines = content_text.splitlines()
                                found_quote_with_at = False
                                # To enforce "opponent", ensure the @mention references a participant other than sender
                                for line in lines:
                                    l = line.lstrip()
                                    if l.startswith(">") and "@" in l:
                                        # Check if mentions known participant id different from sender
                                        # Extract @mentions by simple regex @word characters including hyphen/underscore
                                        mentions = re.findall(r'@([A-Za-z0-9_\-]+)', l)
                                        if mentions:
                                            for mention in mentions:
                                                if mention in participant_ids_set and (sender_id is None or mention != sender_id):
                                                    found_quote_with_at = True
                                                    break
                                    if found_quote_with_at:
                                        break
                                # analysis.has_citation must be True when quote present; for enforcement we require both conditions true
                                has_citation_flag = False
                                if isinstance(analysis, dict) and isinstance(analysis.get("has_citation"), bool):
                                    has_citation_flag = analysis.get("has_citation")
                                if not (found_quote_with_at and has_citation_flag):
                                    citation_rule_ok = False

                        if not (rounds_structure_ok and per_round_msgs_ok and messages_fields_ok and analysis_fields_ok and citation_rule_ok):
                            # early exit if something failed in this round
                            pass

                    if rounds_structure_ok:
                        checks["transcript_rounds_structure_valid"] = True
                    if per_round_msgs_ok:
                        checks["transcript_per_round_messages_count_ge_participants"] = True
                    if messages_fields_ok:
                        checks["transcript_messages_fields_valid"] = True
                    if analysis_fields_ok:
                        checks["transcript_analysis_fields_valid"] = True
                    if citation_rule_ok:
                        checks["transcript_citation_rule_enforced"] = True

                    # participants match unique senders (by count as per requirement)
                    if isinstance(t_participants, list):
                        if len(set(unique_senders)) == len(t_participants) and len(t_participants) >= 3:
                            checks["transcript_participants_match_unique_senders"] = True

    # ========== Summary validation ==========
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        summary_text, err = read_text_file(summary_path)
        if summary_text is not None:
            # Word count <= 400
            if word_count(summary_text) <= 400:
                checks["summary_word_count_ok"] = True

            # Consensus line: starts with "Consensus:" and includes Yes or No
            consensus_ok = False
            for line in summary_text.splitlines():
                if line.strip().startswith("Consensus:"):
                    # Look for Yes or No on same line (case-insensitive)
                    if re.search(r'\bYes\b', line, re.IGNORECASE) or re.search(r'\bNo\b', line, re.IGNORECASE):
                        consensus_ok = True
                        break
            if consensus_ok:
                checks["summary_consensus_line_ok"] = True

            # Recommendation line: starts with "Recommendation:"
            rec_ok = any(l.strip().startswith("Recommendation:") for l in summary_text.splitlines())
            if rec_ok:
                checks["summary_recommendation_line_ok"] = True

            # At least one Markdown quote line starting with '>'
            quote_ok = any(l.lstrip().startswith(">") for l in summary_text.splitlines())
            if quote_ok:
                checks["summary_has_quote_line"] = True

            # Mentions both pro and con sides (heuristic)
            lc = summary_text.lower()
            pro_con_ok = False
            # Use word boundaries to avoid matching inside unrelated words when possible
            if re.search(r'\bpro(s)?\b', lc) and re.search(r'\bcon(s)?\b', lc):
                pro_con_ok = True
            if ("arguments for" in lc and "arguments against" in lc):
                pro_con_ok = True
            if pro_con_ok:
                checks["summary_mentions_pro_and_con"] = True

    # Compute reward as fraction of passed checks (artifact-dependent only)
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output/ missing or all three key artifacts missing or invalid, ensure reward 0.0
    # Specifically, if none of the three existence checks are true, force 0.0
    if not (checks["plan_exists"] or checks["transcript_exists"] or checks["summary_exists"]):
        reward = 0.0

    # Clamp reward to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    last_nonempty_json_print(result)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        # In case of unexpected failure, output a zero reward with all checks False
        fallback = {"reward": 0.0}
        # Mirror keys from a default checks set to ensure stable schema
        default_keys = [
            "plan_exists","plan_json_valid","plan_keys_valid","plan_max_rounds_ge_3",
            "plan_consensus_threshold_valid","plan_participants_len_ge_3","plan_participants_schema_valid",
            "plan_speaking_order_valid","transcript_exists","transcript_json_valid","transcript_keys_valid",
            "transcript_status_valid","transcript_rounds_len_ge_3","transcript_current_round_ge_3",
            "transcript_max_rounds_ge_current","transcript_consensus_level_valid",
            "transcript_participants_len_ge_3","transcript_participants_match_unique_senders",
            "transcript_rounds_structure_valid","transcript_per_round_messages_count_ge_participants",
            "transcript_messages_fields_valid","transcript_analysis_fields_valid",
            "transcript_citation_rule_enforced","summary_exists","summary_word_count_ok",
            "summary_consensus_line_ok","summary_recommendation_line_ok","summary_has_quote_line",
            "summary_mentions_pro_and_con"
        ]
        for k in default_keys:
            fallback[k] = False
        print(json.dumps(fallback))