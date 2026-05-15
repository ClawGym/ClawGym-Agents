import json
import sys
import subprocess
import re
from pathlib import Path


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _count_words(text: str) -> int:
    return len(re.findall(r'\b\w+\b', text))


def _split_sentences(text: str) -> list:
    # Simple sentence splitter based on . ! ?
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def _compute_expected_tool_progress(workspace: Path):
    # Returns list of strings expected in the log, or None if inputs missing/malformed
    posts_path = workspace / "input" / "forum_posts.json"
    posts = _load_json_safe(posts_path)
    if not isinstance(posts, list):
        return None
    # Replicate the tool's tag derivation
    tags = []
    for p in posts:
        pref = (p.get("style_preference") or "").strip().lower()
        if "+" in pref:
            pref = pref.split("+")[0].strip()
        if pref and pref not in tags:
            tags.append(pref)
    expected = [
        "Mock Palette Tool v0.1",
        "Scanning posts from input/forum_posts.json",
        f"Loaded {len(posts)} posts",
        f"Detected style tags: {', '.join(tags) if tags else '(none)'}",
        "Loading palette presets from input/palette_presets.json",
    ]
    return expected


def _parse_exception_from_log(log_text: str):
    # Attempts to extract exception type and missing path from a Python traceback
    # Returns (exception_type, missing_path) or (None, None)
    exc_type = None
    missing_path = None
    # Look for a final line like: FileNotFoundError: [Errno 2] No such file or directory: 'input/palette_presets.json'
    for line in log_text.splitlines():
        if "FileNotFoundError" in line:
            exc_type = "FileNotFoundError"
            # Try to extract quoted path
            m = re.search(r"No such file or directory:\s*'([^']+)'", line)
            if m:
                missing_path = m.group(1)
            else:
                # Alternative Python might show double quotes
                m2 = re.search(r"No such file or directory:\s*\"([^\"]+)\"", line)
                if m2:
                    missing_path = m2.group(1)
    return exc_type, missing_path


def _find_section_ranges(lines: list, posts_info: list) -> dict:
    # Identify sections labeled with both post id and username
    header_positions = []
    for idx, line in enumerate(lines):
        for p in posts_info:
            if str(p["id"]) in line and p["username"] in line:
                header_positions.append((idx, p["id"]))
    # Deduplicate by first occurrence
    seen = set()
    header_positions_sorted = []
    for idx, pid in sorted(header_positions, key=lambda x: x[0]):
        if pid not in seen:
            seen.add(pid)
            header_positions_sorted.append((idx, pid))
    ranges = {}
    for i, (hidx, pid) in enumerate(header_positions_sorted):
        if i + 1 < len(header_positions_sorted):
            end = header_positions_sorted[i + 1][0]
        else:
            end = len(lines)
        ranges[pid] = (hidx, end)
    return ranges


def _extract_section_text(lines: list, start: int, end: int) -> str:
    body_lines = lines[start + 1:end]
    return "\n".join(body_lines).strip()


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _has_two_concrete_suggestions(text: str) -> bool:
    # Count bullet-like lines
    bullet_count = 0
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(("- ", "* ", "1.", "2.", "3.", "1)", "2)", "3)")):
            bullet_count += 1
    if bullet_count >= 2:
        return True
    # Imperative sentence heuristic
    imperative_verbs = {
        "consider", "try", "use", "add", "opt", "choose", "place", "swap",
        "layer", "invest", "look", "incorporate", "hang", "pair", "zone",
        "divide", "float", "upgrade", "buy", "select", "arrange", "position",
        "pick", "set", "install"
    }
    suggestions = 0
    for s in _split_sentences(text):
        s_clean = s.lstrip("-*0123456789). ").strip()
        if not s_clean:
            continue
        first = s_clean.split()[0].lower()
        if first in imperative_verbs:
            suggestions += 1
    return suggestions >= 2


def _is_budget_aware(text: str) -> bool:
    t = text.lower()
    return any(token in t for token in ["budget", "$", "under", "affordable", "cost", "price", "save"])


def _find_section_content_by_heading(doc: str, heading: str) -> str:
    lines = doc.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        low = stripped.lower()
        if low == heading.lower() or (low.startswith("#") and low.lstrip("#").strip().lower() == heading.lower()):
            start_idx = i
            break
    if start_idx is None:
        return ""
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        l2 = lines[j].strip()
        if l2.startswith("#"):
            end_idx = j
            break
    return "\n".join(lines[start_idx + 1:end_idx]).strip()


