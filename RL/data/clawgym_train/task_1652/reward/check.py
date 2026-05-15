import json
import os
import re
import sys

def read_jsonl(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    items.append(obj)
                except json.JSONDecodeError:
                    return None, f"Invalid JSONL line: {line[:80]}"
        return items, None
    except FileNotFoundError:
        return None, "File not found"
    except Exception as e:
        return None, str(e)

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, "File not found"
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {e}"
    except Exception as e:
        return None, str(e)

def read_text_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [ln.rstrip("\n") for ln in f.readlines()], None
    except FileNotFoundError:
        return None, "File not found"
    except Exception as e:
        return None, str(e)

def extract_tokens(molt):
    # Allowed tags and token inner content extractor
    token_inner = r'(?:OP|SRC|PARAM|TRY|CATCH|RETRY|LOG|ASYNC|PAR|VALIDATE)(?::[^\[\]]+)?'
    pattern = re.compile(r'\[(' + token_inner + r')\]')
    return pattern.findall(molt or "")

def molt_valid_by_regex(molt):
    token_inner = r'(?:OP|SRC|PARAM|TRY|CATCH|RETRY|LOG|ASYNC|PAR|VALIDATE)(?::[^\[\]]+)?'
    full = re.compile(r'^\s*(?:\[' + token_inner + r'\]\s*)+$')
    return bool(full.match(molt or ""))

def round_one_decimal(x):
    try:
        return round(x, 1)
    except Exception:
        return 0.0

def parse_header_indices(lines, header_name):
    # returns index of header and index of next header or len(lines)
    header_idx = None
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if re.match(r'^\s*#{1,6}\s*' + re.escape(header_name) + r'\s*$', stripped, flags=re.IGNORECASE) or stripped.lower() == header_name.lower():
            header_idx = i
            break
    if header_idx is None:
        return None, None
    # find next header
    next_idx = len(lines)
    for j in range(header_idx + 1, len(lines)):
        s = lines[j].strip()
        if re.match(r'^\s*#{1,6}\s*\S.*$', s):  # any markdown header
            next_idx = j
            break
    return header_idx, next_idx

def get_section_lines(lines, header_name):
    i, j = parse_header_indices(lines, header_name)
    if i is None:
        return None
    return lines[i+1:j]

def parse_total_entries(lines):
    for ln in lines:
        m = re.search(r'Total entries:\s*(\d+)', ln, flags=re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except:
                return None
    return None

def parse_average_savings(lines):
    for ln in lines:
        m = re.search(r'Average savings:\s*([0-9]+(?:\.[0-9])?)\s*%', ln, flags=re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except:
                return None
    return None

def parse_validation_counts(lines):
    sect = get_section_lines(lines, "Validation")
    if sect is None:
        return None, None
    for ln in sect:
        m = re.search(r'Valid syntax:\s*(\d+)\s*of\s*(\d+)', ln, flags=re.IGNORECASE)
        if m:
            try:
                return int(m.group(1)), int(m.group(2))
            except:
                return None, None
    return None, None

def parse_top_savings(lines):
    sect = get_section_lines(lines, "Top Savings")
    if sect is None:
        return []
    res = []
    for ln in sect:
        m = re.search(r'id:\s*([^\s]+)\s*-\s*([0-9]+(?:\.[0-9])?)\s*%', ln, flags=re.IGNORECASE)
        if m:
            res.append((m.group(1), m.group(2)))
    return res

def parse_tokens_used(lines):
    sect = get_section_lines(lines, "Tokens Used")
    if sect is None:
        return None
    tokens = []
    for ln in sect:
        s = ln.strip()
        if not s:
            continue
        # strip bullets or numbering
        s = re.sub(r'^[-*]\s*', '', s).strip()
        if s:
            tokens.append(s)
    return tokens

def count_discussion_bullets(lines):
    sect = get_section_lines(lines, "Discussion")
    if sect is None:
        return 0
    count = 0
    for ln in sect:
        if re.match(r'^\s*[-*]\s+\S+', ln):
            count += 1
    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {}

    # Load input
    input_path = os.path.join(input_dir, "instructions.jsonl")
    input_items, input_err = read_jsonl(input_path)
    N = 0
    input_by_id = {}
    if input_items is not None:
        for obj in input_items:
            if isinstance(obj, dict) and "id" in obj and "english" in obj:
                input_by_id[obj["id"]] = obj["english"]
        N = len(input_by_id)

    # Check translations.json
    translations_path = os.path.join(output_dir, "translations.json")
    translations, tr_err = read_json(translations_path)
    checks["has_translations_json"] = translations is not None and isinstance(translations, list)
    checks["translations_count_matches_input"] = False
    checks["translations_fields_and_match_ids_english"] = False
    checks["valid_syntax_field_matches_regex_for_all"] = False
    checks["savings_within_tolerance_for_all"] = False

    extracted_tokens_set = set()
    reported_savings_list = []

    if checks["has_translations_json"] and input_items is not None:
        # Verify count and ids match
        try:
            out_ids = []
            fields_ok = True
            id_english_ok = True
            valid_syntax_ok = True
            savings_ok = True

            allowed_fields = {"id", "english", "molt", "unmolt", "valid_syntax", "savings_percent"}

            for item in translations:
                # Verify dict and fields
                if not isinstance(item, dict):
                    fields_ok = False
                    break
                # required fields present
                for rf in allowed_fields:
                    if rf not in item:
                        fields_ok = False
                        break
                if not fields_ok:
                    break
                out_ids.append(item.get("id"))
                # id and english match input
                iid = item.get("id")
                eng = item.get("english")
                if iid not in input_by_id or input_by_id.get(iid) != eng:
                    id_english_ok = False
                # valid_syntax equality
                molt = item.get("molt")
                valid_by_regex = molt_valid_by_regex(molt)
                vs_field = item.get("valid_syntax")
                if not isinstance(vs_field, bool) or (vs_field != valid_by_regex):
                    valid_syntax_ok = False
                # savings tolerance
                if isinstance(eng, str) and isinstance(molt, str) and len(eng) > 0:
                    calc = max(0.0, 100.0 * (len(eng) - len(molt)) / len(eng))
                    calc = round_one_decimal(calc)
                else:
                    calc = 0.0
                rep = item.get("savings_percent")
                try:
                    repf = float(rep)
                except Exception:
                    repf = None
                if repf is None or abs(repf - calc) > 1.0:
                    savings_ok = False
                # collect tokens and savings
                for t in extract_tokens(molt or ""):
                    extracted_tokens_set.add(t)
                if repf is not None:
                    reported_savings_list.append(repf)

            # count match by set equality and length
            checks["translations_count_matches_input"] = (len(translations) == N)
            # also verify that ids sets match
            if len(out_ids) == N and set(out_ids) == set(input_by_id.keys()):
                ids_match = True
            else:
                ids_match = False
            checks["translations_fields_and_match_ids_english"] = fields_ok and id_english_ok and ids_match
            checks["valid_syntax_field_matches_regex_for_all"] = valid_syntax_ok
            checks["savings_within_tolerance_for_all"] = savings_ok
        except Exception:
            pass

    # tokens.txt checks
    tokens_txt_path = os.path.join(output_dir, "tokens.txt")
    tokens_lines, tt_err = read_text_lines(tokens_txt_path)
    checks["has_tokens_txt"] = tokens_lines is not None
    checks["tokens_txt_matches_extracted"] = False
    if checks["has_tokens_txt"]:
        # Prepare expected tokens sorted
        expected_tokens = sorted(extracted_tokens_set)
        # Filter lines: non-empty lines
        given_tokens = [ln.strip() for ln in tokens_lines if ln.strip() != ""]
        # Must be unique and sorted ascending and exact match
        is_unique_sorted = given_tokens == sorted(set(given_tokens))
        checks["tokens_txt_matches_extracted"] = is_unique_sorted and (given_tokens == expected_tokens)

    # report.md checks
    report_md_path = os.path.join(output_dir, "report.md")
    report_lines, rep_err = read_text_lines(report_md_path)
    checks["has_report_md"] = report_lines is not None
    checks["report_total_entries_correct"] = False
    checks["report_average_savings_within_tolerance"] = False
    checks["report_validation_counts_correct"] = False
    checks["report_top_savings_format_three_and_ids_exist"] = False
    checks["report_tokens_used_matches_tokens_txt"] = False
    checks["report_discussion_has_at_least_three_bullets"] = False

    if checks["has_report_md"]:
        # Total entries
        total_entries = parse_total_entries(report_lines)
        if total_entries is not None and total_entries == N:
            checks["report_total_entries_correct"] = True

        # Average savings
        avg_line_val = parse_average_savings(report_lines)
        if avg_line_val is not None and reported_savings_list:
            avg_calc = sum(reported_savings_list) / len(reported_savings_list)
            avg_calc = round_one_decimal(avg_calc)
            if abs(avg_line_val - avg_calc) <= 1.0:
                checks["report_average_savings_within_tolerance"] = True

        # Validation counts
        v_true = 0
        if checks["has_translations_json"]:
            for item in translations:
                if bool(item.get("valid_syntax")):
                    v_true += 1
        v_report, n_report = parse_validation_counts(report_lines)
        if v_report is not None and n_report is not None:
            if v_report == v_true and n_report == N:
                checks["report_validation_counts_correct"] = True

        # Top Savings section format
        ts = parse_top_savings(report_lines)
        # Must contain exactly 3 lines and ids exist in input and numbers parse
        top_ok = False
        if len(ts) == 3:
            ids_ok = all(i in input_by_id for (i, _) in ts)
            nums_ok = True
            for _, num in ts:
                try:
                    float(num)
                except:
                    nums_ok = False
                    break
            top_ok = ids_ok and nums_ok
        checks["report_top_savings_format_three_and_ids_exist"] = top_ok

        # Tokens Used matches tokens.txt
        tokens_used = parse_tokens_used(report_lines)
        if tokens_used is not None and checks["has_tokens_txt"]:
            # list must exactly match the set in tokens.txt
            given_tokens = set([ln.strip() for ln in tokens_lines if ln.strip() != ""])
            used_set = set([t.strip() for t in tokens_used if t.strip() != ""])
            # no extraneous and includes all tokens.txt entries -> equality
            if used_set == given_tokens:
                checks["report_tokens_used_matches_tokens_txt"] = True

        # Discussion bullets
        disc_count = count_discussion_bullets(report_lines)
        if disc_count >= 3:
            checks["report_discussion_has_at_least_three_bullets"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # Ensure no-op baseline: if outputs missing, reward must be 0.0
    output_exists = os.path.isdir(output_dir) and any(
        os.path.exists(os.path.join(output_dir, p)) for p in ["translations.json", "tokens.txt", "report.md"]
    )
    if not output_exists:
        reward = 0.0

    # Print result JSON
    result = {"reward": float(round(reward, 6))}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()