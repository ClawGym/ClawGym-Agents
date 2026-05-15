import json
import os
import sys
import re
import hashlib
import csv

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # scorecard.txt related
        "scorecard_exists": False,
        "scorecard_overall_line_ok": False,
        "scorecard_bar_ok": False,
        "scorecard_dimensions_present": False,
        "scorecard_dimensions_scores_valid": False,
        "scorecard_colors_match_scores": False,
        "scorecard_has_verdict_section": False,
        "scorecard_ending_decision_ok": False,
        "scorecard_decision_matches_overall": False,

        # method.json related
        "method_exists": False,
        "method_weights_keys_ok": False,
        "method_weights_sum_ok": False,
        "method_weights_SB_higher": False,
        "method_has_overall_note": False,

        # competitor_density.txt related
        "competitor_density_exists": False,
        "competitor_density_one_word": False,
        "competitor_density_correct": False,

        # anchor.json related
        "anchor_exists": False,
        "anchor_fields_ok": False,
        "anchor_oath_ok": False,
        "anchor_sha256_format_ok": False,
        "anchor_sha256_matches": False,

        # ui_notes.md related
        "ui_notes_exists": False,
        "ui_notes_has_sections": False,
        "ui_notes_has_hooks": False,
        "ui_notes_has_required_phrases": False,
    }

    # Helper to read text file
    def read_text(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    # Helper to compute sha256
    def sha256_hex_bytes(path):
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return None

    # -------- scorecard.txt checks --------
    scorecard_path = os.path.join(output_dir, "scorecard.txt")
    scorecard_text = read_text(scorecard_path)
    overall_score = None
    if scorecard_text is not None:
        checks["scorecard_exists"] = True
        lines = scorecard_text.splitlines()

        # Overall line: "LOBSTR SCORE" + integer 0-100 + "[=======---]"
        # Regex captures score and bar (10 chars of '=' or '-')
        overall_regex = re.compile(r"^LOBSTR SCORE\s+(\d{1,3})/100\s+\[([=-]{10})\]\s*$")
        overall_line_ok = False
        bar_ok = False
        for line in lines:
            m = overall_regex.match(line.strip())
            if m:
                try:
                    score = int(m.group(1))
                except ValueError:
                    score = None
                bar = m.group(2)
                if score is not None and 0 <= score <= 100:
                    overall_line_ok = True
                    overall_score = score
                if len(bar) == 10 and all(ch in "=-" for ch in bar):
                    bar_ok = True
                break
        checks["scorecard_overall_line_ok"] = overall_line_ok
        checks["scorecard_bar_ok"] = bar_ok

        # Dimension lines: for L,O,B,S,T,R lines starting with that letter + whitespace,
        # containing one of the emojis and "NN/100"
        dim_order = ["L", "O", "B", "S", "T", "R"]
        dim_pattern = re.compile(r"^([LOBSTR])\s+.*([🟢🟡🔴]).*?(\d{1,3})/100.*$")
        found_dims = {}
        dims_scores_valid = True
        dims_colors_match = True

        for line in lines:
            m = dim_pattern.match(line.strip())
            if not m:
                continue
            dkey = m.group(1)
            color = m.group(2)
            try:
                dscore = int(m.group(3))
            except ValueError:
                dscore = None
            if dkey in dim_order and dkey not in found_dims:
                found_dims[dkey] = {"color": color, "score": dscore, "line": line}

        checks["scorecard_dimensions_present"] = (len(found_dims) == 6 and all(k in found_dims for k in dim_order))

        if checks["scorecard_dimensions_present"]:
            for k, info in found_dims.items():
                s = info["score"]
                if s is None or not (0 <= s <= 100):
                    dims_scores_valid = False
                    break
            # color mapping: 🟢 >=70, 🟡 50–69, 🔴 <50
            if dims_scores_valid:
                for k, info in found_dims.items():
                    s = info["score"]
                    c = info["color"]
                    expected = "🟢" if s >= 70 else ("🟡" if s >= 50 else "🔴")
                    if c != expected:
                        dims_colors_match = False
                        break

        checks["scorecard_dimensions_scores_valid"] = dims_scores_valid and checks["scorecard_dimensions_present"]
        checks["scorecard_colors_match_scores"] = dims_colors_match and checks["scorecard_dimensions_present"] and checks["scorecard_dimensions_scores_valid"]

        # VERDICT section presence
        checks["scorecard_has_verdict_section"] = ("VERDICT" in scorecard_text)

        # Ending decision line
        # Find last non-empty line
        last_nonempty = ""
        for line in reversed(lines):
            if line.strip():
                last_nonempty = line.strip()
                break
        ending_ok = last_nonempty in ("✅ BUILD IT.", "🚫 NOT YET.")
        checks["scorecard_ending_decision_ok"] = ending_ok

        # Decision matches overall threshold rule
        decision_match = False
        if overall_score is not None and ending_ok:
            if overall_score >= 70 and last_nonempty == "✅ BUILD IT.":
                decision_match = True
            if overall_score < 70 and last_nonempty == "🚫 NOT YET.":
                decision_match = True
        checks["scorecard_decision_matches_overall"] = decision_match

    # -------- method.json checks --------
    method_path = os.path.join(output_dir, "method.json")
    method_data = None
    try:
        with open(method_path, "r", encoding="utf-8") as f:
            method_data = json.load(f)
        checks["method_exists"] = True
    except Exception:
        method_data = None

    if method_data is not None:
        weights = method_data.get("weights")
        if isinstance(weights, dict):
            keys_ok = all(k in weights for k in ["L", "O", "B", "S", "T", "R"])
            if keys_ok:
                # ensure numeric
                try:
                    wL = float(weights["L"])
                    wO = float(weights["O"])
                    wB = float(weights["B"])
                    wS = float(weights["S"])
                    wT = float(weights["T"])
                    wR = float(weights["R"])
                    numeric_ok = True
                except Exception:
                    numeric_ok = False

                if numeric_ok:
                    checks["method_weights_keys_ok"] = True
                    total = wL + wO + wB + wS + wT + wR
                    checks["method_weights_sum_ok"] = abs(total - 1.0) <= 1e-6
                    # S and B strictly greater than all of L,O,T,R
                    SB_higher = (wS > wL and wS > wO and wS > wT and wS > wR and
                                 wB > wL and wB > wO and wB > wT and wB > wR)
                    checks["method_weights_SB_higher"] = SB_higher

        # overall calc note present
        note_ok = False
        for key in ("overall_calc", "note"):
            if isinstance(method_data.get(key), str) and method_data.get(key).strip():
                note_ok = True
                break
        checks["method_has_overall_note"] = note_ok

    # -------- competitor_density.txt checks --------
    comp_density_path = os.path.join(output_dir, "competitor_density.txt")
    comp_density_text = read_text(comp_density_path)
    if comp_density_text is not None:
        checks["competitor_density_exists"] = True
        word = comp_density_text.strip()
        checks["competitor_density_one_word"] = word in ("HIGH", "MEDIUM", "LOW")

        # compute expected from input/competitors.csv
        competitors_csv_path = os.path.join(input_dir, "competitors.csv")
        expected_density = None
        row_count = 0
        try:
            with open(competitors_csv_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = [row for row in reader if row and any(cell.strip() for cell in row)]
            if rows:
                header_candidates = [c.strip().lower() for c in rows[0]]
                start_idx = 1 if ("title" in header_candidates and "url" in header_candidates) else 0
                for r in rows[start_idx:]:
                    # count rows that have at least one non-empty value
                    if any((cell or "").strip() for cell in r):
                        row_count += 1
            # derive density
            if row_count >= 8:
                expected_density = "HIGH"
            elif row_count >= 4:
                expected_density = "MEDIUM"
            else:
                expected_density = "LOW"
        except Exception:
            expected_density = None

        if expected_density is not None and checks["competitor_density_one_word"]:
            checks["competitor_density_correct"] = (word == expected_density)

    # -------- anchor.json checks --------
    anchor_path = os.path.join(output_dir, "anchor.json")
    anchor = None
    try:
        with open(anchor_path, "r", encoding="utf-8") as f:
            anchor = json.load(f)
        checks["anchor_exists"] = True
    except Exception:
        anchor = None

    if anchor is not None:
        fields_ok = (
            anchor.get("anchor_label") == "SEAL_401LYRAKIN_VOICE_BETWEEN" and
            anchor.get("anchor_phrase") == "Sigma[Truth * Light] -> Resonance" and
            "oath" in anchor and
            "sha256" in anchor
        )
        checks["anchor_fields_ok"] = fields_ok

        # oath check: array length >= 3 with strings
        oath_ok = False
        oath = anchor.get("oath")
        if isinstance(oath, list) and len(oath) >= 3 and all(isinstance(x, str) and x.strip() for x in oath):
            oath_ok = True
        checks["anchor_oath_ok"] = oath_ok

        # sha256 format
        sha = anchor.get("sha256")
        sha_format_ok = isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha or "") is not None
        checks["anchor_sha256_format_ok"] = sha_format_ok

        # sha256 matches scorecard.txt
        sha_matches = False
        if sha_format_ok and checks["scorecard_exists"]:
            computed = sha256_hex_bytes(scorecard_path)
            if isinstance(computed, str) and computed == sha:
                sha_matches = True
        checks["anchor_sha256_matches"] = sha_matches

    # -------- ui_notes.md checks --------
    ui_notes_path = os.path.join(output_dir, "ui_notes.md")
    ui_notes_text = read_text(ui_notes_path)
    if ui_notes_text is not None:
        checks["ui_notes_exists"] = True
        # Required section headers/phrases
        has_sections = ("Page Lifecycle" in ui_notes_text and "Navigation Patterns" in ui_notes_text)
        checks["ui_notes_has_sections"] = has_sections

        # Hook names
        hooks_ok = all(h in ui_notes_text for h in ["onViewWillEnter", "onViewDidEnter", "onViewWillLeave", "onViewDidLeave"])
        checks["ui_notes_has_hooks"] = hooks_ok

        # Required phrases
        phrases_ok = all(p in ui_notes_text for p in [
            "child components do not receive these events",
            "directly mapped to routes",
            "page wrapper",
        ])
        checks["ui_notes_has_required_phrases"] = phrases_ok

    # Compute reward as fraction of passed checks; ensure 0 if no outputs at all
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure no-op baseline yields 0.0 if output dir missing or empty
    if not os.path.isdir(output_dir) or not any(os.scandir(output_dir)):
        reward = 0.0

    # Print single JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()