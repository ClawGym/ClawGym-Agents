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

def parse_simple_yaml_lines(lines):
    data = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Remove surrounding quotes if present
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        data[key] = val
    return data

def extract_frontmatter(md_text):
    if md_text is None:
        return None, None, None
    lines = md_text.splitlines()
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            start_idx = i
            break
    if start_idx is None:
        return None, None, None
    for j in range(start_idx + 1, len(lines)):
        if lines[j].strip() == "---":
            end_idx = j
            break
    if end_idx is None:
        return None, None, None
    fm_lines = lines[start_idx + 1:end_idx]
    body = "\n".join(lines[end_idx + 1:]) if end_idx + 1 < len(lines) else ""
    fm_dict = parse_simple_yaml_lines(fm_lines)
    fm_text = "\n".join(fm_lines)
    return fm_dict, fm_text, body

def contains_non_ascii(s):
    if s is None:
        return False
    return any(ord(ch) > 127 for ch in s)

def bool_to_float(b):
    return 1.0 if b else 0.0

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        # Config checks
        "config_exists": False,
        "config_values_ok": False,
        # Output files existence
        "translation_exists": False,
        "analysis_exists": False,
        "prompt_exists": False,
        # Frontmatter checks
        "translation_frontmatter_present": False,
        "translation_frontmatter_source_fields_ok": False,
        "translation_frontmatter_translated_fields_ok": False,
        # Code preservation
        "code_block_preserved": False,
        # Glossary checks
        "glossary_ai_agent": False,
        "glossary_guardrails": False,
        "glossary_rlhf": False,
        "glossary_flywheel": False,
        "glossary_transformer": False,
        "glossary_grounding": False,
        "glossary_alignment": False,
        "glossary_hallucination": False,
    }

    # Paths
    config_path = os.path.join(output_dir, ".baoyu-skills", "baoyu-translate", "EXTEND.md")
    trans_dir = os.path.join(output_dir, "article-zh-CN")
    translation_path = os.path.join(trans_dir, "translation.md")
    analysis_path = os.path.join(trans_dir, "01-analysis.md")
    prompt_path = os.path.join(trans_dir, "02-prompt.md")

    # 1) Config file check
    config_text = read_text(config_path)
    if config_text is not None and config_text.strip() != "":
        checks["config_exists"] = True
        # Simple YAML parse for key-values
        cfg_lines = config_text.splitlines()
        cfg = parse_simple_yaml_lines(cfg_lines)
        if (
            cfg.get("target_language") == "zh-CN" and
            cfg.get("default_mode") == "normal" and
            cfg.get("audience") == "general" and
            cfg.get("style") == "formal"
        ):
            checks["config_values_ok"] = True

    # 2) Required outputs exist and non-empty
    trans_text = read_text(translation_path)
    if trans_text is not None and trans_text.strip() != "":
        checks["translation_exists"] = True
    analysis_text = read_text(analysis_path)
    if analysis_text is not None and analysis_text.strip() != "":
        checks["analysis_exists"] = True
    prompt_text = read_text(prompt_path)
    if prompt_text is not None and prompt_text.strip() != "":
        checks["prompt_exists"] = True

    # For subsequent checks, require translation file existence
    input_article_path = os.path.join(input_dir, "article.md")
    input_article_text = read_text(input_article_path)

    # Parse input frontmatter to fetch original fields
    input_fm_dict, _, _ = extract_frontmatter(input_article_text) if input_article_text else (None, None, None)
    orig = {}
    if input_fm_dict:
        for k in ["title", "description", "author", "date", "url"]:
            v = input_fm_dict.get(k)
            if isinstance(v, str):
                orig[k] = v.strip()
            else:
                orig[k] = None

    if checks["translation_exists"]:
        # 3) Frontmatter transformation
        trans_fm_dict, _, trans_body = extract_frontmatter(trans_text)
        if trans_fm_dict is not None:
            checks["translation_frontmatter_present"] = True

            # Source fields exact match to original
            src_ok = True
            required_pairs = [
                ("sourceTitle", "title"),
                ("sourceDescription", "description"),
                ("sourceAuthor", "author"),
                ("sourceDate", "date"),
                ("sourceUrl", "url"),
            ]
            if not input_fm_dict:
                src_ok = False
            else:
                for new_key, old_key in required_pairs:
                    expected_val = orig.get(old_key)
                    got_val = None
                    if trans_fm_dict is not None:
                        got_raw = trans_fm_dict.get(new_key)
                        got_val = got_raw.strip() if isinstance(got_raw, str) else None
                    if expected_val is None or got_val is None or got_val != expected_val:
                        src_ok = False
                        break
            checks["translation_frontmatter_source_fields_ok"] = src_ok

            # Translated title and description: present, not identical, contains non-ASCII
            t_title = trans_fm_dict.get("title") if trans_fm_dict else None
            t_desc = trans_fm_dict.get("description") if trans_fm_dict else None
            trans_fields_ok = True
            # Validate title
            if not (isinstance(t_title, str) and t_title.strip() and (orig.get("title") is None or t_title.strip() != orig.get("title")) and contains_non_ascii(t_title)):
                trans_fields_ok = False
            # Validate description
            if not (isinstance(t_desc, str) and t_desc.strip() and (orig.get("description") is None or t_desc.strip() != orig.get("description")) and contains_non_ascii(t_desc)):
                trans_fields_ok = False
            checks["translation_frontmatter_translated_fields_ok"] = trans_fields_ok

        else:
            # If frontmatter missing, body is entire file
            trans_body = trans_text

        # 4) Markdown/code preservation in body
        if trans_body is not None:
            # Look for a line starting with ```python and presence of def respond(
            has_python_fence = False
            for ln in trans_body.splitlines():
                if ln.lstrip().startswith("```python"):
                    has_python_fence = True
                    break
            has_def = "def respond(" in trans_body
            if has_python_fence and has_def:
                checks["code_block_preserved"] = True

        # 5) Glossary application in body
        body_for_glossary = trans_body if trans_body is not None else ""
        if body_for_glossary:
            # AI Agent -> AI 智能体
            if "AI 智能体" in body_for_glossary:
                checks["glossary_ai_agent"] = True
            # guardrails -> 护栏
            if "护栏" in body_for_glossary:
                checks["glossary_guardrails"] = True
            # RLHF -> 基于人类反馈的强化学习
            if "基于人类反馈的强化学习" in body_for_glossary:
                checks["glossary_rlhf"] = True
            # flywheel -> 飞轮效应
            if "飞轮效应" in body_for_glossary:
                checks["glossary_flywheel"] = True
            # Transformer -> Transformer (English retained)
            if re.search(r"transformer", body_for_glossary, flags=re.IGNORECASE):
                checks["glossary_transformer"] = True
            # grounding -> 落地
            if "落地" in body_for_glossary:
                checks["glossary_grounding"] = True
            # alignment -> 对齐
            if "对齐" in body_for_glossary:
                checks["glossary_alignment"] = True
            # hallucination -> 幻觉
            if "幻觉" in body_for_glossary:
                checks["glossary_hallucination"] = True

    # Compute reward
    # Weights:
    # Config: exists (0.05), values ok (0.10) = 0.15
    # Outputs: translation_exists (0.05), analysis_exists (0.05), prompt_exists (0.05) = 0.15
    # Frontmatter: present (0.10), source_fields_ok (0.10), translated_fields_ok (0.10) = 0.30
    # Code block: preserved (0.10)
    # Glossary: 8 terms equally (0.30 total -> 0.0375 each)
    reward = 0.0
    reward += 0.05 * bool_to_float(checks["config_exists"])
    reward += 0.10 * bool_to_float(checks["config_values_ok"])

    reward += 0.05 * bool_to_float(checks["translation_exists"])
    reward += 0.05 * bool_to_float(checks["analysis_exists"])
    reward += 0.05 * bool_to_float(checks["prompt_exists"])

    reward += 0.10 * bool_to_float(checks["translation_frontmatter_present"])
    reward += 0.10 * bool_to_float(checks["translation_frontmatter_source_fields_ok"])
    reward += 0.10 * bool_to_float(checks["translation_frontmatter_translated_fields_ok"])

    reward += 0.10 * bool_to_float(checks["code_block_preserved"])

    glossary_keys = [
        "glossary_ai_agent",
        "glossary_guardrails",
        "glossary_rlhf",
        "glossary_flywheel",
        "glossary_transformer",
        "glossary_grounding",
        "glossary_alignment",
        "glossary_hallucination",
    ]
    per_gloss = 0.30 / len(glossary_keys)
    for k in glossary_keys:
        reward += per_gloss * bool_to_float(checks[k])

    # Ensure reward is 0 if no outputs at all (no-op baseline)
    output_exists_any = (
        checks["translation_exists"] or
        checks["analysis_exists"] or
        checks["prompt_exists"] or
        checks["config_exists"]
    )
    if not output_exists_any:
        reward = 0.0

    # Clamp reward to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()