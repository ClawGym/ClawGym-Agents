import json
import os
import re
import sys

def count_chinese_chars(text: str) -> int:
    # Count characters in the CJK Unified Ideographs block \u4E00-\u9FFF
    return len(re.findall(r'[\u4E00-\u9FFF]', text))

def read_file(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    output_dir = os.path.join(workspace_root, "output")
    # Inputs aren't required for scoring; we only validate outputs.

    checks = {
        "has_summary_file": False,
        "valid_title": False,
        "required_sections_once": False,
        "section_order_correct": False,
        "sections_nonempty": False,
        "contains_acronyms": False,
        "contains_chinese_terms": False,
        "char_count_ge_200": False,
        "keywords_line_found": False,
        "keywords_count_ge_5": False,
        "has_metadata_file": False,
        "metadata_valid_json": False,
        "metadata_title_match": False,
        "metadata_keyword_count_match": False,
        "metadata_has_bioinfo_focus": False,
        "metadata_sections_true": False,
        "metadata_acronym_presence_true": False,
        "metadata_chinese_char_count_match": False,
    }

    summary_path = os.path.join(output_dir, "summary.zh.md")
    metadata_path = os.path.join(output_dir, "metadata.json")

    summary_text = ""
    lines = []
    title_text = ""
    required_sections = ["背景", "方法", "结果", "局限性", "数据处理流程", "生信要点", "关键词"]
    section_headers = [f"## {s}" for s in required_sections]
    section_positions = {}

    if os.path.isfile(summary_path):
        checks["has_summary_file"] = True
        summary_text = read_file(summary_path)
        lines = summary_text.splitlines()

        # Validate title: first line starts with "# "
        if len(lines) > 0 and lines[0].lstrip().startswith("# "):
            # Extract title by removing leading "# " from the very first line (strip only one level)
            first_line = lines[0].lstrip()
            title_text = first_line[2:].strip()
            if title_text:
                checks["valid_title"] = True

        # Find section headers and count occurrences
        occurrences = {h: [] for h in section_headers}
        for idx, line in enumerate(lines):
            stripped = line.strip()
            for h in section_headers:
                if stripped == h:
                    occurrences[h].append(idx)

        # Exactly once each
        if all(len(occurrences[h]) == 1 for h in section_headers):
            checks["required_sections_once"] = True
            # Record positions
            for h in section_headers:
                section_positions[h] = occurrences[h][0]

            # Check order: strictly increasing in the required order
            positions_list = [section_positions[h] for h in section_headers]
            if positions_list == sorted(positions_list):
                checks["section_order_correct"] = True

            # Check non-empty content for each section: at least one non-empty line before next section
            nonempty_all = True
            for i, h in enumerate(section_headers):
                start_idx = section_positions[h] + 1
                end_idx = len(lines) if i == len(section_headers) - 1 else section_positions[section_headers[i+1]]
                # Determine if there is any non-empty content
                has_content = False
                for j in range(start_idx, end_idx):
                    if lines[j].strip():
                        has_content = True
                        break
                if not has_content:
                    nonempty_all = False
                    break
            if nonempty_all:
                checks["sections_nonempty"] = True

            # Extract keywords line within next 3 lines after "## 关键词"
            kw_header_idx = section_positions["## 关键词"]
            candidate_lines = []
            for j in range(kw_header_idx + 1, min(len(lines), kw_header_idx + 4)):
                candidate_lines.append(lines[j].strip())

            keyword_line = None
            for cl in candidate_lines:
                if not cl:
                    continue
                if ("," in cl) or ("、" in cl):
                    keyword_line = cl
                    break
            if keyword_line is not None:
                checks["keywords_line_found"] = True
                # Normalize delimiters to comma, then split
                norm = keyword_line.replace("、", ",")
                items = [x.strip() for x in norm.split(",") if x.strip()]
                if len(items) >= 5:
                    checks["keywords_count_ge_5"] = True
                parsed_keyword_count = len(items)
            else:
                parsed_keyword_count = 0
        else:
            parsed_keyword_count = 0

        # Acronyms presence
        acronyms = ["TPM", "RPKM", "TMM", "DESeq"]
        if all(a in summary_text for a in acronyms):
            checks["contains_acronyms"] = True

        # Chinese terms presence: 批次效应 and 复现 or 复现性; and 单细胞 or scRNA
        has_batch = ("批次效应" in summary_text)
        has_repro = ("复现性" in summary_text) or ("复现" in summary_text)
        has_single_cell = ("单细胞" in summary_text) or ("scRNA" in summary_text)
        if has_batch and has_repro and has_single_cell:
            checks["contains_chinese_terms"] = True

        # Chinese char count >= 200
        chinese_count = count_chinese_chars(summary_text)
        if chinese_count >= 200:
            checks["char_count_ge_200"] = True
    else:
        parsed_keyword_count = 0
        chinese_count = 0

    # Validate metadata.json
    if os.path.isfile(metadata_path):
        checks["has_metadata_file"] = True
        metadata_text = read_file(metadata_path)
        try:
            metadata = json.loads(metadata_text)
            checks["metadata_valid_json"] = True

            # Title match
            if isinstance(metadata.get("title"), str) and title_text and metadata["title"] == title_text:
                checks["metadata_title_match"] = True

            # keyword_count match and >= 5
            kc = metadata.get("keyword_count")
            if isinstance(kc, int) and kc == parsed_keyword_count and kc >= 5:
                checks["metadata_keyword_count_match"] = True

            # has_bioinfo_focus must be true
            if metadata.get("has_bioinfo_focus") is True:
                checks["metadata_has_bioinfo_focus"] = True

            # sections object keys and values
            sections_obj = metadata.get("sections")
            required_section_keys = ["背景", "方法", "结果", "局限性", "数据处理流程", "生信要点", "关键词"]
            if isinstance(sections_obj, dict) and all(sections_obj.get(k) is True for k in required_section_keys):
                checks["metadata_sections_true"] = True

            # acronym_presence object
            acr_obj = metadata.get("acronym_presence")
            if isinstance(acr_obj, dict) and all(acr_obj.get(k) is True for k in ["TPM", "RPKM", "TMM", "DESeq"]):
                checks["metadata_acronym_presence_true"] = True

            # chinese_char_count match exactly
            m_cc = metadata.get("chinese_char_count")
            if isinstance(m_cc, int) and m_cc == chinese_count:
                checks["metadata_chinese_char_count_match"] = True

        except Exception:
            # metadata_valid_json remains False
            pass

    # Compute final reward: 1.0 only if all checks pass; else 0.0
    all_pass = all(checks.values())
    reward = 1.0 if all_pass else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()