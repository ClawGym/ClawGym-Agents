import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def split_lines(text):
    return text.splitlines() if text is not None else []

def find_section_ranges(lines, headers):
    # Return dict header -> (start_idx_inclusive, end_idx_exclusive)
    indices = {}
    header_positions = []
    for i, line in enumerate(lines):
        if line.strip() in headers:
            header_positions.append((i, line.strip()))
    header_positions.sort()
    for idx, (i, header) in enumerate(header_positions):
        start = i + 1
        end = header_positions[idx + 1][0] if idx + 1 < len(header_positions) else len(lines)
        indices[header] = (start, end)
    return indices

def get_section_text(lines, section_range):
    if section_range is None:
        return []
    start, end = section_range
    return lines[start:end]

def match_label_line(lines, label):
    # Match lines like "**标签**: ..." or "标签: ..." with both ":" and "："
    pattern = re.compile(rf'^\s*(?:\*\*)?{re.escape(label)}(?:\*\*)?\s*[：:]\s*(.*)\s*$')
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if m:
            return i, m.group(1).strip()
    return None, None

def extract_block_after_label(lines, label, stop_labels):
    # Find label line, then collect subsequent lines until a stop label or next section header "## "
    start_idx, first_line_after = None, None
    pattern = re.compile(rf'^\s*(?:\*\*)?{re.escape(label)}(?:\*\*)?\s*[：:]\s*(.*)\s*$')
    stop_patterns = [re.compile(rf'^\s*(?:\*\*)?{re.escape(lab)}(?:\*\*)?\s*[：:]\s*') for lab in stop_labels]
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if m:
            start_idx = i
            first_line_after = m.group(1)
            break
    if start_idx is None:
        return None
    collected = [first_line_after] if first_line_after is not None else []
    for j in range(start_idx + 1, len(lines)):
        if lines[j].strip().startswith("## "):
            break
        stop = False
        for sp in stop_patterns:
            if sp.match(lines[j]):
                stop = True
                break
        if stop:
            break
        collected.append(lines[j])
    # Join with newlines, strip trailing whitespace
    return "\n".join(collected).strip()

def contains_cjk(s):
    if not s:
        return False
    return re.search(r'[\u4e00-\u9fff]', s) is not None

def contains_emoji(s):
    if not s:
        return False
    # Common emoji ranges + some symbols
    return re.search(r'[\U0001F300-\U0001FAFF\U00002600-\U000026FF\U00002700-\U000027BF]', s) is not None

def parse_time_hhmm(s):
    if not s:
        return None
    m = re.search(r'\b([01]?\d|2[0-3]):([0-5]\d)\b', s)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    return (hh, mm)

def parse_brand_colors_from_extend(md_text):
    if not md_text:
        return []
    lines = md_text.splitlines()
    # Find "brand_colors:" block
    colors = []
    in_block = False
    base_indent = None
    for line in lines:
        # Normalize tabs
        l = line.rstrip("\n")
        if not in_block:
            if re.match(r'^\s*brand_colors\s*:\s*$', l):
                in_block = True
                base_indent = len(re.match(r'^(\s*)', l).group(1))
                continue
        else:
            # Stop if new top-level key or end of list
            if re.match(r'^\s*[A-Za-z_]+\s*:', l) and len(re.match(r'^(\s*)', l).group(1)) <= base_indent:
                break
            m = re.match(r'^\s*-\s*["\']?(#[0-9A-Fa-f]{6})["\']?\s*$', l)
            if m:
                colors.append(m.group(1))
            else:
                # If it's blank or comment, skip; if it's not a list item and not blank, keep scanning but don't add
                pass
    return colors

def count_hashtags(tag_line):
    if not tag_line:
        return 0
    # tags beginning with #, not followed by space only
    tags = re.findall(r'(?:^|\s)#([^\s#]+)', tag_line)
    return len(tags)

