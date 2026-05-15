import json
import os
import sys
import re
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_lines(path):
    txt = read_text(path)
    if txt is None:
        return None
    return txt.splitlines()

def normalize_ws(s: str) -> str:
    return " ".join((s or "").split())

def has_banned_substrings(text: str, banned_list):
    t = (text or "").lower()
    return any(b in t for b in banned_list)

def count_words(s: str) -> int:
    return len(re.findall(r"\S+", s or ""))

def get_feature_names_from_input(features_csv_path):
    feats = set()
    try:
        with open(features_csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return feats  # empty set; if cannot read, matching will fail
    if not rows:
        return feats
    header = rows[0]
    # Handle BOM on first cell
    if header:
        header[0] = header[0].lstrip("\ufeff")
    # Find "Feature" column case-insensitive
    col_idx = None
    for i, h in enumerate(header):
        if (h or "").strip().lower() == "feature":
            col_idx = i
            break
    if col_idx is None:
        return feats
    for row in rows[1:]:
        if len(row) > col_idx:
            val = (row[col_idx] or "").strip()
            if val:
                feats.add(val.strip().lower())
    return feats

def validate_one_thing(path):
    # Must exist, exactly one non-empty line, 1-5 words, no banned
    banned = ["we believe", "helps", "might", "flexible", "customizable"]
    lines = read_lines(path)
    if lines is None:
        return False
    nonempty = [ln.strip() for ln in lines if ln.strip() != ""]
    if len(nonempty) != 1:
        return False
    line = nonempty[0]
    if has_banned_substrings(line, banned):
        return False
    wc = count_words(line)
    if wc < 1 or wc > 5:
        return False
    return True

def validate_names(path):
    # 6–10 non-empty lines; each 1–2 words, letters and spaces only; no digits/punct; length<=16 excluding spaces
    # Must not contain: ai, cloud, sync, platform (case-insensitive)
    # All lines unique (case-insensitive)
    banned = ["ai", "cloud", "sync", "platform"]
    lines = read_lines(path)
    if lines is None:
        return False
    names = [ln.strip() for ln in lines if ln.strip() != ""]
    if len(names) < 6 or len(names) > 10:
        return False
    # Uniqueness check
    lower_set = set()
    for n in names:
        low = n.lower()
        if low in lower_set:
            return False
        lower_set.add(low)
    # Validate each name
    pattern = re.compile(r"^[A-Za-z]+(?: [A-Za-z]+)?$")  # 1-2 words, letters only
    for n in names:
        if not pattern.fullmatch(n):
            return False
        if len(n.replace(" ", "")) > 16:
            return False
        if has_banned_substrings(n, banned):
            return False
    return True

def validate_taglines(path):
    # 8–12 non-empty lines; each <= 6 words and <= 40 chars; unique case-insensitive
    # Must not contain banned substrings
    banned = ["ai", "api", "sdk", "gb", "machine", "customizable", "flexible", "helps", "might", "we believe", "feature"]
    lines = read_lines(path)
    if lines is None:
        return False
    taglines = [ln.strip() for ln in lines if ln.strip() != ""]
    if len(taglines) < 8 or len(taglines) > 12:
        return False
    seen = set()
    for tl in taglines:
        if len(tl) > 40:
            return False
        if count_words(tl) > 6:
            return False
        if has_banned_substrings(tl, banned):
            return False
        low = tl.lower()
        if low in seen:
            return False
        seen.add(low)
    return True

def validate_hero(path):
    # First line starts with "# " and <=7 words; contains "## Old way" and "## New way"
    # Under each heading at least 3 bullet lines "- "
    # Must not contain banned substrings anywhere
    banned = ["we believe", "helps", "might", "customizable", "flexible", "api", "sdk", "gb", "machine"]
    lines = read_lines(path)
    if lines is None or len(lines) == 0:
        return False
    content = "\n".join(lines)
    if has_banned_substrings(content, banned):
        return False
    first = lines[0]
    if not first.startswith("# "):
        return False
    headline = first[2:].strip()
    if headline == "":
        return False
    if count_words(headline) > 7:
        return False
    # Find headings exactly
    try:
        old_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "## Old way")
        new_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "## New way")
    except StopIteration:
        return False
    # Count bullets under each heading until next "## " or EOF
    def count_bullets(start_idx):
        cnt = 0
        i = start_idx + 1
        while i < len(lines):
            ln = lines[i]
            if ln.strip().startswith("## "):
                break
            if ln.startswith("- "):
                cnt += 1
            i += 1
        return cnt
    old_bullets = count_bullets(old_idx)
    new_bullets = count_bullets(new_idx)
    if old_bullets < 3 or new_bullets < 3:
        return False
    return True

def validate_pricing(path):
    # Valid JSON object with required keys and constraints
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    # Banned top-level keys
    for bad in ["tiers", "plans", "matrix"]:
        if bad in data:
            return False
    # Required keys
    if "plan_name" not in data or "price" not in data or "currency" not in data or "billing_period" not in data:
        return False
    if not isinstance(data["plan_name"], str) or data["plan_name"].strip() == "":
        return False
    if not (isinstance(data["price"], int) or isinstance(data["price"], float)):
        return False
    if data["price"] < 1 or data["price"] > 100:
        return False
    if not isinstance(data["currency"], str) or data["currency"].strip() == "":
        return False
    if not isinstance(data["billing_period"], str) or data["billing_period"].strip() == "":
        return False
    period = data["billing_period"].strip().lower()
    if period not in ("monthly", "yearly"):
        return False
    # Value statement key: "value" or "value_statement"
    has_value = False
    if "value" in data and isinstance(data["value"], str) and data["value"].strip() != "":
        has_value = True
    if "value_statement" in data and isinstance(data["value_statement"], str) and data["value_statement"].strip() != "":
        has_value = True
    if not has_value:
        return False
    return True

