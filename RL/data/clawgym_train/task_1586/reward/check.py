import json
import os
import sys
from collections import OrderedDict

def workspace_paths(root):
    return (
        os.path.join(root, "input"),
        os.path.join(root, "output"),
        os.path.join(root, "reward"),
    )

def parse_time_to_ms(tstr):
    # Expect HH:MM:SS.mmm
    try:
        hms, ms = tstr.split(".")
        h, m, s = hms.split(":")
        h = int(h)
        m = int(m)
        s = int(s)
        ms = int(ms.ljust(3, "0")[:3])  # normalize to 3 digits
        return ((h * 60 + m) * 60 + s) * 1000 + ms
    except Exception:
        return None

def diff_ms(start_str, end_str):
    start = parse_time_to_ms(start_str)
    end = parse_time_to_ms(end_str)
    if start is None or end is None:
        return None
    diff = end - start
    if diff < 0:
        diff += 24 * 60 * 60 * 1000  # handle crossing midnight
    return diff

def format_duration(ms):
    if ms is None:
        return None
    if ms < 1000:
        return f"{int(round(ms))}ms"
    elif ms < 60000:
        return f"{ms/1000.0:.2f}s"
    else:
        return f"{ms/60000.0:.2f}min"

def read_text_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            # Preserve lines without trailing newlines explicitly
            content = f.read().splitlines()
        return content
    except Exception:
        return None

def last_non_empty_line(lines):
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() != "":
            return lines[i]
    return ""

def normalize_spaces(s):
    return " ".join(s.strip().split())

