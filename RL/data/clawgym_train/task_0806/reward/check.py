import json
import os
import sys
import re

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_plan_file": False,
        "plan_non_empty": False,
        "headings_order_correct": False,
        "cover_text_within_8": False,
        "xhs_title_within_20": False,
        "pinterest_title_within_100": False,
        "pinterest_desc_within_500": False,
        "oper_has_self_comment": False,
        "oper_replies_three": False,
        "oper_series_next_third": False,
        "oper_checklist_five": False,
        "char_count_section_present": False,
        "has_diagnosis_file": False,
        "diagnosis_bullets_1_to_3": False,
    }

    plan_path = os.path.join(output_dir, "plan.md")
    diagnosis_path = os.path.join(output_dir, "diagnosis.md")

    plan_text = ""
    plan_lines = []

    if os.path.isfile(plan_path):
        checks["has_plan_file"] = True
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                plan_text = f.read()
            if plan_text.strip():
                checks["plan_non_empty"] = True
                plan_lines = plan_text.splitlines()
        except Exception:
            # keep as False if reading fails
            pass

    # Only proceed if plan file is present and non-empty
    if checks["plan_non_empty"]:
        # Expected headings in exact order
        # Build headings with Unicode escapes (ASCII-only source)
        h1 = "## " + "\U0001F4F8" + " " + "\u89c6\u89c9\u65b9\u6848"  # ## 📸 视觉方案
        h2 = "## " + "\u270D" + "\uFE0F" + " " + "\u5c0f\u7ea2\u4e66\u6587\u6848"  # ## ✍️ 小红书文案
        h3 = "## " + "\U0001F4CC" + " Pinterest Copy"  # ## 📌 Pinterest Copy
        h4 = "## " + "\U0001F3AF" + " " + "\u8fd0\u8425\u52a8\u4f5c"  # ## 🎯 运营动作
        h5 = "## Character Count Verification"

        expected_headings = [h1, h2, h3, h4, h5]

        # Collect all headings lines that start with "## "
        headings_in_doc = [ln.strip() for ln in plan_lines if ln.strip().startswith("## ")]
        # Determine the index of each expected heading in the document
        idxs = []
        order_ok = True
        for eh in expected_headings:
            try:
                idx = headings_in_doc.index(eh)
                idxs.append(idx)
            except ValueError:
                order_ok = False
                break
        # Check strictly increasing order
        if order_ok and all(earlier < later for earlier, later in zip(idxs, idxs[1:])):
            checks["headings_order_correct"] = True

        # Independent presence check for Character Count Verification
        checks["char_count_section_present"] = (h5 in headings_in_doc)

        # Helper to get section text by heading
        def get_section_text(start_heading):
            if start_heading not in headings_in_doc:
                return ""
            start_idx = headings_in_doc.index(start_heading)
            # Map to absolute line index in plan_lines
            # Need to find the nth heading occurrence in plan_lines
            def find_heading_line_index(target_heading, occurrence_index):
                count = -1
                for i, ln in enumerate(plan_lines):
                    if ln.strip().startswith("## "):
                        if ln.strip() == target_heading:
                            count += 1
                            if count == occurrence_index:
                                return i
                return -1

            # Determine occurrence index of this heading among duplicate same text (rare, assume 0)
            # We'll find the first occurrence
            start_line_idx = -1
            occ = 0
            # Locate first occurrence
            for i, ln in enumerate(plan_lines):
                if ln.strip() == start_heading:
                    start_line_idx = i
                    break
            if start_line_idx == -1:
                return ""

            # Find next heading after start_line_idx
            end_line_idx = len(plan_lines)
            for j in range(start_line_idx + 1, len(plan_lines)):
                if plan_lines[j].strip().startswith("## "):
                    end_line_idx = j
                    break
            return "\n".join(plan_lines[start_line_idx:end_line_idx])

        # Section: 视觉方案
        visual_sec = get_section_text(h1)
        if visual_sec:
            # Find line starting with "**封面文字**:"
            # label is Chinese with escapes: 封面文字
            cover_label = "**" + "\u5c01\u9762\u6587\u5b57" + "**:"
            cover_line = None
            for ln in visual_sec.splitlines():
                if ln.strip().startswith(cover_label):
                    cover_line = ln.strip()
                    break
            if cover_line and "\"" in cover_line:
                # Extract first quoted value
                first_quote = cover_line.find('"')
                second_quote = cover_line.find('"', first_quote + 1)
                if first_quote != -1 and second_quote != -1 and second_quote > first_quote + 1:
                    cover_text_val = cover_line[first_quote + 1:second_quote]
                    # Unicode length between 1 and 8 inclusive
                    if 1 <= len(cover_text_val) <= 8:
                        checks["cover_text_within_8"] = True

        # Section: 小红书文案
        xhs_sec = get_section_text(h2)
        if xhs_sec:
            title_label = "**" + "\u6807\u9898" + "**:"
            xhs_title = None
            for ln in xhs_sec.splitlines():
                s = ln.strip()
                if s.startswith(title_label):
                    val = s[len(title_label):].strip()
                    # Remove surrounding brackets or quotes if present
                    if (val.startswith("[") and val.endswith("]")) or (val.startswith("“") and val.endswith("”")):
                        val = val[1:-1].strip()
                    # Remove surrounding ASCII quotes if any
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1].strip()
                    xhs_title = val
                    break
            if xhs_title is not None:
                if len(xhs_title) <= 20 and len(xhs_title) > 0:
                    checks["xhs_title_within_20"] = True

        # Section: Pinterest Copy
        pin_sec = get_section_text(h3)
        if pin_sec:
            pin_title = None
            pin_desc = None
            for ln in pin_sec.splitlines():
                s = ln.strip()
                if s.startswith("**Title**:"):
                    val = s[len("**Title**:"):].strip()
                    pin_title = val
                elif s.startswith("**Description**:"):
                    val = s[len("**Description**:"):].strip()
                    pin_desc = val
            if pin_title is not None and len(pin_title) <= 100 and len(pin_title) > 0:
                checks["pinterest_title_within_100"] = True
            if pin_desc is not None and len(pin_desc) <= 500 and len(pin_desc) > 0:
                checks["pinterest_desc_within_500"] = True

        # Section: 运营动作
        ops_sec = get_section_text(h4)
        if ops_sec:
            self_comment_label = "**" + "\u9996\u6761\u81ea\u8bc4" + "**:"
            replies_label = "**" + "\u56de\u590d\u6a21\u677f" + "**"
            series_label = "**" + "\u7cfb\u5217\u89c4\u5212" + "**"
            checklist_label = "**" + "\u771f\u4eba\u611f\u68c0\u67e5\u6e05\u5355" + "**"

            # Self comment presence
            for ln in ops_sec.splitlines():
                if ln.strip().startswith(self_comment_label):
                    checks["oper_has_self_comment"] = True
                    break

            # Replies block has at least "1.", "2.", "3."
            has_replies_block = replies_label in ops_sec
            if has_replies_block:
                has_1 = any(l.strip().startswith("1.") for l in ops_sec.splitlines())
                has_2 = any(l.strip().startswith("2.") for l in ops_sec.splitlines())
                has_3 = any(l.strip().startswith("3.") for l in ops_sec.splitlines())
                if has_1 and has_2 and has_3:
                    checks["oper_replies_three"] = True

            # Series planning with "- 下一篇:" and "- 第三篇:"
            has_series_block = series_label in ops_sec
            next_line_prefix = "- " + "\u4e0b\u4e00\u7bc7" + ":"
            third_line_prefix = "- " + "\u7b2c\u4e09\u7bc7" + ":"
            has_next = any(l.strip().startswith(next_line_prefix) for l in ops_sec.splitlines())
            has_third = any(l.strip().startswith(third_line_prefix) for l in ops_sec.splitlines())
            if has_series_block and has_next and has_third:
                checks["oper_series_next_third"] = True

            # Checklist with at least 5 "- [ ]" lines
            has_checklist_block = checklist_label in ops_sec
            checklist_count = sum(1 for l in ops_sec.splitlines() if l.strip().startswith("- [ ]"))
            if has_checklist_block and checklist_count >= 5:
                checks["oper_checklist_five"] = True

    # Diagnosis file checks
    if os.path.isfile(diagnosis_path):
        checks["has_diagnosis_file"] = True
        try:
            with open(diagnosis_path, "r", encoding="utf-8") as f:
                dx_text = f.read()
            lines = [ln for ln in dx_text.splitlines()]
            bullet_lines = [ln for ln in lines if ln.strip().startswith("- ")]
            if 1 <= len(bullet_lines) <= 3:
                checks["diagnosis_bullets_1_to_3"] = True
        except Exception:
            pass

    # Compute reward as average of boolean checks (excluding reward field)
    bool_values = [v for k, v in checks.items()]
    total = len(bool_values)
    true_count = sum(1 for v in bool_values if v)
    reward = (true_count / total) if total > 0 else 0.0

    # No-op baseline: if no output files exist or plan missing/non-empty fails, reward must be 0.0
    if not checks["plan_non_empty"]:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()