def _paragraphs(text: str) -> list:
    paras = []
    cur = []
    for line in text.splitlines():
        if line.strip() == "":
            if cur:
                paras.append("\n".join(cur).strip())
                cur = []
        else:
            cur.append(line)
    if cur:
        paras.append("\n".join(cur).strip())
    return paras


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {}

    # Prepare paths
    log_path = workspace / "output" / "mock_palette_tool.log"
    ea_path = workspace / "output" / "error_analysis.md"
    fr_path = workspace / "output" / "forum_replies.md"
    mn_path = workspace / "output" / "meeting_notes.md"

    # Load artifacts
    log_text = _read_text_safe(log_path)
    ea_text = _read_text_safe(ea_path)
    fr_text = _read_text_safe(fr_path)
    mn_text = _read_text_safe(mn_path)

    # Extract dynamic info from log
    exc_type, missing_path = _parse_exception_from_log(log_text)

    # 1) Tool log checks
    log_has_error = bool(exc_type == "FileNotFoundError" and isinstance(missing_path, str) and missing_path)
    expected_progress = False
    expected_lines = _compute_expected_tool_progress(workspace)
    if log_text and expected_lines:
        expected_progress = all(line in log_text for line in expected_lines)

    scores["mock_tool_log_failure_captured"] = 1.0 if (log_path.exists() and log_has_error) else 0.0
    scores["mock_tool_log_expected_progress"] = 1.0 if (log_path.exists() and expected_progress) else 0.0

    # Repro run: Only award if the log exists; cross-check that reproduction shows same error signature.
    repro_ok = 0.0
    tool_path = workspace / "input" / "mock_palette_tool.py"
    if log_path.exists() and tool_path.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(tool_path)],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=25
            )
            combined = (proc.stdout or "") + (proc.stderr or "")
            exc2, miss2 = _parse_exception_from_log(combined)
            if exc2 == exc_type and miss2 == missing_path and exc2 == "FileNotFoundError":
                repro_ok = 1.0
        except Exception:
            repro_ok = 0.0
    scores["repro_run_matches_log_error"] = repro_ok

    # 2) error_analysis.md checks
    # Must include the exact exception type and missing file/path mentioned in the error (from the log)
    ea_has_exc_and_path = False
    if ea_text and log_path.exists() and log_has_error:
        ea_has_exc_and_path = (exc_type in ea_text and missing_path in ea_text)

    # Must include reproduction command used (presence of python and input/mock_palette_tool.py)
    ea_has_repro_cmd = ("input/mock_palette_tool.py" in ea_text and ("python " in ea_text.lower() or "python3" in ea_text.lower()))

    # 2–3 sentence explanation: find a paragraph with 2 or 3 sentences
    explanation_ok = 0.0
    if ea_text:
        paras = _paragraphs(ea_text)
        found_2to3 = False
        for para in paras:
            # skip bullet lists
            lines = [l for l in para.splitlines() if l.strip()]
            if any(l.strip().startswith(("-", "*", "1.", "2.", "3.")) for l in lines):
                continue
            sents = _split_sentences(para)
            if 2 <= len(sents) <= 3:
                found_2to3 = True
                break
        explanation_ok = 1.0 if found_2to3 else 0.0

    # Two actionable next steps (bulleted or enumerated lines)
    next_steps_count = 0
    for line in ea_text.splitlines():
        ls = line.strip()
        if ls.startswith(("- ", "* ", "1.", "2.", "3.", "1)", "2)", "3)")):
            next_steps_count += 1
    ea_has_two_next_steps = 1.0 if next_steps_count >= 2 else 0.0

    scores["error_analysis_exception_and_path"] = 1.0 if (ea_path.exists() and ea_has_exc_and_path) else 0.0
    scores["error_analysis_reproduction_command"] = 1.0 if (ea_path.exists() and ea_has_repro_cmd) else 0.0
    scores["error_analysis_explanation_2_to_3_sentences"] = 1.0 if (ea_path.exists() and explanation_ok == 1.0) else 0.0
    scores["error_analysis_two_next_steps"] = 1.0 if (ea_path.exists() and ea_has_two_next_steps == 1.0) else 0.0

    # 3) forum_replies.md checks
    posts_info = [
        {"id": 101, "username": "HandyDad"},
        {"id": 102, "username": "StudioCat"},
        {"id": 103, "username": "PlantNerd"},
    ]
    fr_lines = fr_text.splitlines() if fr_text else []
    section_ranges = _find_section_ranges(fr_lines, posts_info)

    for p in posts_info:
        pid = p["id"]
        uname = p["username"]
        key_label = f"forum_reply_section_labeled_{pid}"
        key_greet = f"forum_reply_greeting_{pid}"
        key_question = f"forum_reply_has_question_{pid}"
        key_suggestions = f"forum_reply_two_suggestions_{pid}"
        key_tool = f"forum_reply_tool_status_{pid}"
        key_wordcount = f"forum_reply_word_count_{pid}"
        key_budget = f"forum_reply_budget_aware_{pid}"

        labeled = 1.0 if pid in section_ranges else 0.0
        scores[key_label] = 1.0 if (fr_path.exists() and labeled == 1.0) else 0.0

        section_text = ""
        if pid in section_ranges:
            start, end = section_ranges[pid]
            section_text = _extract_section_text(fr_lines, start, end)

        greet_ok = 0.0
        if section_text:
            first_line = _first_nonempty_line(section_text)
            if first_line.startswith(f"@{uname}"):
                greet_ok = 1.0
        scores[key_greet] = 1.0 if (fr_path.exists() and greet_ok == 1.0) else 0.0

        has_question = 1.0 if ("?" in section_text) else 0.0
        scores[key_question] = 1.0 if (fr_path.exists() and has_question == 1.0) else 0.0

        has_two = 1.0 if _has_two_concrete_suggestions(section_text) else 0.0
        scores[key_suggestions] = 1.0 if (fr_path.exists() and has_two == 1.0) else 0.0

        # Tool status note must acknowledge unavailability and include the precise exc_type and missing_path from the log
        has_tool_note = 0.0
        if fr_path.exists() and log_path.exists() and log_has_error:
            t = section_text
            low = t.lower()
            palette_tool_unavail = ("palette" in low and "tool" in low and ("temporar" in low or "unavailable" in low))
            includes_exc_and_path = (exc_type in t and missing_path in t)
            if palette_tool_unavail and includes_exc_and_path:
                has_tool_note = 1.0
        scores[key_tool] = has_tool_note

        wc = _count_words(section_text)
        wc_ok = 1.0 if (120 <= wc <= 180) else 0.0
        scores[key_wordcount] = 1.0 if (fr_path.exists() and wc_ok == 1.0) else 0.0

        budget_ok = 1.0 if _is_budget_aware(section_text) else 0.0
        scores[key_budget] = 1.0 if (fr_path.exists() and budget_ok == 1.0) else 0.0

    # 4) meeting_notes.md checks
    summary_content = _find_section_content_by_heading(mn_text, "Summary") if mn_text else ""
    decisions_content = _find_section_content_by_heading(mn_text, "Decisions") if mn_text else ""
    action_items_content = _find_section_content_by_heading(mn_text, "Action Items") if mn_text else ""

    has_sections = all([
        mn_path.exists(),
        bool(summary_content.strip()),
        bool(decisions_content.strip()),
        bool(action_items_content.strip()),
    ])
    scores["meeting_notes_has_sections"] = 1.0 if has_sections else 0.0

    # Check that Action Items include owners and due details per transcript
    designer_thursday = 0.0
    client_sunday = 0.0
    owners_present = 0
    if action_items_content:
        for line in action_items_content.splitlines():
            l = line.strip()
            llow = l.lower()
            if l:
                if "designer" in llow:
                    owners_present += 1
                if "client" in llow:
                    owners_present += 1
                if "designer" in llow and "thursday" in llow:
                    designer_thursday = 1.0
                if "client" in llow and "sunday" in llow:
                    client_sunday = 1.0
    scores["meeting_notes_designer_due_thursday"] = 1.0 if (mn_path.exists() and designer_thursday == 1.0) else 0.0
    scores["meeting_notes_client_due_sunday"] = 1.0 if (mn_path.exists() and client_sunday == 1.0) else 0.0
    # At least two owner-tagged items (Designer/Client)
    scores["meeting_notes_action_items_have_owners"] = 1.0 if (mn_path.exists() and owners_present >= 2) else 0.0

    # Ensure JSON serializable floats
    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()