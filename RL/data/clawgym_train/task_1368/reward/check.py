import json
import re
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _list_md_files(input_dir: Path) -> List[Path]:
    if not input_dir.exists():
        return []
    return sorted([p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() == ".md"])


def _parse_front_matter(lines: List[str]) -> Dict[str, str]:
    fm = {}
    if len(lines) >= 1 and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            line = lines[i].strip()
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()
            i += 1
    return fm


def _parse_emotions(line: str) -> List[Dict[str, Any]]:
    emotions = []
    if ":" in line:
        after = line.split(":", 1)[1].strip()
    else:
        after = line.strip()
    parts = [p.strip() for p in after.split(",") if p.strip()]
    for p in parts:
        m = re.match(r'^(.+?)\s*\((\d+)\)\s*$', p)
        if m:
            name = m.group(1).strip()
            try:
                intensity = int(m.group(2))
            except Exception:
                continue
            emotions.append({"name": name, "intensity": intensity})
    return emotions


def _collect_bullets(start_index: int, lines: List[str]) -> List[str]:
    items = []
    i = start_index + 1
    while i < len(lines):
        s = lines[i].rstrip("\n")
        if s.strip() == "":
            break
        if s.strip().endswith(":") and not s.strip().startswith(("-", "*")):
            break
        if s.lstrip().startswith("- ") or s.lstrip().startswith("* "):
            item = s.lstrip()[2:].strip()
            items.append(item)
        else:
            break
        i += 1
    return items


def _parse_expected_entry(md_text: str, source_filename: str) -> Dict[str, Any]:
    lines = md_text.splitlines()
    fm = _parse_front_matter(lines)
    date = fm.get("date", "").strip()
    client = fm.get("client", "").strip()

    emotions: List[Dict[str, Any]] = []
    triggers: List[str] = []
    coping: List[str] = []
    poem_lines: List[str] = []

    for idx, raw in enumerate(lines):
        line = raw.strip()
        if line.lower().startswith("feelings:"):
            emotions = _parse_emotions(raw)
        elif line.strip() == "Triggers:":
            triggers = _collect_bullets(idx, lines)
        elif line.strip() == "Coping:":
            coping = _collect_bullets(idx, lines)
        elif line.strip() == "Poem lines:":
            poem_lines = _collect_bullets(idx, lines)

    return {
        "date": date,
        "client": client,
        "emotions": emotions,
        "triggers": triggers,
        "coping": coping,
        "poem_lines": poem_lines,
        "source_filename": source_filename,
    }


def _top_emotion_names(emotions: List[Dict[str, Any]]) -> List[str]:
    if not emotions:
        return []
    max_val = max((e.get("intensity", 0) for e in emotions), default=None)
    if max_val is None:
        return []
    return [e.get("name", "") for e in emotions if e.get("intensity", 0) == max_val]


def _sentences_count(text: str) -> int:
    sentences = re.findall(r'[^.!?]+[.!?]', text, flags=re.DOTALL)
    if not sentences:
        parts = [p.strip() for p in re.split(r'[.!?]\s*', text) if p.strip()]
        return len(parts)
    return len([s for s in (seg.strip() for seg in sentences) if s])