def load_input_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir, output_dir, reward_dir = workspace_paths(workspace_root)

    checks = OrderedDict()

    # Read input scenarios
    input_path = os.path.join(input_dir, "ping_scenarios.json")
    scenarios, input_ok = load_input_json(input_path)
    # This check is reported but not scored positively
    checks["input_loaded"] = bool(input_ok and isinstance(scenarios, dict))

    # Prepare expected values
    single_expected = {}
    compare_expected = []

    if checks["input_loaded"]:
        # Singles
        for item in scenarios.get("single", []):
            model = item.get("model")
            sent = item.get("sent")
            received = item.get("received")
            if not (model and sent and received):
                continue
            d_ms = diff_ms(sent, received)
            formatted = format_duration(d_ms)
            single_expected[model] = {
                "sent": sent,
                "received": received,
                "duration": formatted,
                "diff_ms": d_ms,
                "file": os.path.join(output_dir, "pings", f"{model}.txt"),
            }

        # Compare
        comp_models = scenarios.get("compare", {}).get("models", [])
        for item in comp_models:
            model = item.get("model")
            sent = item.get("sent")
            received = item.get("received")
            if not (model and sent and received):
                continue
            d_ms = diff_ms(sent, received)
            formatted = format_duration(d_ms)
            compare_expected.append({
                "model": model,
                "diff_ms": d_ms,
                "duration": formatted,
            })

    # Define files to validate
    # Singles: kimi, minimax, gemini (as per task specification)
    required_models = ["kimi", "minimax", "gemini"]
    for model in required_models:
        # Initialize checks to False
        checks[f"{model}_file_exists"] = False
        checks[f"{model}_header_correct"] = False
        checks[f"{model}_blank_lines_positions"] = False
        checks[f"{model}_timestamps_match"] = False
        checks[f"{model}_latency_correct"] = False
        checks[f"{model}_final_pong"] = False

    # Comparison checks
    compare_file = os.path.join(output_dir, "comparison", "compare_all.txt")
    checks["compare_file_exists"] = False
    checks["compare_header_topbar"] = False
    checks["compare_header_label"] = False
    checks["compare_header_bottombar"] = False
    checks["compare_blank_after_header"] = False
    checks["compare_rankings_correct"] = False
    checks["compare_fastest_line"] = False
    checks["compare_no_extra_nonempty_lines"] = False

    # Validate singles
    for model in required_models:
        exp = single_expected.get(model)
        if not exp:
            # If input not loaded or missing scenario, cannot validate; leave checks as False
            continue
        fpath = exp["file"]
        if os.path.isfile(fpath):
            checks[f"{model}_file_exists"] = True
            lines = read_text_lines(fpath)
            if lines is None:
                continue

            # Enforce exactly 7 lines with blanks at positions 2 and 6 (1-indexed: 2 and 6; zero-indexed: 1 and 5)
            if len(lines) == 7 and lines[1].strip() == "" and lines[5].strip() == "":
                checks[f"{model}_blank_lines_positions"] = True

            # Header exact match
            header = f"🧪 PING {model}"
            if len(lines) >= 1 and lines[0] == header:
                checks[f"{model}_header_correct"] = True

            # Timestamps
            sent_ok = False
            recv_ok = False
            if len(lines) >= 4:
                sent_line = lines[2]
                recv_line = lines[3]
                if sent_line.startswith("📤 Sent:"):
                    # Extract text after colon
                    try:
                        sent_value = sent_line.split("Sent:")[1].strip()
                        # Allow any number of spaces; exact time must match
                        if sent_value == exp["sent"]:
                            sent_ok = True
                        else:
                            sent_ok = False
                    except Exception:
                        sent_ok = False
                if recv_line.startswith("📥 Received:"):
                    try:
                        recv_value = recv_line.split("Received:")[1].strip()
                        if recv_value == exp["received"]:
                            recv_ok = True
                        else:
                            recv_ok = False
                    except Exception:
                        recv_ok = False
            if sent_ok and recv_ok:
                checks[f"{model}_timestamps_match"] = True

            # Latency line
            if len(lines) >= 5 and lines[4].startswith("⏱️  Latency:"):
                try:
                    latency_value = lines[4].split("Latency:")[1].strip()
                    if latency_value == exp["duration"]:
                        checks[f"{model}_latency_correct"] = True
                except Exception:
                    pass

            # Final Pong
            if last_non_empty_line(lines) == "🎯 Pong!":
                checks[f"{model}_final_pong"] = True

    # Validate comparison
    if os.path.isfile(compare_file):
        checks["compare_file_exists"] = True
        comp_lines = read_text_lines(compare_file) or []

        # Header bars and label
        topbar = "═" * 50
        if len(comp_lines) >= 3:
            if comp_lines[0] == topbar:
                checks["compare_header_topbar"] = True
            if comp_lines[1].strip() == "🧪 MODEL COMPARISON":
                checks["compare_header_label"] = True
            if comp_lines[2] == topbar:
                checks["compare_header_bottombar"] = True
        if len(comp_lines) >= 4 and comp_lines[3].strip() == "":
            checks["compare_blank_after_header"] = True

        # Rankings and fastest line
        # Build expected order by ascending diff_ms
        if compare_expected:
            sorted_expected = sorted(compare_expected, key=lambda x: x["diff_ms"])
            # Medal order expected
            medals_expected = ["🥇", "🥈", "🥉", "4️⃣"]
            # Ranking lines expected at positions 4..7
            rankings_ok = False
            if len(comp_lines) >= 8:
                rankings_ok = True
                for idx in range(4, 8):
                    line = comp_lines[idx]
                    norm = normalize_spaces(line)
                    parts = norm.split(" ")
                    if len(parts) < 3:
                        rankings_ok = False
                        break
                    medal = parts[0]
                    duration = parts[-1]
                    model = " ".join(parts[1:-1]).strip()

                    expected_medal = medals_expected[idx - 4]
                    expected_model = sorted_expected[idx - 4]["model"]
                    expected_duration = sorted_expected[idx - 4]["duration"]

                    if medal != expected_medal or model != expected_model or duration != expected_duration:
                        rankings_ok = False
                        break
            if rankings_ok:
                checks["compare_rankings_correct"] = True

            # Fastest line
            # Expect a line after the four rankings that starts with 🏆 Fastest: and includes "{fastest} ({duration})"
            fastest_line_idx = 8
            if len(comp_lines) > fastest_line_idx:
                fl = comp_lines[fastest_line_idx].lstrip()
                fastest_expected_model = sorted_expected[0]["model"]
                fastest_expected_duration = sorted_expected[0]["duration"]
                if fl.startswith("🏆 Fastest:") and (f"{fastest_expected_model} ({fastest_expected_duration})" in fl):
                    checks["compare_fastest_line"] = True

                # Ensure no additional non-empty lines beyond fastest line
                extra_nonempty = False
                for rest in comp_lines[fastest_line_idx + 1:]:
                    if rest.strip() != "":
                        extra_nonempty = True
                        break
                checks["compare_no_extra_nonempty_lines"] = not extra_nonempty

    # Compute reward as proportion of passed checks that depend on output/
    scoring_keys = []
    # Singles
    for model in required_models:
        scoring_keys.extend([
            f"{model}_file_exists",
            f"{model}_header_correct",
            f"{model}_blank_lines_positions",
            f"{model}_timestamps_match",
            f"{model}_latency_correct",
            f"{model}_final_pong",
        ])
    # Comparison
    scoring_keys.extend([
        "compare_file_exists",
        "compare_header_topbar",
        "compare_header_label",
        "compare_header_bottombar",
        "compare_blank_after_header",
        "compare_rankings_correct",
        "compare_fastest_line",
        "compare_no_extra_nonempty_lines",
    ])

    total = len(scoring_keys)
    passed = sum(1 for k in scoring_keys if checks.get(k, False))
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if required files missing and nothing passes, reward must be 0.0
    # This is already satisfied by the ratio.

    output = OrderedDict()
    output["reward"] = round(reward, 6)
    # Append all checks
    for k, v in checks.items():
        output[k] = bool(v)

    print(json.dumps(output))

if __name__ == "__main__":
    main()