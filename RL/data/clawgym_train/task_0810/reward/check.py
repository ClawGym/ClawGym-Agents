import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def read_csv_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            # Ensure headers are present
            if reader.fieldnames is None:
                return None
            # Validate all rows have the same keys
            for r in rows:
                if set(r.keys()) != set(reader.fieldnames):
                    return None
            return rows
    except Exception:
        return None


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def file_size_bytes(path: Path) -> int:
    try:
        if path.exists() and path.is_file():
            return path.stat().st_size
        return 0
    except Exception:
        return 0


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s


def load_settings_yaml_minimal(path: Path) -> Optional[Dict]:
    """
    Minimal YAML parser tailored for the expected structure of settings.yaml:
    - top-level keys: out_dir, disclaimers (mapping), subject_template (string), body_template (literal block)
    - supports 'disclaimers: {}' or a nested mapping block
    - supports body_template: | followed by indented lines
    """
    text = read_text_safe(path)
    if text is None:
        return None

    lines = text.splitlines()
    settings: Dict = {"disclaimers": {}}
    i = 0
    n = len(lines)

    # Helpers to detect indentation
    def indent_of(s: str) -> int:
        return len(s) - len(s.lstrip(" "))

    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # out_dir
        m = re.match(r'^\s*out_dir\s*:\s*(.+?)\s*$', line)
        if m:
            settings["out_dir"] = _strip_quotes(m.group(1))
            i += 1
            continue

        # subject_template
        m = re.match(r'^\s*subject_template\s*:\s*(.+?)\s*$', line)
        if m:
            settings["subject_template"] = _strip_quotes(m.group(1))
            i += 1
            continue

        # disclaimers mapping
        m = re.match(r'^(\s*)disclaimers\s*:\s*(\{\s*\})?\s*$', line)
        if m:
            base_indent = len(m.group(1))
            if m.group(2):
                settings["disclaimers"] = {}
                i += 1
                continue
            # Parse nested mapping
            i += 1
            disclaimers: Dict[str, str] = {}
            while i < n:
                l2 = lines[i]
                if not l2.strip() or l2.strip().startswith("#"):
                    i += 1
                    continue
                ind2 = indent_of(l2)
                if ind2 <= base_indent:
                    break
                # Expect key: value on one line
                mm = re.match(r'^\s*([A-Za-z0-9_]+)\s*:\s*(.+?)\s*$', l2)
                if mm:
                    key = mm.group(1)
                    val = _strip_quotes(mm.group(2))
                    disclaimers[key] = val
                    i += 1
                else:
                    # Malformed mapping
                    return None
            settings["disclaimers"] = disclaimers
            continue

        # body_template literal block
        m = re.match(r'^(\s*)body_template\s*:\s*\|\s*$', line)
        if m:
            base_indent = len(m.group(1))
            i += 1
            block_lines: List[str] = []
            # Collect lines with indent > base_indent
            while i < n:
                l2 = lines[i]
                if not l2.strip():
                    # preserve blank lines inside block with newline
                    block_lines.append("")
                    i += 1
                    continue
                ind2 = indent_of(l2)
                if ind2 <= base_indent:
                    break
                # Remove the minimal indent of the block content
                block_lines.append(l2[base_indent + 2 if ind2 >= base_indent + 2 else ind2 :])
                i += 1
            # Join with newlines; YAML literal '|' preserves newlines as-is
            settings["body_template"] = "\n".join(block_lines)
            continue

        # Unknown top-level key, skip
        i += 1

    return settings


def safe_subject_fill(template: str, data: Dict[str, str]) -> str:
    """
    Safely replace {placeholders} in template using provided data.
    Unknown placeholders are left intact.
    """
    def repl(match: re.Match) -> str:
        key = match.group(1)
        return str(data.get(key, "{" + key + "}"))
    return re.sub(r"\{([A-Za-z0-9_]+)\}", repl, template)


