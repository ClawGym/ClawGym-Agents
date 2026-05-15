import json
import re
import sys;
import hashlib
from pathlib import Path
from datetime import datetime


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _compute_sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _parse_agenda(agenda_text: str):
    """
    Returns (date_str, bullets) where bullets are verbatim lines starting with '- '.
    Date must be in first heading line like '# Agenda - YYYY-MM-DD'
    """
    if not isinstance(agenda_text, str):
        return None, []
    lines = agenda_text.splitlines()
    date_str = None
    # Find first heading line
    for line in lines:
        if line.strip().startswith("#"):
            m = re.search(r"#\s*Agenda\s*-\s*(\d{4}-\d{2}-\d{2})", line.strip())
            if m:
                date_str = m.group(1)
            break
    bullets = [ln for ln in lines if ln.startswith("- ")]
    return date_str, bullets


def _parse_config_yaml(yaml_text: str):
    """
    Minimal parser for the specific config structure.
    Returns dict: { "team": [{"name": str, "owns_keywords": [str, ...]}, ...], "fallback_owner": str }
    """
    result = {"team": [], "fallback_owner": None}
    if not isinstance(yaml_text, str):
        return None
    lines = yaml_text.splitlines()
    # Extract fallback_owner
    for ln in lines:
        s = ln.strip()
        if s.startswith("fallback_owner:"):
            val = s.split(":", 1)[1].strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            result["fallback_owner"] = val
    # Extract team entries
    i = 0
    n = len(lines)
    while i < n:
        s = lines[i].strip()
        if s.startswith("- name:"):
            name = s.split(":", 1)[1].strip()
            if (name.startswith('"') and name.endswith('"')) or (name.startswith("'") and name.endswith("'")):
                name = name[1:-1]
            keywords = []
            j = i + 1
            while j < n:
                sj = lines[j].strip()
                if sj.startswith("- name:") or sj.startswith("fallback_owner:"):
                    break
                if sj.startswith("owns_keywords:"):
                    after = sj.split(":", 1)[1].strip()
                    vals = []
                    if after.startswith("[") and after.endswith("]"):
                        inner = after[1:-1].strip()
                        if inner:
                            parts = [p.strip() for p in inner.split(",")]
                            for p in parts:
                                p2 = p
                                if (p2.startswith('"') and p2.endswith('"')) or (p2.startswith("'") and p2.endswith("'")):
                                    p2 = p2[1:-1]
                                vals.append(p2)
                    keywords = vals
                j += 1
            result["team"].append({"name": name, "owns_keywords": keywords})
            i = j
            continue
        i += 1
    # Basic validation
    if result["fallback_owner"] is None or not isinstance(result["team"], list):
        return None
    for member in result["team"]:
        if "name" not in member or "owns_keywords" not in member:
            return None
        if not isinstance(member["owns_keywords"], list):
            return None
    return result


def _assign_owner(item_text: str, config: dict) -> str:
    """
    Assigns owner based on first matching keyword in team order (case-insensitive).
    """
    text_l = item_text.lower()
    for member in config["team"]:
        for kw in member.get("owns_keywords", []):
            if kw is None:
                continue
            if kw.lower() in text_l:
                return member["name"]
    return config["fallback_owner"]


def _extract_first_heading_and_codeblock(md_text: str):
    """
    Returns (heading_text, codeblock_text) from a Markdown string.
    - heading_text is the first Markdown heading text outside code blocks (line starting with 1-6 '#' and a space), without the leading hashes.
    - codeblock_text is the first fenced code block including fences.
    """
    if not isinstance(md_text, str):
        return None, None
    lines = md_text.splitlines()
    in_code = False
    heading_text = None
    codeblock_text = None
    code_started = False
    code_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_code:
                in_code = True
                if codeblock_text is None:
                    code_started = True
                    code_lines = [line]
                else:
                    code_started = False
            else:
                if code_started:
                    code_lines.append(line)
                    codeblock_text = "\n".join(code_lines)
                    code_started = False
                in_code = False
            continue
        if in_code:
            if code_started:
                code_lines.append(line)
            continue
        if heading_text is None and re.match(r"^\s*#{1,6}\s+.+", line):
            m = re.match(r"^\s*(#{1,6})\s+(.+)", line)
            if m:
                heading_text = m.group(2).strip()
    return heading_text, codeblock_text