def validate_kill_grid(path, features_csv_path):
    # CSV with header exactly Axis1,Axis2,KeepOrKill,Name,Reason and constraints
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return False
    if not rows or not rows[0]:
        return False
    header = rows[0]
    header[0] = (header[0] or "").lstrip("\ufeff")
    if header != ["Axis1", "Axis2", "KeepOrKill", "Name", "Reason"]:
        return False
    data_rows = rows[1:]
    if len(data_rows) < 4:
        return False
    keep_count = 0
    kill_count = 0
    # Load features from input/features.csv
    feature_names = get_feature_names_from_input(features_csv_path)
    if not feature_names:
        # If no feature names available, cannot validate mapping -> fail
        return False
    for r in data_rows:
        # Ensure at least 5 columns
        if len(r) < 5:
            return False
        axis1, axis2, kok, name, reason = r[0].strip(), r[1].strip(), r[2].strip(), r[3].strip(), r[4].strip()
        if kok not in ("Keep", "Kill"):
            return False
        if kok == "Keep":
            keep_count += 1
        if kok == "Kill":
            kill_count += 1
        if reason == "":
            return False
        if name.strip() == "":
            return False
        # Name must match a Feature value from input/features.csv (case-insensitive)
        if name.strip().lower() not in feature_names:
            return False
    if kill_count < 2 or keep_count < 1:
        return False
    return True

def validate_presentation(path):
    # Five numbered sections 1..5 in order with required phrases; under 3. exactly three bullets; no banned substrings
    banned = ["we believe", "helps", "might", "customizable", "flexible", "api", "sdk", "gb", "machine"]
    lines = read_lines(path)
    if lines is None:
        return False
    content = "\n".join(lines)
    if has_banned_substrings(content, banned):
        return False
    # Find section lines
    numbered = []
    for idx, ln in enumerate(lines):
        m = re.match(r"^\s*([1-5])\.\s*(.*)$", ln)
        if m:
            num = int(m.group(1))
            text = m.group(2)
            numbered.append((idx, num, text))
    # Need at least one of each 1..5 in order
    indices_map = {}
    expected = [1, 2, 3, 4, 5]
    # Record first occurrence of each required number
    for num in expected:
        found = next(((i, n, t) for (i, n, t) in numbered if n == num), None)
        if not found:
            return False
        indices_map[num] = found
    # Check order by index increasing
    last_index = -1
    for num in expected:
        idx = indices_map[num][0]
        if idx <= last_index:
            return False
        last_index = idx
    # Check required phrases in those lines (case-insensitive contains)
    req_phrases = {
        1: "set the stage",
        2: "introduce the hero",
        3: "rule of three",
        4: "demo",
        5: "one more thing",
    }
    for num in expected:
        text = indices_map[num][2]
        if req_phrases[num] not in text.lower():
            return False
    # Under section 3, exactly three bullets starting with "- "
    idx3 = indices_map[3][0]
    # Find next numbered line after 3 to delimit the section
    end_idx = len(lines)
    for idx, n, _ in numbered:
        if idx > idx3 and n == 4:
            end_idx = idx
            break
    bullets = 0
    for i in range(idx3 + 1, end_idx):
        ln = lines[i]
        if ln.startswith("- "):
            bullets += 1
    if bullets != 3:
        return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    one_thing_path = os.path.join(output_dir, "one_thing.txt")
    names_path = os.path.join(output_dir, "names.txt")
    taglines_path = os.path.join(output_dir, "taglines.txt")
    hero_path = os.path.join(output_dir, "hero.md")
    pricing_path = os.path.join(output_dir, "pricing.json")
    kill_grid_path = os.path.join(output_dir, "kill_grid.csv")
    presentation_path = os.path.join(output_dir, "presentation.md")

    features_csv_path = os.path.join(input_dir, "features.csv")

    checks = {
        "one_thing_ok": False,
        "names_ok": False,
        "taglines_ok": False,
        "hero_ok": False,
        "pricing_ok": False,
        "kill_grid_ok": False,
        "presentation_ok": False,
    }

    # Perform validations only if files exist as needed
    if os.path.isfile(one_thing_path):
        checks["one_thing_ok"] = validate_one_thing(one_thing_path)

    if os.path.isfile(names_path):
        checks["names_ok"] = validate_names(names_path)

    if os.path.isfile(taglines_path):
        checks["taglines_ok"] = validate_taglines(taglines_path)

    if os.path.isfile(hero_path):
        checks["hero_ok"] = validate_hero(hero_path)

    if os.path.isfile(pricing_path):
        checks["pricing_ok"] = validate_pricing(pricing_path)

    if os.path.isfile(kill_grid_path):
        checks["kill_grid_ok"] = validate_kill_grid(kill_grid_path, features_csv_path)

    if os.path.isfile(presentation_path):
        checks["presentation_ok"] = validate_presentation(presentation_path)

    # Compute reward: fraction of checks passed; explicit no-op baseline gives 0.0 when all False
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if passed > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()