def _extract_sections(text: str, headers: List[str]) -> Optional[Dict[str, str]]:
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    idxs = []
    for h in headers:
        try:
            i = lines.index(h)
        except ValueError:
            return None
        idxs.append(i)
    if any(idxs[i] >= idxs[i + 1] for i in range(len(idxs) - 1)):
        return None
    sections: Dict[str, str] = {}
    for i, h in enumerate(headers):
        start = idxs[i] + 1
        end = idxs[i + 1] if i + 1 < len(headers) else len(lines)
        content = "\n".join(lines[start:end]).strip()
        sections[h] = content
    return sections


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_updated_template_path": 0.0,
        "reply_template_valid": 0.0,
        "pipeline_runs_once": 0.0,
        "entries_json_parsed_and_contains_expected": 0.0,
        "entries_json_sorted": 0.0,
        "replies_valid": 0.0,
        "meeting_notes_valid": 0.0,
        "idempotence_rerun_no_duplicates": 0.0,
        "processed_index_valid": 0.0,
    }

    # Load config
    cfg_path = workspace / "config" / "automation.json"
    cfg = _read_json(cfg_path) or {}
    templates_cfg = cfg.get("templates", {})
    reply_template_rel = templates_cfg.get("reply")
    # Check config updated to point to rewritten template
    if isinstance(reply_template_rel, str) and reply_template_rel == "templates/reply_template.txt":
        scores["config_updated_template_path"] = 1.0

    # Validate reply_template.txt strictly
    reply_template_path = workspace / "templates" / "reply_template.txt"
    draft_template_path = workspace / "templates" / "reply_draft.txt"
    tmpl_text = _read_text(reply_template_path)
    draft_text = _read_text(draft_template_path) or ""
    breathing_sentence = "If it feels right, place a hand on your heart and take three gentle breaths."
    if (
        tmpl_text is not None
        and 3 <= _sentences_count(tmpl_text) <= 5
        and breathing_sentence in tmpl_text
        and "{{client}}" in tmpl_text
        and "{{date}}" in tmpl_text
        and "{{top_emotion}}" in tmpl_text
        and tmpl_text.strip() != draft_text.strip()
    ):
        scores["reply_template_valid"] = 1.0

    # Prepare expected data from input markdown files
    input_dir = workspace / "input" / "journals" / "incoming"
    input_files = _list_md_files(input_dir)
    expected_entries: List[Dict[str, Any]] = []
    for p in input_files:
        t = _read_text(p)
        if t is None:
            continue
        expected_entries.append(_parse_expected_entry(t, p.name))
    expected_entries.sort(key=lambda e: e.get("date", ""))

    # Run pipeline once
    pipeline_path = workspace / "scripts" / "pipeline.py"
    ran_ok = False
    if pipeline_path.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(pipeline_path), "--once"],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
            )
            ran_ok = proc.returncode == 0
        except Exception:
            ran_ok = False

    # Load outputs after first run
    out_entries_path = workspace / "outputs" / "structured" / "entries.json"
    entries = _read_json(out_entries_path)
    entries_valid_full = False
    sorted_ok = False
    if isinstance(entries, list) and entries and expected_entries:
        by_src = {e.get("source_filename"): e for e in entries if isinstance(e, dict)}
        match_count = 0
        for exp in expected_entries:
            src = exp["source_filename"]
            got = by_src.get(src)
            if not isinstance(got, dict):
                continue
            date_ok = got.get("date") == exp.get("date")
            client_ok = got.get("client") == exp.get("client")
            emotions_ok = isinstance(got.get("emotions"), list) and got.get("emotions") == exp.get("emotions")
            triggers_ok = isinstance(got.get("triggers"), list) and got.get("triggers") == exp.get("triggers")
            coping_ok = isinstance(got.get("coping"), list) and got.get("coping") == exp.get("coping")
            poem_ok = isinstance(got.get("poem_lines"), list) and got.get("poem_lines") == exp.get("poem_lines")
            if date_ok and client_ok and emotions_ok and triggers_ok and coping_ok and poem_ok:
                match_count += 1
        entries_valid_full = (match_count == len(expected_entries))
        dates = [e.get("date", "") for e in entries]
        sorted_ok = dates == sorted(dates)
    scores["entries_json_parsed_and_contains_expected"] = 1.0 if entries_valid_full else 0.0
    scores["entries_json_sorted"] = 1.0 if (entries_valid_full and sorted_ok) else 0.0

    # Validate replies
    replies_dir = workspace / "outputs" / "replies"
    signature = ""
    try:
        signature = cfg.get("reply", {}).get("signature", "")
    except Exception:
        signature = ""
    replies_ok_full = False
    if expected_entries:
        ok_count = 0
        for exp in expected_entries:
            base = Path(exp["source_filename"]).stem
            reply_path = replies_dir / f"{base}_reply.txt"
            txt = _read_text(reply_path)
            if txt is None:
                continue
            lines = [ln.rstrip("\n") for ln in txt.splitlines()]
            first_non_empty = next((ln for ln in lines if ln.strip() != ""), "")
            hi_ok = first_non_empty == "Hi A."
            ems = exp.get("emotions", [])
            top_names = _top_emotion_names(ems)
            body = "\n".join(lines)
            emotion_ok = any((name and (name.lower() in body.lower())) for name in top_names) if top_names else False
            breathing_ok = breathing_sentence in body
            last_non_empty = ""
            for ln in reversed(lines):
                if ln.strip() != "":
                    last_non_empty = ln
                    break
            signature_ok = (signature != "") and (last_non_empty == signature)
            if hi_ok and emotion_ok and breathing_ok and signature_ok:
                ok_count += 1
        replies_ok_full = (ok_count == len(expected_entries)) if expected_entries else False
    scores["replies_valid"] = 1.0 if replies_ok_full else 0.0

    # Validate meeting notes
    notes_path = workspace / "outputs" / "meetings" / "notes.md"
    notes_text = _read_text(notes_path) or ""
    notes_ok = False
    if notes_text.strip() and expected_entries:
        section_headers = [
            "Client",
            "Dates covered",
            "Dominant emotions",
            "Triggers mentioned",
            "Suggested agenda",
        ]
        sections = _extract_sections(notes_text, section_headers)
        if sections is not None:
            client_ok = sections["Client"].strip() == "A."
            dates = [e["date"] for e in expected_entries if e.get("date")]
            min_date = min(dates) if dates else ""
            max_date = max(dates) if dates else ""
            dates_str = f"{min_date} to {max_date}" if min_date and max_date else ""
            dates_ok = sections["Dates covered"].strip() == dates_str

            # Dominant emotions by average, top two rounded
            sums: Dict[str, List[int]] = {}
            for e in expected_entries:
                for em in e.get("emotions", []):
                    name = em.get("name")
                    val = em.get("intensity")
                    if isinstance(name, str) and isinstance(val, int):
                        sums.setdefault(name, []).append(val)
            avgs: Dict[str, float] = {k: (sum(v) / len(v)) for k, v in sums.items() if v}
            sorted_avgs = sorted(avgs.items(), key=lambda kv: kv[1], reverse=True)
            top_two = [(name, int(round(avg))) for name, avg in sorted_avgs[:2]]
            dom_txt = sections["Dominant emotions"]
            dominants_ok = True
            for name, rounded_val in top_two:
                if (name.lower() not in dom_txt.lower()) or (str(rounded_val) not in dom_txt):
                    dominants_ok = False
                    break

            # Triggers mentioned: unique bullet list including all triggers from expected
            expected_triggers_set = set()
            for e in expected_entries:
                expected_triggers_set.update(e.get("triggers", []))
            trig_section = sections["Triggers mentioned"]
            bullet_lines = [ln.strip() for ln in trig_section.splitlines() if ln.strip().startswith(("- ", "* "))]
            bullets = [ln[2:].strip() for ln in bullet_lines]
            triggers_all_present = expected_triggers_set.issubset(set(bullets))
            triggers_unique = len(bullets) == len(set(bullets)) and len(bullets) >= len(expected_triggers_set)

            # Suggested agenda: at least 3 bullets and includes phrase "breathing practice"
            agenda_section = sections["Suggested agenda"]
            agenda_bullets = [ln.strip() for ln in agenda_section.splitlines() if ln.strip().startswith(("- ", "* "))]
            agenda_count_ok = len(agenda_bullets) >= 3
            breathing_phrase_ok = ("breathing practice" in agenda_section.lower())

            if client_ok and dates_ok and dominants_ok and triggers_all_present and triggers_unique and agenda_count_ok and breathing_phrase_ok:
                notes_ok = True
    scores["meeting_notes_valid"] = 1.0 if notes_ok else 0.0

    # Gate pipeline_runs_once: only credit if run succeeded and core outputs are correct
    if ran_ok and scores["entries_json_parsed_and_contains_expected"] == 1.0 and scores["entries_json_sorted"] == 1.0 and scores["replies_valid"] == 1.0 and scores["meeting_notes_valid"] == 1.0 and scores["config_updated_template_path"] == 1.0 and scores["reply_template_valid"] == 1.0:
        scores["pipeline_runs_once"] = 1.0
    else:
        scores["pipeline_runs_once"] = 0.0

    # Processed index validation: strict and gated on core correctness
    proc_idx_ok = 0.0
    proc_idx_path = None
    try:
        watch_cfg = cfg.get("watch", {}) if isinstance(cfg, dict) else {}
        proc_idx_rel = watch_cfg.get("processed_index") or "outputs/state/processed_index.json"
        proc_idx_path = workspace / proc_idx_rel
    except Exception:
        proc_idx_path = workspace / "outputs" / "state" / "processed_index.json"
    proc_idx = _read_json(proc_idx_path) or {}
    if scores["entries_json_parsed_and_contains_expected"] == 1.0 and scores["replies_valid"] == 1.0 and scores["meeting_notes_valid"] == 1.0:
        processed_list = proc_idx.get("processed")
        last_run = proc_idx.get("last_run")
        if isinstance(processed_list, list) and isinstance(last_run, str) and len(last_run) >= 10:
            no_dups = len(processed_list) == len(set(processed_list))
            exp_names = [e["source_filename"] for e in expected_entries]
            contains_all = set(exp_names).issubset(set(processed_list))
            if no_dups and contains_all:
                proc_idx_ok = 1.0
    scores["processed_index_valid"] = proc_idx_ok

    # Idempotence check: only evaluate if core success so far
    idempotent_ok = 0.0
    if scores["pipeline_runs_once"] == 1.0:
        # Capture baseline entries and replies
        out_entries_path = workspace / "outputs" / "structured" / "entries.json"
        baseline_entries = _read_json(out_entries_path)
        baseline_replies: Dict[str, str] = {}
        replies_dir = workspace / "outputs" / "replies"
        if replies_dir.exists():
            for p in replies_dir.iterdir():
                if p.is_file() and p.name.endswith("_reply.txt"):
                    txt = _read_text(p)
                    if txt is not None:
                        baseline_replies[p.name] = txt
        # Run again
        try:
            proc2 = subprocess.run(
                [sys.executable, str(pipeline_path), "--once"],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
            )
            if proc2.returncode == 0:
                entries2 = _read_json(out_entries_path)
                replies_after: Dict[str, str] = {}
                if replies_dir.exists():
                    for p in replies_dir.iterdir():
                        if p.is_file() and p.name.endswith("_reply.txt"):
                            txt = _read_text(p)
                            if txt is not None:
                                replies_after[p.name] = txt
                entries2_ok = False
                if isinstance(baseline_entries, list) and isinstance(entries2, list):
                    srcs_before = [e.get("source_filename") for e in baseline_entries if isinstance(e, dict)]
                    srcs_after = [e.get("source_filename") for e in entries2 if isinstance(e, dict)]
                    entries2_ok = (len(srcs_after) == len(srcs_before)) and (len(srcs_after) == len(set(srcs_after)))
                replies_ok = False
                if baseline_replies:
                    names_before = set(baseline_replies.keys())
                    names_after = set(replies_after.keys())
                    if names_before == names_after:
                        contents_ok = all(baseline_replies[n] == replies_after.get(n, "") for n in names_before)
                        replies_ok = contents_ok
                idempotent_ok = 1.0 if (entries2_ok and replies_ok) else 0.0
        except Exception:
            idempotent_ok = 0.0
    scores["idempotence_rerun_no_duplicates"] = idempotent_ok

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()