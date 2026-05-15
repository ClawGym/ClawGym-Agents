import json
import sys
import re
from pathlib import Path


def read_text_safe(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_data_files(workspace: Path):
    data_dir = workspace / "data"
    if not data_dir.exists():
        return set()
    files = set()
    for p in data_dir.rglob("*"):
        if p.is_file():
            rel = p.relative_to(workspace).as_posix()
            files.add(rel)
    return files


def detect_heading_name(line: str, allowed):
    s = line.strip()
    if not s:
        return None
    s = s.lstrip("#").strip()
    s_no_colon = s[:-1].strip() if s.endswith(":") else s
    for h in allowed:
        if s == h or s_no_colon == h:
            return h
    return None


def extract_sections(text: str, required_headings):
    lines = text.splitlines()
    positions = []
    for idx, line in enumerate(lines):
        h = detect_heading_name(line, required_headings)
        if h:
            positions.append((h, idx))

    found_headings = [h for h, _ in positions]
    in_order = found_headings == required_headings

    sections = {}
    for i, (h, start_idx) in enumerate(positions):
        end_idx = len(lines)
        if i + 1 < len(positions):
            end_idx = positions[i + 1][1]
        content_lines = lines[start_idx + 1 : end_idx]
        sections[h] = "\n".join(content_lines).strip()
    return sections, in_order


def section_contains_paths(section_text: str):
    if not section_text:
        return set()
    matches = re.findall(r"\bdata/[A-Za-z0-9_\-./]+", section_text)
    cleaned = set()
    for m in matches:
        cleaned_path = m.rstrip(").,;:").strip()
        cleaned.add(cleaned_path)
    return cleaned


def get_bullet_lines(text: str):
    bullet_lines = []
    for line in text.splitlines():
        s = line.lstrip()
        if s.startswith("- ") or s.startswith("* "):
            bullet_lines.append(line.strip())
    return bullet_lines


def compute_top3_players_by_war(data_path: Path):
    data = load_json_safe(data_path)
    if not isinstance(data, list):
        return []
    players = []
    for row in data:
        if not isinstance(row, dict):
            return []
        try:
            name = row["name"]
            position = row["position"]
            bats = row["bats"]
            throws = row["throws"]
            war = row["projected_war"]
        except Exception:
            return []
        if not isinstance(name, str) or not isinstance(position, str):
            return []
        if not isinstance(bats, str) or not isinstance(throws, str):
            return []
        if not isinstance(war, (int, float)):
            return []
        players.append(
            {
                "name": name,
                "position": position,
                "bats": bats,
                "throws": throws,
                "projected_war": float(war),
            }
        )
    players_sorted = sorted(players, key=lambda x: x["projected_war"], reverse=True)
    return players_sorted[:3]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "architecture_md_structure": 0.0,
        "architecture_current_inputs_match": 0.0,
        "architecture_error_analysis_quality": 0.0,
        "architecture_proposed_architecture_quality": 0.0,
        "architecture_cli_sketch_quality": 0.0,
        "command_diagnostics_exception_captured": 0.0,
        "fan_email_mentions_pilot_weekly_local": 0.0,
        "fan_email_has_three_bullets": 0.0,
        "fan_email_top3_correct_order_and_fields": 0.0,
    }

    discovered_data_files = list_data_files(workspace)

    # Check architecture.md structure and sections
    arch_path = workspace / "output" / "architecture.md"
    arch_text = read_text_safe(arch_path)
    required_headings = ["Current Inputs", "Error Analysis", "Proposed Architecture", "CLI Sketch"]
    if arch_text is not None:
        sections, in_order = extract_sections(arch_text, required_headings)
        if in_order and all(h in sections for h in required_headings):
            scores["architecture_md_structure"] = 1.0

        # Current Inputs must list exact data files found
        current_inputs = sections.get("Current Inputs", "")
        listed_paths = section_contains_paths(current_inputs)
        if listed_paths == discovered_data_files and len(listed_paths) == len(discovered_data_files):
            scores["architecture_current_inputs_match"] = 1.0

        # Error Analysis quality: mention missing CSV, exception, and prevention strategy
        error_analysis = sections.get("Error Analysis", "")
        ea_lower = error_analysis.lower()
        has_missing_csv_ref = ("data/new_players.csv" in error_analysis) or ("csv" in ea_lower)
        has_exception_ref = ("filenotfounderror" in ea_lower) or ("no such file" in ea_lower)
        mentions_prevention = any(k in ea_lower for k in ["validat", "exist", "check", "guard", "ensure"])
        if has_missing_csv_ref and has_exception_ref and mentions_prevention:
            scores["architecture_error_analysis_quality"] = 1.0

        # Proposed Architecture: pipeline, directory layout, validation, missing/incorrect handling
        proposed_arch = sections.get("Proposed Architecture", "")
        pa_lower = proposed_arch.lower()
        mentions_pipeline = "pipeline" in pa_lower or "steps" in pa_lower
        mentions_validation = "validat" in pa_lower
        mentions_missing_incorrect = ("missing" in pa_lower) or ("incorrect" in pa_lower) or ("invalid" in pa_lower)
        mentions_dirs = ("data/" in proposed_arch) and ("output/" in proposed_arch)
        if mentions_pipeline and mentions_validation and mentions_missing_incorrect and mentions_dirs:
            scores["architecture_proposed_architecture_quality"] = 1.0

        # CLI Sketch: summarize and email-draft, with input/output paths and defaults
        cli_sketch = sections.get("CLI Sketch", "")
        cs_lower = cli_sketch.lower()
        has_summarize = "summarize" in cs_lower
        has_email_draft = ("email-draft" in cs_lower) or ("email draft" in cs_lower) or ("email_draft" in cs_lower)
        has_output_paths = "output/" in cli_sketch
        has_input_paths = "data/" in cli_sketch
        mentions_default = "default" in cs_lower or "defaults" in cs_lower
        if has_summarize and has_email_draft and has_output_paths and has_input_paths and mentions_default:
            scores["architecture_cli_sketch_quality"] = 1.0

    # Check command diagnostics
    diag_path = workspace / "output" / "command_diagnostics.txt"
    diag_text = read_text_safe(diag_path)
    if diag_text is not None:
        non_empty_lines = [ln.strip() for ln in diag_text.splitlines() if ln.strip() != ""]
        if len(non_empty_lines) == 1:
            line = non_empty_lines[0]
            if ("FileNotFoundError" in line) and ("data/new_players.csv" in line):
                scores["command_diagnostics_exception_captured"] = 1.0

    # Check fan email draft
    email_path = workspace / "output" / "fan_email_draft.txt"
    email_text = read_text_safe(email_path)
    top3 = compute_top3_players_by_war(workspace / "data" / "new_players.json")
    if email_text is not None:
        et_lower = email_text.lower()
        has_weekly = "weekly" in et_lower
        has_spotlight = "spotlight" in et_lower
        has_pilot = any(w in et_lower for w in ["pilot", "piloting", "trial", "test", "testing"])
        has_automated = any(w in et_lower for w in ["automated", "automation"])
        has_local = "local" in et_lower or "locally" in et_lower
        has_group = ("padre" in et_lower) and (("meetup" in et_lower) or ("group" in et_lower))
        if has_weekly and has_spotlight and has_pilot and has_automated and has_local and has_group:
            scores["fan_email_mentions_pilot_weekly_local"] = 1.0

        bullets = get_bullet_lines(email_text)
        if len(bullets) == 3:
            scores["fan_email_has_three_bullets"] = 1.0

        if len(bullets) == 3 and len(top3) == 3:
            all_ok = True
            for i, b in enumerate(bullets):
                player = top3[i]
                name_ok = player["name"] in b
                position_ok = player["position"] in b
                bt = f"{player['bats']}/{player['throws']}"
                bt_ok = bt in b
                war_str = str(player["projected_war"])
                war_ok = war_str in b
                if not (name_ok and position_ok and bt_ok and war_ok):
                    all_ok = False
                    break
            if all_ok:
                scores["fan_email_top3_correct_order_and_fields"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()