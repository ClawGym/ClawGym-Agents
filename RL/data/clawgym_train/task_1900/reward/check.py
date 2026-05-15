import json
import os
import re
import sys

def kebab_case(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    s = s.strip('-')
    return s

def parse_list_value(raw: str):
    raw = raw.strip()
    if not (raw.startswith('[') and raw.endswith(']')):
        return None
    inner = raw[1:-1].strip()
    if inner == '':
        return []
    items = [itm.strip() for itm in inner.split(',')]
    normalized = []
    for itm in items:
        # remove surrounding quotes if present
        if (len(itm) >= 2) and ((itm[0] == '"' and itm[-1] == '"') or (itm[0] == "'" and itm[-1] == "'")):
            itm = itm[1:-1]
        normalized.append(itm)
    return normalized

def extract_metadata_block(lines):
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if '<!-- KB_META_START -->' in line:
            start_idx = i
        if '<!-- KB_META_END -->' in line:
            end_idx = i
            break
    if start_idx is None or end_idx is None or end_idx <= start_idx:
        return None, None, None
    content_lines = lines[start_idx+1:end_idx]
    content_text = '\n'.join(content_lines)
    return start_idx, end_idx, content_text

def parse_metadata_kv(block_text):
    required_keys = ["id", "name_zh", "name_en", "category", "tags", "scenarios", "related_models", "difficulty", "contradiction"]
    kv = {}
    counts = {k: 0 for k in required_keys}
    lines = [l for l in block_text.splitlines()]
    for line in lines:
        m = re.match(r'^\s*([a-zA-Z0-9_]+)\s*:\s*(.*)\s*$', line)
        if not m:
            continue
        key = m.group(1)
        val = m.group(2)
        if key in counts:
            counts[key] += 1
            if key in ["tags", "scenarios", "related_models"]:
                lst = parse_list_value(val)
                kv[key] = lst
            else:
                kv[key] = val
    return kv, counts

def count_words(text):
    return len(text.strip().split())

def get_next_nonempty_line(lines, start_index):
    for i in range(start_index+1, len(lines)):
        if lines[i].strip() != "":
            return lines[i]
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "analysis_exists": False,
        "analysis_non_empty": False,
        "kb_meta_exists": False,
        "kb_meta_valid_json": False,
        "single_model_header": False,
        "strategic_question_present": False,
        "strategic_question_has_content": False,
        "bullets_in_order": False,
        "f_length_leq_50": False,
        "metadata_block_present": False,
        "metadata_keys_once_each": False,
        "id_format_valid": False,
        "category_allowed": False,
        "tags_count_valid": False,
        "scenarios_count_valid": False,
        "related_models_count_valid": False,
        "difficulty_allowed": False,
        "contradiction_has_symbols_and_arrow": False,
        "model_name_equals_name_en": False,
        "id_matches_kebab_name_en": False,
        "transfer_contains_you": False,
        "anchor_case_length_ge_80": False,
        "kb_json_fields_exact": False,
        "kb_json_constraints_ok": False,
        "metadata_json_match": False
    }

    allowed_categories = {"investing", "startup", "systems", "ai-thinking", "positioning", "management", "growth", "cognitive-bias", "influence", "economics"}
    allowed_difficulty = {"beginner", "intermediate", "advanced"}

    analysis_path = os.path.join(output_dir, "analysis.md")
    kb_meta_path = os.path.join(output_dir, "kb_meta.json")

    analysis_lines = []
    analysis_text = ""
    if os.path.isfile(analysis_path):
        checks["analysis_exists"] = True
        try:
            with open(analysis_path, "r", encoding="utf-8") as f:
                analysis_text = f.read()
                if analysis_text.strip() != "":
                    checks["analysis_non_empty"] = True
                analysis_lines = analysis_text.splitlines()
        except Exception:
            pass

    # Early parse only if analysis exists and non-empty
    model_name = None
    name_en_in_meta = None
    id_in_meta = None
    category_in_meta = None
    tags_in_meta = None
    scenarios_in_meta = None
    related_models_in_meta = None
    difficulty_in_meta = None
    contradiction_in_meta = None

    f_text = ""
    a_text = ""
    t_text = ""

    if checks["analysis_non_empty"]:
        # Check single model header
        header_lines = [ln for ln in analysis_lines if ln.lstrip().startswith("### 💎 ")]
        if len(header_lines) == 1:
            checks["single_model_header"] = True
            header = header_lines[0].lstrip()
            model_name = header[len("### 💎 "):].strip()

        # Strategic question presence and content after
        sq_indices = [i for i, ln in enumerate(analysis_lines) if ln.strip() == "### ⚡ Strategic Question"]
        if len(sq_indices) >= 1:
            checks["strategic_question_present"] = True
            next_line = get_next_nonempty_line(analysis_lines, sq_indices[0])
            if next_line is not None and next_line.strip() != "":
                checks["strategic_question_has_content"] = True

        # Bullets in order and extract texts
        bullet_prefixes = [
            "- **[F] Core Framework**:",
            "- **[A] Anchor Case**:",
            "- **[C] Contradiction Destroyed**:",
            "- **[E] Hidden Boundaries**:",
            "- **[T] Cross-Domain Transfer**:"
        ]
        bullet_indices = []
        bullet_texts = []
        valid_order = True
        last_index = -1
        for pref in bullet_prefixes:
            matching = [i for i, ln in enumerate(analysis_lines) if ln.startswith(pref)]
            if len(matching) != 1:
                valid_order = False
                break
            idx = matching[0]
            if idx <= last_index:
                valid_order = False
                break
            last_index = idx
            bullet_indices.append(idx)
            line = analysis_lines[idx]
            # Extract text after first colon
            colon_pos = line.find(':')
            content_after = line[colon_pos+1:].strip() if colon_pos != -1 else ""
            bullet_texts.append(content_after)
        if valid_order:
            checks["bullets_in_order"] = True
            if len(bullet_texts) == 5:
                f_text = bullet_texts[0]
                a_text = bullet_texts[1]
                # c_text = bullet_texts[2]  # not needed for deterministic checks beyond metadata
                # e_text = bullet_texts[3]
                t_text = bullet_texts[4]
                # F length <= 50 words
                if count_words(f_text) <= 50 and f_text.strip() != "":
                    checks["f_length_leq_50"] = True
                # T contains 'you' or 'your'
                lt = t_text.lower()
                if (" you " in f" {lt} ") or (" your " in f" {lt} ") or lt.startswith("you ") or lt.startswith("your ") or lt.endswith(" you") or lt.endswith(" your"):
                    checks["transfer_contains_you"] = True
                # A length >= 80 chars (characters, not bytes)
                if len(a_text) >= 80:
                    checks["anchor_case_length_ge_80"] = True

        # Metadata block
        start_idx, end_idx, block_text = extract_metadata_block(analysis_lines)
        if block_text is not None:
            checks["metadata_block_present"] = True
            kv, counts = parse_metadata_kv(block_text)
            # Check keys once each
            required_keys = ["id", "name_zh", "name_en", "category", "tags", "scenarios", "related_models", "difficulty", "contradiction"]
            keys_once = all(counts.get(k, 0) == 1 for k in required_keys)
            # Also ensure all are present in kv
            keys_present = all(k in kv and kv[k] is not None for k in required_keys)
            if keys_once and keys_present:
                checks["metadata_keys_once_each"] = True
                id_in_meta = kv["id"].strip()
                name_en_in_meta = kv["name_en"].strip()
                category_in_meta = kv["category"].strip()
                tags_in_meta = kv["tags"]
                scenarios_in_meta = kv["scenarios"]
                related_models_in_meta = kv["related_models"]
                difficulty_in_meta = kv["difficulty"].strip()
                contradiction_in_meta = kv["contradiction"].strip()

                # id format
                if re.fullmatch(r'^[a-z0-9]+(?:-[a-z0-9]+)*$', id_in_meta):
                    checks["id_format_valid"] = True
                # category allowed
                if category_in_meta in allowed_categories:
                    checks["category_allowed"] = True
                # tags count 3-5
                if isinstance(tags_in_meta, list) and 3 <= len(tags_in_meta) <= 5:
                    checks["tags_count_valid"] = True
                # scenarios count 3-5
                if isinstance(scenarios_in_meta, list) and 3 <= len(scenarios_in_meta) <= 5:
                    checks["scenarios_count_valid"] = True
                # related_models count 2-4
                if isinstance(related_models_in_meta, list) and 2 <= len(related_models_in_meta) <= 4:
                    checks["related_models_count_valid"] = True
                # difficulty allowed
                if difficulty_in_meta in allowed_difficulty:
                    checks["difficulty_allowed"] = True
                # contradiction has symbols and arrow
                contr = contradiction_in_meta
                if ("❌" in contr) and ("✅" in contr) and ("→" in contr):
                    checks["contradiction_has_symbols_and_arrow"] = True
                # Model name equals name_en
                if model_name is not None and name_en_in_meta == model_name:
                    checks["model_name_equals_name_en"] = True
                # id matches kebab of name_en
                if name_en_in_meta:
                    if id_in_meta == kebab_case(name_en_in_meta):
                        checks["id_matches_kebab_name_en"] = True

    # Parse kb_meta.json
    kb_json = None
    if os.path.isfile(kb_meta_path):
        checks["kb_meta_exists"] = True
        try:
            with open(kb_meta_path, "r", encoding="utf-8") as jf:
                kb_json = json.load(jf)
            if isinstance(kb_json, dict):
                checks["kb_meta_valid_json"] = True
        except Exception:
            kb_json = None

    if checks["kb_meta_valid_json"]:
        # Fields exact
        required_fields = ["id", "name_zh", "name_en", "category", "tags", "scenarios", "related_models", "difficulty", "contradiction"]
        if set(kb_json.keys()) == set(required_fields):
            checks["kb_json_fields_exact"] = True
        # Constraints on JSON
        ok_json_constraints = True
        try:
            j_id = kb_json["id"]
            j_name_en = kb_json["name_en"]
            j_category = kb_json["category"]
            j_tags = kb_json["tags"]
            j_scenarios = kb_json["scenarios"]
            j_related = kb_json["related_models"]
            j_difficulty = kb_json["difficulty"]
            j_contradiction = kb_json["contradiction"]

            if not isinstance(j_id, str) or re.fullmatch(r'^[a-z0-9]+(?:-[a-z0-9]+)*$', j_id) is None:
                ok_json_constraints = False
            if j_category not in allowed_categories:
                ok_json_constraints = False
            if not (isinstance(j_tags, list) and all(isinstance(x, str) for x in j_tags) and 3 <= len(j_tags) <= 5):
                ok_json_constraints = False
            if not (isinstance(j_scenarios, list) and all(isinstance(x, str) for x in j_scenarios) and 3 <= len(j_scenarios) <= 5):
                ok_json_constraints = False
            if not (isinstance(j_related, list) and all(isinstance(x, str) for x in j_related) and 2 <= len(j_related) <= 4):
                ok_json_constraints = False
            if j_difficulty not in allowed_difficulty:
                ok_json_constraints = False
            if not (isinstance(j_contradiction, str) and ("❌" in j_contradiction) and ("✅" in j_contradiction) and ("→" in j_contradiction)):
                ok_json_constraints = False
            # id matches kebab-case of name_en
            if not isinstance(j_name_en, str) or kebab_case(j_name_en) != j_id:
                ok_json_constraints = False
        except Exception:
            ok_json_constraints = False

        if ok_json_constraints:
            checks["kb_json_constraints_ok"] = True

        # Cross-validate with metadata block
        if checks["metadata_keys_once_each"]:
            cross_ok = True
            try:
                # Strings
                if kb_json["id"] != id_in_meta:
                    cross_ok = False
                if kb_json["name_zh"] != kv["name_zh"].strip():
                    cross_ok = False
                if kb_json["name_en"] != name_en_in_meta:
                    cross_ok = False
                if kb_json["category"] != category_in_meta:
                    cross_ok = False
                if kb_json["difficulty"] != difficulty_in_meta:
                    cross_ok = False
                if kb_json["contradiction"] != contradiction_in_meta:
                    cross_ok = False
                # Lists (exact order)
                if tags_in_meta is None or scenarios_in_meta is None or related_models_in_meta is None:
                    cross_ok = False
                else:
                    if kb_json["tags"] != tags_in_meta:
                        cross_ok = False
                    if kb_json["scenarios"] != scenarios_in_meta:
                        cross_ok = False
                    if kb_json["related_models"] != related_models_in_meta:
                        cross_ok = False
            except Exception:
                cross_ok = False
            if cross_ok:
                checks["metadata_json_match"] = True

    # Compute reward
    # Enforce no-op baseline: if required artifacts missing, reward must be 0.0
    required_present = checks["analysis_exists"] and checks["analysis_non_empty"] and checks["kb_meta_exists"] and checks["kb_meta_valid_json"]
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    if required_present:
        reward = passed_checks / total_checks if total_checks > 0 else 0.0
    else:
        reward = 0.0

    # Print JSON result
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()