def find_line_index(lines: List[str], predicate) -> int:
    for idx, ln in enumerate(lines):
        if predicate(ln):
            return idx
    return -1


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "config_out_dir_updated": 0.0,
        "config_disclaimers_added": 0.0,
        "config_body_template_modified": 0.0,
        "manifest_exists_and_headers": 0.0,
        "manifest_row_count": 0.0,
        "manifest_paths_and_status_consistency": 0.0,
        "brand_icons_saved_consistency": 0.0,
        "emails_generated_count": 0.0,
        "emails_headers_correct": 0.0,
        "emails_body_includes_required_fields": 0.0,
        "emails_brand_icon_line_correct": 0.0,
        "emails_disclaimer_correct": 0.0,
        "emails_brand_icon_before_disclaimer": 0.0,
    }

    # Load inputs
    input_csv_path = workspace / "input" / "recommendations.csv"
    rows = read_csv_safe(input_csv_path)

    # Load settings.yaml
    settings_path = workspace / "config" / "settings.yaml"
    settings = load_settings_yaml_minimal(settings_path) if settings_path.exists() else None

    # Expected disclaimers
    expected_supplement = (
        "These recommendations are provided for healthy adult dogs and are not a substitute for veterinary advice. "
        "Always check with your veterinarian before starting a new supplement."
    )
    expected_food = (
        "Transition foods gradually over 7–10 days to avoid GI upset. Monitor stool quality and consult your veterinarian if adverse signs occur."
    )

    # Config checks
    if settings is not None:
        # out_dir updated
        scores["config_out_dir_updated"] = 1.0 if settings.get("out_dir") == "out/emails" else 0.0

        # disclaimers added
        disc = settings.get("disclaimers", {}) if isinstance(settings.get("disclaimers", {}), dict) else {}
        supplement_ok = 1.0 if disc.get("supplement") == expected_supplement else 0.0
        food_ok = 1.0 if disc.get("food") == expected_food else 0.0
        # Average the two
        scores["config_disclaimers_added"] = (supplement_ok + food_ok) / 2.0

        # body_template modified: ensure "Brand icon: {brand_icon_path}" line immediately before "Disclaimer: {disclaimer}"
        body_tmpl = settings.get("body_template")
        if isinstance(body_tmpl, str) and body_tmpl.strip():
            bt_lines = body_tmpl.splitlines()
            disc_idx = find_line_index(bt_lines, lambda s: s.strip() == "Disclaimer: {disclaimer}")
            if disc_idx != -1:
                # Find the previous non-empty line
                prev_idx = disc_idx - 1
                while prev_idx >= 0 and bt_lines[prev_idx].strip() == "":
                    prev_idx -= 1
                if prev_idx >= 0:
                    if bt_lines[prev_idx].strip() == "Brand icon: {brand_icon_path}":
                        scores["config_body_template_modified"] = 1.0

    # Prepare expected unique brand domains
    unique_domains: List[str] = []
    domain_set = set()
    if rows is not None:
        for r in rows:
            dom = (r.get("brand_domain") or "").strip()
            if dom and dom not in domain_set:
                domain_set.add(dom)
                unique_domains.append(dom)

    # Manifest checks
    manifest_path = workspace / "reports" / "asset_manifest.csv"
    manifest_rows = read_csv_safe(manifest_path)
    # Validate headers
    if manifest_rows is not None:
        try:
            with manifest_path.open(newline="", encoding="utf-8") as mf:
                reader = csv.DictReader(mf)
                headers = reader.fieldnames or []
            expected_headers = ["brand_domain", "saved_path", "status", "bytes"]
            if headers == expected_headers:
                scores["manifest_exists_and_headers"] = 1.0
        except Exception:
            pass

    if rows is not None and manifest_rows is not None:
        # Row count equals unique domains
        if len(manifest_rows) == len(unique_domains):
            scores["manifest_row_count"] = 1.0

        # Build index by brand_domain
        manifest_by_domain: Dict[str, Dict[str, str]] = {}
        for mr in manifest_rows:
            manifest_by_domain[mr.get("brand_domain", "")] = mr

        # Check paths, status, bytes consistency per domain
        per_checks: List[float] = []
        for dom in unique_domains:
            mr = manifest_by_domain.get(dom)
            if mr is None:
                per_checks.append(0.0)
                continue
            expected_path = f"downloads/brand_icons/{dom}.ico"
            path_ok = 1.0 if mr.get("saved_path") == expected_path else 0.0
            status = mr.get("status", "")
            bytes_str = mr.get("bytes", "")
            try:
                bytes_val = int(bytes_str)
            except Exception:
                bytes_val = -1
            bytes_ok = 1.0 if bytes_val >= 0 else 0.0

            icon_file = workspace / "downloads" / "brand_icons" / f"{dom}.ico"
            exists = icon_file.exists() and icon_file.is_file()
            size = file_size_bytes(icon_file)

            status_ok = 0.0
            if status == "downloaded":
                if exists and size > 0 and bytes_val == size:
                    status_ok = 1.0
            elif status == "unavailable":
                # Should not create the file; if it exists with >0 bytes, that's inconsistent
                if (not exists) and bytes_val == 0:
                    status_ok = 1.0
                else:
                    # If file exists but bytes_val is 0, still inconsistent with requirement
                    status_ok = 0.0
            else:
                status_ok = 0.0

            per_checks.append(1.0 if (path_ok == 1.0 and bytes_ok == 1.0 and status_ok == 1.0) else 0.0)

        if per_checks:
            scores["manifest_paths_and_status_consistency"] = sum(per_checks) / len(per_checks)

    # Brand icons saved consistency: if a file exists for a domain, it must be non-empty
    brand_icon_checks: List[float] = []
    if rows is not None:
        for dom in unique_domains:
            icon_file = workspace / "downloads" / "brand_icons" / f"{dom}.ico"
            if icon_file.exists():
                sz = file_size_bytes(icon_file)
                brand_icon_checks.append(1.0 if sz > 0 else 0.0)
        # If none exist, consider this pass (no violations)
        scores["brand_icons_saved_consistency"] = (sum(brand_icon_checks) / len(brand_icon_checks)) if brand_icon_checks else 1.0

    # Emails checks
    if settings is not None and rows is not None:
        out_dir_str = settings.get("out_dir")
        subject_template = settings.get("subject_template")
        disclaimers_map = settings.get("disclaimers", {}) if isinstance(settings.get("disclaimers", {}), dict) else {}
        out_dir = workspace / (out_dir_str if isinstance(out_dir_str, str) else "")

        # emails_generated_count: ratio of files present
        present_count = 0
        total_rows = len(rows)
        # For other email checks
        header_checks = []
        body_fields_checks = []
        icon_line_checks = []
        disclaimer_checks = []
        icon_before_disclaimer_checks = []

        for r in rows:
            client_email = (r.get("client_email") or "").strip()
            dog_name = (r.get("dog_name") or "").strip()
            product_name = (r.get("product_name") or "").strip()
            brand = (r.get("brand") or "").strip()
            dog_weight_lb = (r.get("dog_weight_lb") or "").strip()
            dosage_note = (r.get("dosage_note") or "").strip()
            brand_domain = (r.get("brand_domain") or "").strip()
            category = (r.get("category") or "").strip()

            expected_filename = f"{client_email}_{dog_name}.txt"
            email_path = out_dir / expected_filename

            content = read_text_safe(email_path)
            if content is None:
                header_checks.append(0.0)
                body_fields_checks.append(0.0)
                icon_line_checks.append(0.0)
                disclaimer_checks.append(0.0)
                icon_before_disclaimer_checks.append(0.0)
                continue

            present_count += 1

            lines = content.splitlines()
            first_line = lines[0] if lines else ""
            to_ok = (first_line.strip() == f"To: {client_email}")

            # Subject check: find a line starting with "Subject: "
            subj_line_idx = find_line_index(lines, lambda s: s.startswith("Subject: "))
            subj_ok = False
            if isinstance(subject_template, str):
                expected_subject = safe_subject_fill(subject_template, {"dog_name": dog_name})
                if subj_line_idx != -1:
                    subj_ok = lines[subj_line_idx].strip() == f"Subject: {expected_subject}"

            header_checks.append(1.0 if (to_ok and subj_ok) else 0.0)

            # Body includes required fields
            contains_all = True
            lc = content  # case-sensitive matches for exact snippets
            if product_name not in lc:
                contains_all = False
            if brand not in lc:
                contains_all = False
            if dog_name not in lc:
                contains_all = False
            if dog_weight_lb not in lc:
                contains_all = False
            if dosage_note not in lc:
                contains_all = False
            body_fields_checks.append(1.0 if contains_all else 0.0)

            # Brand icon line correctness
            expected_icon_path = f"downloads/brand_icons/{brand_domain}.ico"
            icon_file = workspace / expected_icon_path
            icon_exists = icon_file.exists() and file_size_bytes(icon_file) > 0
            expected_icon_value = expected_icon_path if icon_exists else "UNAVAILABLE"
            icon_line_idx = find_line_index(lines, lambda s: s.strip().startswith("Brand icon: "))
            icon_line_ok = False
            if icon_line_idx != -1:
                icon_line_ok = lines[icon_line_idx].strip() == f"Brand icon: {expected_icon_value}"
            icon_line_checks.append(1.0 if icon_line_ok else 0.0)

            # Disclaimer correctness
            expected_disc = ""
            if category == "supplement":
                expected_disc = expected_supplement
            elif category == "food":
                expected_disc = expected_food
            # Check presence of the exact disclaimer string in content
            disclaimer_ok = expected_disc in content if expected_disc else False
            disclaimer_checks.append(1.0 if disclaimer_ok else 0.0)

            # Order: Brand icon line appears before Disclaimer line
            disc_line_idx = find_line_index(lines, lambda s: s.strip().startswith("Disclaimer:"))
            order_ok = (icon_line_idx != -1 and disc_line_idx != -1 and icon_line_idx < disc_line_idx)
            icon_before_disclaimer_checks.append(1.0 if order_ok else 0.0)

        scores["emails_generated_count"] = (present_count / total_rows) if total_rows > 0 else 0.0
        if header_checks:
            scores["emails_headers_correct"] = sum(header_checks) / len(header_checks)
        if body_fields_checks:
            scores["emails_body_includes_required_fields"] = sum(body_fields_checks) / len(body_fields_checks)
        if icon_line_checks:
            scores["emails_brand_icon_line_correct"] = sum(icon_line_checks) / len(icon_line_checks)
        if disclaimer_checks:
            scores["emails_disclaimer_correct"] = sum(disclaimer_checks) / len(disclaimer_checks)
        if icon_before_disclaimer_checks:
            scores["emails_brand_icon_before_disclaimer"] = sum(icon_before_disclaimer_checks) / len(icon_before_disclaimer_checks)

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()