def load_keywords(csv_text):
    if not csv_text:
        return []
    kws = []
    for line in csv_text.splitlines():
        # Split by comma, strip spaces, remove quotes
        parts = [p.strip().strip('"').strip("'") for p in line.split(",")]
        for p in parts:
            if p:
                kws.append(p)
    # Deduplicate while preserving order
    seen = set()
    res = []
    for k in kws:
        kl = k.strip()
        if kl and kl.lower() not in seen:
            seen.add(kl.lower())
            res.append(kl)
    return res

def count_keywords_in_text(keywords, text):
    if not keywords or not text:
        return 0, set()
    text_cf = text.casefold()
    matched = set()
    for kw in keywords:
        if not kw:
            continue
        if kw.casefold() in text_cf:
            matched.add(kw)
    return len(matched), matched

def first_n_contains_any_keyword(n, keywords, text):
    if not keywords or not text:
        return False
    snippet = text[:n]
    count, matched = count_keywords_in_text(keywords, snippet)
    return count >= 1

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "plan_exists": False,
        "diagnosis_exists": False,
        "headers_visual": False,
        "headers_xhs": False,
        "headers_pinterest": False,
        "headers_ops": False,
        "headers_char_table": False,
        "visual_scene_present": False,
        "visual_composition_present": False,
        "visual_palette_present": False,
        "visual_covertext_present": False,
        "visual_brand_colors_present": False,
        "visual_covertext_len_ok": False,
        "xhs_title_len_ok": False,
        "xhs_title_has_cjk": False,
        "xhs_body_len_ok": False,
        "xhs_body_has_cjk": False,
        "xhs_body_has_emoji": False,
        "xhs_tags_count_ok": False,
        "xhs_post_time_valid": False,
        "pinterest_title_len_ok": False,
        "pinterest_description_len_ok": False,
        "pinterest_keywords_count_ok": False,
        "pinterest_keywords_early_ok": False,
        "pinterest_no_cjk": False,
        "pinterest_board_present": False,
        "pinterest_post_time_valid": False,
        "ops_self_comment_present": False,
        "ops_reply_templates_three": False,
        "ops_series_two": False,
        "ops_checklist_three": False,
        "diagnosis_groups_count_ok": False,
        "diagnosis_groups_format_ok": False,
        "char_table_header_present": False,
    }

    # Paths
    plan_path = os.path.join(output_dir, "plan.md")
    diagnosis_path = os.path.join(output_dir, "diagnosis.md")
    extend_path = os.path.join(input_dir, "EXTEND.md")
    briefing_path = os.path.join(input_dir, "briefing.json")  # Might be used by the agent; we don't score it directly
    keywords_path = os.path.join(input_dir, "keywords.csv")

    plan_text = read_text(plan_path)
    diagnosis_text = read_text(diagnosis_path)
    extend_text = read_text(extend_path)
    keywords_text = read_text(keywords_path)

    brand_colors = parse_brand_colors_from_extend(extend_text or "")
    # We won't score reading inputs alone; brand color check will be applied within plan parsing.

    if plan_text is not None:
        checks["plan_exists"] = True

    if diagnosis_text is not None:
        checks["diagnosis_exists"] = True

    # If plan exists, parse sections and run validations
    if checks["plan_exists"]:
        lines = split_lines(plan_text)

        # Sections headers expected
        headers = [
            "## 📸 视觉方案",
            "## ✍️ 小红书文案",
            "## 📌 Pinterest Copy",
            "## 🎯 运营动作",
            "## Character Count Verification",
        ]
        section_ranges = find_section_ranges(lines, set(headers))

        checks["headers_visual"] = "## 📸 视觉方案" in section_ranges
        checks["headers_xhs"] = "## ✍️ 小红书文案" in section_ranges
        checks["headers_pinterest"] = "## 📌 Pinterest Copy" in section_ranges
        checks["headers_ops"] = "## 🎯 运营动作" in section_ranges
        checks["headers_char_table"] = "## Character Count Verification" in section_ranges

        # Visual section checks
        vis_lines = get_section_text(lines, section_ranges.get("## 📸 视觉方案"))
        if vis_lines:
            # 画面描述
            _, scene_val = match_label_line(vis_lines, "画面描述")
            checks["visual_scene_present"] = bool(scene_val and len(scene_val.strip()) > 0)
            # 构图
            _, comp_val = match_label_line(vis_lines, "构图")
            checks["visual_composition_present"] = bool(comp_val and len(comp_val.strip()) > 0)
            # 色调
            palette_idx, palette_val = match_label_line(vis_lines, "色调")
            checks["visual_palette_present"] = bool(palette_val and len(palette_val.strip()) > 0)
            # Verify brand colors presence in 色调 line
            if palette_val and brand_colors and len(brand_colors) == 3:
                b_ok = all((c in palette_val) for c in brand_colors)
                checks["visual_brand_colors_present"] = b_ok
            else:
                checks["visual_brand_colors_present"] = False
            # 封面文字
            cover_idx, cover_val = match_label_line(vis_lines, "封面文字")
            if cover_val is not None:
                checks["visual_covertext_present"] = True
                # extract text inside first pair of ASCII quotes
                m = re.search(r'"([^"]*)"', cover_val)
                if m:
                    inner = m.group(1)
                    checks["visual_covertext_len_ok"] = len(inner) <= 8
                else:
                    # If no quotes found, fail length check
                    checks["visual_covertext_len_ok"] = False

        # XHS section
        xhs_lines = get_section_text(lines, section_ranges.get("## ✍️ 小红书文案"))
        if xhs_lines:
            _, title_val = match_label_line(xhs_lines, "标题")
            if title_val is not None:
                title_val_stripped = title_val.strip()
                checks["xhs_title_len_ok"] = len(title_val_stripped) <= 20
                checks["xhs_title_has_cjk"] = contains_cjk(title_val_stripped)
            body_text = extract_block_after_label(xhs_lines, "正文", stop_labels=["标签", "发布时间"])
            if body_text is not None:
                checks["xhs_body_len_ok"] = len(body_text) <= 800
                checks["xhs_body_has_cjk"] = contains_cjk(body_text)
                checks["xhs_body_has_emoji"] = contains_emoji(body_text)
            _, tags_val = match_label_line(xhs_lines, "标签")
            if tags_val is not None:
                tag_count = count_hashtags(tags_val)
                checks["xhs_tags_count_ok"] = (5 <= tag_count <= 10)
            _, post_val = match_label_line(xhs_lines, "发布时间")
            if post_val is not None:
                tm = parse_time_hhmm(post_val)
                if tm is not None and tm[1] != 0:
                    # Also require reason string presence (look for "原因")
                    has_reason = ("原因" in post_val)
                    checks["xhs_post_time_valid"] = True and has_reason

        # Pinterest section
        pin_lines = get_section_text(lines, section_ranges.get("## 📌 Pinterest Copy"))
        if pin_lines:
            _, pin_title = match_label_line(pin_lines, "Title")
            if pin_title is not None:
                pin_title_str = pin_title.strip()
                checks["pinterest_title_len_ok"] = len(pin_title_str) <= 100
            pin_desc_text = extract_block_after_label(pin_lines, "Description", stop_labels=["Board", "Post Time"])
            if pin_desc_text is not None:
                checks["pinterest_description_len_ok"] = len(pin_desc_text) <= 500
            # No CJK in Title + Description
            combined_pin = ((pin_title or "") + "\n" + (pin_desc_text or "")).strip()
            if combined_pin:
                checks["pinterest_no_cjk"] = not contains_cjk(combined_pin)
            # Keywords
            kws = load_keywords(keywords_text or "")
            if pin_desc_text is not None and kws:
                matched_count, _ = count_keywords_in_text(kws, pin_desc_text)
                checks["pinterest_keywords_count_ok"] = matched_count >= 3
                checks["pinterest_keywords_early_ok"] = first_n_contains_any_keyword(40, kws, pin_desc_text)
            _, board_val = match_label_line(pin_lines, "Board")
            checks["pinterest_board_present"] = bool(board_val and len(board_val.strip()) > 0)
            _, post_time_val = match_label_line(pin_lines, "Post Time")
            if post_time_val is not None:
                tm2 = parse_time_hhmm(post_time_val)
                utc_ok = ("UTC" in post_time_val) or ("utc" in post_time_val.lower())
                if tm2 is not None and tm2[1] != 0 and utc_ok:
                    checks["pinterest_post_time_valid"] = True

        # Operations section
        ops_lines = get_section_text(lines, section_ranges.get("## 🎯 运营动作"))
        if ops_lines:
            _, self_comment_val = match_label_line(ops_lines, "首条自评")
            checks["ops_self_comment_present"] = bool(self_comment_val and len(self_comment_val.strip()) > 0)

            # 回复模板 block: count lines like "1. ...", "2. ..." after a line containing "回复模板"
            # Find index of 回复模板 line
            reply_idx = None
            for i, line in enumerate(ops_lines):
                if re.search(r'回复模板', line):
                    reply_idx = i
                    break
            if reply_idx is not None:
                cnt = 0
                for j in range(reply_idx + 1, len(ops_lines)):
                    l = ops_lines[j]
                    if l.strip().startswith("## "):
                        break
                    if re.match(r'^\s*\d+\.\s+', l):
                        cnt += 1
                checks["ops_reply_templates_three"] = cnt >= 3

            # 系列规划: count lines starting with "- "
            series_idx = None
            for i, line in enumerate(ops_lines):
                if re.search(r'系列规划', line):
                    series_idx = i
                    break
            if series_idx is not None:
                cnt_series = 0
                for j in range(series_idx + 1, len(ops_lines)):
                    l = ops_lines[j]
                    if l.strip().startswith("## "):
                        break
                    if re.match(r'^\s*-\s+', l):
                        cnt_series += 1
                checks["ops_series_two"] = cnt_series >= 2

            # 真人感检查清单: lines starting with "- [ ]"
            checklist_idx = None
            for i, line in enumerate(ops_lines):
                if re.search(r'真人感检查清单', line):
                    checklist_idx = i
                    break
            if checklist_idx is not None:
                cnt_chk = 0
                for j in range(checklist_idx + 1, len(ops_lines)):
                    l = ops_lines[j]
                    if l.strip().startswith("## "):
                        break
                    if re.match(r'^\s*-\s*\[\s*\]\s+', l):
                        cnt_chk += 1
                checks["ops_checklist_three"] = cnt_chk >= 3

        # Character Count Verification section - table header present
        ccv_lines = get_section_text(lines, section_ranges.get("## Character Count Verification"))
        if ccv_lines:
            header_present = False
            for l in ccv_lines:
                if ("Element" in l and "Limit" in l and "Actual" in l and "Pass" in l and "|" in l):
                    header_present = True
                    break
            checks["char_table_header_present"] = header_present

    # Diagnosis checks
    if checks["diagnosis_exists"]:
        dlines = split_lines(diagnosis_text)
        # Collect groups of 3 lines: Symptom:, Diagnosis:, Fix:
        i = 0
        groups = 0
        format_ok = True
        while i < len(dlines):
            line = dlines[i].strip()
            if line.startswith("Symptom:"):
                # Next lines
                if i + 2 < len(dlines):
                    d1 = dlines[i + 1].strip()
                    d2 = dlines[i + 2].strip()
                    if d1.startswith("Diagnosis:") and d2.startswith("Fix:"):
                        groups += 1
                        i += 3
                        # Skip optional blank line
                        while i < len(dlines) and dlines[i].strip() == "":
                            i += 1
                        continue
                    else:
                        format_ok = False
                        break
                else:
                    format_ok = False
                    break
            i += 1
        checks["diagnosis_groups_count_ok"] = (1 <= groups <= 3)
        checks["diagnosis_groups_format_ok"] = format_ok and (groups >= 1)

    # Compute reward
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    # No-op baseline: if output missing or required artifacts missing, reward 0.0 (this falls out naturally)
    if total > 0:
        reward = passed / total
    # Additionally, require both main files to exist for any positive reward
    if not (checks["plan_exists"] and checks["diagnosis_exists"]):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()