def _get_notes_sections(notes_text: str):
    """
    Parse notes into:
    - first_heading_line
    - sections dict mapping section heading (like 'Agenda') to content lines list
    - order list of section headings as they appear
    """
    if not isinstance(notes_text, str):
        return None, {}, []
    lines = notes_text.splitlines()
    first_heading_line = lines[0].strip() if lines else ""
    sections = {}
    order = []
    current = None
    for line in lines:
        if line.startswith("## "):
            title = line[3:].strip()
            current = title
            order.append(title)
            sections[current] = []
        else:
            if current is not None:
                sections[current].append(line)
    return first_heading_line, sections, order


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "state_hash_matches_agenda": 0.0,
        "download_readme_file_present": 0.0,
        "metadata_fields_valid_and_consistent": 0.0,
        "notes_file_for_agenda_date_present": 0.0,
        "notes_first_heading_includes_date": 0.0,
        "notes_sections_order_and_names": 0.0,
        "notes_agenda_section_verbatim_bullets": 0.0,
        "notes_action_items_assigned_correctly": 0.0,
        "markdown_tip_includes_readme_heading": 0.0,
        "markdown_tip_includes_first_code_block_or_excerpt": 0.0,
        "run_log_exists_and_nonempty": 0.0,
    }

    # Paths
    agenda_path = workspace / "input" / "agenda.md"
    config_path = workspace / "input" / "config.yaml"
    state_hash_path = workspace / "out" / "state" / "agenda.sha256"
    download_readme_path = workspace / "out" / "downloads" / "commonmark_README.md"
    metadata_json_path = workspace / "out" / "metadata" / "commonmark_source.json"
    logs_path = workspace / "out" / "logs" / "run.log"

    # Load agenda and compute hash
    agenda_bytes = _read_bytes(agenda_path)
    agenda_text = None
    if agenda_bytes is not None:
        agenda_text = agenda_bytes.decode("utf-8", errors="replace")
        agenda_hash = _compute_sha256_bytes(agenda_bytes)
        state_hash_text = _read_text(state_hash_path)
        if state_hash_text is not None:
            state_hash = state_hash_text.strip()
            if state_hash == agenda_hash:
                scores["state_hash_matches_agenda"] = 1.0
            else:
                scores["state_hash_matches_agenda"] = 0.0
        else:
            scores["state_hash_matches_agenda"] = 0.0

    # Downloaded readme presence
    readme_text = _read_text(download_readme_path)
    if readme_text is not None and len(readme_text) > 0:
        scores["download_readme_file_present"] = 1.0

    # Metadata validation
    metadata_ok = False
    meta_text = _read_text(metadata_json_path)
    if meta_text is not None:
        try:
            meta = json.loads(meta_text)
            required_fields = {"source_id", "fetched_at", "sha256", "bytes"}
            if isinstance(meta, dict) and required_fields.issubset(meta.keys()):
                source_id_ok = meta["source_id"] == "github:commonmark/commonmark-spec:README.md"
                fetched_at_ok = _is_iso8601(meta["fetched_at"])
                sha_ok = isinstance(meta["sha256"], str) and len(meta["sha256"]) == 64 and all(
                    c in "0123456789abcdef" for c in meta["sha256"].lower()
                )
                bytes_ok = isinstance(meta["bytes"], int) and meta["bytes"] >= 0
                file_consistent = False
                if readme_text is not None:
                    rb = readme_text.encode("utf-8")
                    calc_sha = _compute_sha256_bytes(rb)
                    file_consistent = (calc_sha == meta["sha256"]) and (len(rb) == meta["bytes"])
                metadata_ok = source_id_ok and fetched_at_ok and sha_ok and bytes_ok and file_consistent
        except Exception:
            metadata_ok = False
    scores["metadata_fields_valid_and_consistent"] = 1.0 if metadata_ok else 0.0

    # Parse agenda date and bullets
    agenda_date, agenda_bullets = _parse_agenda(agenda_text) if agenda_text is not None else (None, [])

    # Notes file presence
    notes_present = False
    notes_text = None
    if agenda_date:
        notes_path = workspace / "out" / "notes" / f"{agenda_date}-meeting.md"
        notes_text = _read_text(notes_path)
        if notes_text is not None and len(notes_text) > 0:
            notes_present = True
            scores["notes_file_for_agenda_date_present"] = 1.0

    # Notes structure checks
    if notes_present:
        first_heading_line, sections, order = _get_notes_sections(notes_text)
        # First heading contains date and "Meeting Notes"
        if first_heading_line.startswith("#") and "Meeting Notes" in first_heading_line and (agenda_date in first_heading_line):
            scores["notes_first_heading_includes_date"] = 1.0
        else:
            scores["notes_first_heading_includes_date"] = 0.0

        # Sections order and names
        try:
            idx_agenda = order.index("Agenda")
            idx_actions = order.index("Action Items")
            idx_tip = order.index("Markdown Tip")
            if idx_agenda < idx_actions < idx_tip:
                scores["notes_sections_order_and_names"] = 1.0
        except Exception:
            scores["notes_sections_order_and_names"] = 0.0

        # Agenda section verbatim bullets
        agenda_section_lines = sections.get("Agenda", [])
        agenda_section_bullets = [ln for ln in agenda_section_lines if ln.startswith("- ")]
        if agenda_bullets and agenda_section_bullets and len(agenda_bullets) == len(agenda_section_bullets):
            verbatim_ok = all(a == b for a, b in zip(agenda_bullets, agenda_section_bullets))
            scores["notes_agenda_section_verbatim_bullets"] = 1.0 if verbatim_ok else 0.0
        else:
            scores["notes_agenda_section_verbatim_bullets"] = 0.0

        # Action items assignments and format
        config_text = _read_text(config_path)
        config = _parse_config_yaml(config_text) if config_text is not None else None
        action_section_lines = sections.get("Action Items", [])
        action_bullets = [ln for ln in action_section_lines if ln.startswith("- ")]
        if config is not None and agenda_bullets and len(action_bullets) == len(agenda_bullets):
            all_ok = True
            for idx, orig in enumerate(agenda_bullets):
                item_text = orig[2:].strip()
                owner = _assign_owner(item_text, config)
                expected_line = f"- {owner}: Follow up on — {item_text}"
                if action_bullets[idx] != expected_line:
                    all_ok = False
                    break
            scores["notes_action_items_assigned_correctly"] = 1.0 if all_ok else 0.0
        else:
            scores["notes_action_items_assigned_correctly"] = 0.0

        # Markdown Tip content checks
        tip_lines = sections.get("Markdown Tip", [])
        tip_text = "\n".join(tip_lines) if tip_lines is not None else ""
        if readme_text is not None:
            heading_text, codeblock_text = _extract_first_heading_and_codeblock(readme_text)
            # Heading presence
            if heading_text and (heading_text in tip_text):
                scores["markdown_tip_includes_readme_heading"] = 1.0
            else:
                scores["markdown_tip_includes_readme_heading"] = 0.0
            # Code block or excerpt
            if codeblock_text:
                scores["markdown_tip_includes_first_code_block_or_excerpt"] = 1.0 if codeblock_text in tip_text else 0.0
            else:
                excerpt = readme_text[:120]
                scores["markdown_tip_includes_first_code_block_or_excerpt"] = 1.0 if excerpt in tip_text else 0.0
        else:
            scores["markdown_tip_includes_readme_heading"] = 0.0
            scores["markdown_tip_includes_first_code_block_or_excerpt"] = 0.0

    # Logging check
    log_text = _read_text(logs_path)
    if log_text is not None and log_text.strip() != "":
        scores["run_log_exists_and_nonempty"] = 1.0
    else:
        scores["run_log_exists_and_nonempty"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()