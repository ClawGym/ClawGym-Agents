import json
import sys
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


BASELINE_KEYNOTE_MD = """# Keynote: From Metrics to Moments — Inclusion That Scales

## Opening
- Why inclusive practices accelerate outcomes and trust
- Story: turning participation feedback into product change

## Case Study: Hiring Pathways Program
- Context: outreach, mentorship, and team training
- Outcome: increased candidate diversity and higher retention

## Metrics That Matter
- Participation rates by ERG
- Accessibility requests fulfilled
- Sentiment shifts (pre/post)

## What Helped
- Accessible templates and captioned demos
- Language support for participant materials

## Call to Action
- Start small: one inclusive default in your workflow this week
- Share your learnings

## Appendix: Tech Environment (to be auto-filled)
<!-- APPENDIX_TECH_ENV_START -->
[This section will be auto-filled with a summarized system snapshot highlighting inclusive tooling for demonstration reproducibility.]
<!-- APPENDIX_TECH_ENV_END -->
"""


def read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def parse_probe_log(text: str) -> Dict:
    sections: Dict[str, List[str]] = {}
    current_section: Optional[str] = None
    start_seen = False
    end_seen = False
    timestamp: Optional[str] = None

    lines = text.splitlines()
    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if line.strip() == "== PROBE START ==":
            start_seen = True
            continue
        if line.strip() == "== PROBE END ==":
            end_seen = True
            current_section = None
            continue
        ts_match = re.match(r"^\s*Timestamp:\s*(.+)\s*$", line)
        if ts_match and timestamp is None:
            timestamp = ts_match.group(1).strip()
        sec_match = re.match(r"^\s*==\s*([A-Z_]+)\s*==\s*$", line)
        if sec_match:
            current_section = sec_match.group(1).strip()
            sections[current_section] = []
            continue
        if current_section is not None:
            sections[current_section].append(line)

    return {
        "sections": sections,
        "start_seen": start_seen,
        "end_seen": end_seen,
        "timestamp": timestamp,
    }


def compute_statuses(parsed: Dict) -> Dict[str, str]:
    sections: Dict[str, List[str]] = parsed.get("sections", {})
    # OS
    os_id = "Unknown"
    for l in sections.get("OS", []):
        m = re.match(r"^\s*OS_PRETTY_NAME:\s*(.+)\s*$", l)
        if m:
            val = m.group(1).strip()
            if val:
                os_id = val
                break
    if os_id == "Unknown":
        for l in sections.get("OS", []):
            m = re.match(r"^\s*UNAME:\s*(.+)\s*$", l)
            if m:
                val = m.group(1).strip()
                if val:
                    os_id = val
                    break

    # LOCALE
    default_lang = "Unknown"
    locale_lines = sections.get("LOCALE", [])
    if any(x.strip().startswith("ERROR:") for x in locale_lines):
        default_lang = "Unknown"
    else:
        found_lang_env = False
        for l in locale_lines:
            if l.strip().startswith("LANG_ENV:"):
                val = l.split(":", 1)[1].strip() if ":" in l else ""
                found_lang_env = True
                default_lang = val if val else "Unknown"
                break
        if not found_lang_env:
            for l in locale_lines:
                if l.startswith("LANG="):
                    val = l.split("=", 1)[1].strip()
                    default_lang = val if val else "Unknown"
                    break

    # LOCALE_LIST
    ll_lines = sections.get("LOCALE_LIST", [])
    if any(x.strip().startswith("ERROR:") for x in ll_lines):
        en_avail = "Unknown"
        es_avail = "Unknown"
    else:
        en_avail = "Found" if any(x.strip() == "en_US.UTF-8" for x in ll_lines) else "Not Found"
        es_avail = "Found" if any(x.strip() == "es_ES.UTF-8" for x in ll_lines) else "Not Found"

    # TTS (espeak-ng)
    tts_lines = sections.get("TTS", [])
    if any(x.strip().startswith("ERROR:") for x in tts_lines):
        tts = "Unknown"
    else:
        tts = "Unknown"
        for l in tts_lines:
            if l.startswith("espeak-ng:"):
                rest = l.split(":", 1)[1].strip()
                if rest.endswith("NOT FOUND"):
                    tts = "Absent"
                else:
                    tts = "Present" if rest else "Unknown"
                break

    # CAPTION (ffmpeg)
    cap_lines = sections.get("CAPTION", [])
    if any(x.strip().startswith("ERROR:") for x in cap_lines):
        caption = "Unknown"
    else:
        caption = "Unknown"
        for l in cap_lines:
            if l.startswith("ffmpeg:"):
                rest = l.split(":", 1)[1].strip()
                if rest.endswith("NOT FOUND"):
                    caption = "Absent"
                else:
                    caption = "Present" if rest else "Unknown"
                break

    # FONTS (Noto Sans)
    fonts_lines = sections.get("FONTS", [])
    if any(x.strip().startswith("ERROR:") for x in fonts_lines):
        noto = "Unknown"
    else:
        noto = "Present" if any("Noto Sans" in x for x in fonts_lines) else "Absent"

    # Timestamp
    ts = parsed.get("timestamp") or "Unknown"

    return {
        "os": os_id,
        "default_lang": default_lang,
        "locale_en_US_UTF8": en_avail,
        "locale_es_ES_UTF8": es_avail,
        "tts_espeak_ng": tts,
        "caption_ffmpeg": caption,
        "noto_sans_font": noto,
        "probe_timestamp": ts,
    }


def build_expected_report_lines(statuses: Dict[str, str]) -> List[str]:
    return [
        f"OS: {statuses['os']}",
        f"Default LANG: {statuses['default_lang']}",
        f"Locale availability: en_US.UTF-8={statuses['locale_en_US_UTF8']}, es_ES.UTF-8={statuses['locale_es_ES_UTF8']}",
        f"Text-to-Speech tool (espeak-ng): {statuses['tts_espeak_ng']}",
        f"Captioning tool (ffmpeg): {statuses['caption_ffmpeg']}",
        f"Noto Sans font: {statuses['noto_sans_font']}",
        f"Probe timestamp: {statuses['probe_timestamp']}",
    ]


def parse_report(text: str) -> Tuple[bool, Optional[Dict[str, str]], List[str]]:
    raw_lines = text.splitlines()
    lines = [ln.rstrip("\n") for ln in raw_lines if ln.strip() != ""]
    if len(lines) != 7:
        return False, None, lines

    statuses: Dict[str, str] = {}

    m = re.match(r"^OS:\s*(.+)$", lines[0])
    if not m:
        return False, None, lines
    statuses["os"] = m.group(1).strip()

    m = re.match(r"^Default LANG:\s*(.+)$", lines[1])
    if not m:
        return False, None, lines
    statuses["default_lang"] = m.group(1).strip()

    m = re.match(r"^Locale availability:\s*en_US\.UTF-8=(Found|Not Found|Unknown),\s*es_ES\.UTF-8=(Found|Not Found|Unknown)$", lines[2])
    if not m:
        return False, None, lines
    statuses["locale_en_US_UTF8"] = m.group(1)
    statuses["locale_es_ES_UTF8"] = m.group(2)

    m = re.match(r"^Text-to-Speech tool \(espeak-ng\):\s*(Present|Absent|Unknown)$", lines[3])
    if not m:
        return False, None, lines
    statuses["tts_espeak_ng"] = m.group(1)

    m = re.match(r"^Captioning tool \(ffmpeg\):\s*(Present|Absent|Unknown)$", lines[4])
    if not m:
        return False, None, lines
    statuses["caption_ffmpeg"] = m.group(1)

    m = re.match(r"^Noto Sans font:\s*(Present|Absent|Unknown)$", lines[5])
    if not m:
        return False, None, lines
    statuses["noto_sans_font"] = m.group(1)

    m = re.match(r"^Probe timestamp:\s*(.+)$", lines[6])
    if not m:
        return False, None, lines
    statuses["probe_timestamp"] = m.group(1).strip()

    return True, statuses, lines


def extract_marked_region(text: str, start_marker: str, end_marker: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    start_idx = text.find(start_marker)
    end_idx = text.find(end_marker)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        return None, None, None
    pre = text[:start_idx + len(start_marker)]
    region = text[start_idx + len(start_marker): end_idx]
    post = text[end_idx:]
    return pre, region, post


def parse_outline_bullets(region_text: str) -> Tuple[bool, List[str]]:
    # Return whether region contains exactly seven "- " lines (ignoring empty lines) and the normalized lines.
    lines = [ln.rstrip() for ln in region_text.splitlines() if ln.strip() != ""]
    if len(lines) != 7:
        return False, lines
    if not all(line.startswith("- ") for line in lines):
        return False, lines
    return True, lines


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "probe_log_presence_and_structure": 0.0,
        "summary_file_exact_format": 0.0,
        "summary_values_match_log": 0.0,
        "outline_bullets_structure": 0.0,
        "outline_bullets_match_summary": 0.0,
        "outline_outside_markers_unchanged": 0.0,
    }

    probe_log_path = workspace / "reports" / "probe_raw.log"
    summary_path = workspace / "reports" / "system_inclusion_report.txt"
    outline_path = workspace / "docs" / "keynote_outline.md"

    # Probe log checks
    probe_text = read_text_file(probe_log_path)
    parsed = {"sections": {}, "start_seen": False, "end_seen": False, "timestamp": None}
    probe_valid = False
    if probe_text is not None and probe_text.strip() != "":
        parsed = parse_probe_log(probe_text)
        required_sections = {"OS", "LOCALE", "LOCALE_LIST", "TTS", "CAPTION", "FONTS"}
        present_sections = set(parsed.get("sections", {}).keys())
        if (
            parsed.get("start_seen") is True
            and parsed.get("end_seen") is True
            and parsed.get("timestamp") not in (None, "")
            and required_sections.issubset(present_sections)
        ):
            scores["probe_log_presence_and_structure"] = 1.0
            probe_valid = True

    # Summary checks
    summary_text = read_text_file(summary_path)
    summary_valid = False
    summary_lines: List[str] = []
    if summary_text is not None and summary_text.strip() != "":
        valid, parsed_report_statuses, report_lines = parse_report(summary_text)
        if valid:
            scores["summary_file_exact_format"] = 1.0
            summary_valid = True
            summary_lines = report_lines

    # Summary must match log-derived statuses
    if probe_valid and summary_valid:
        expected_statuses = compute_statuses(parsed)
        expected_report_lines = build_expected_report_lines(expected_statuses)
        if summary_lines == expected_report_lines:
            scores["summary_values_match_log"] = 1.0

    # Outline checks
    outline_text = read_text_file(outline_path)
    bullets_ok = False
    region_lines: List[str] = []
    if outline_text is not None:
        start_marker = "<!-- APPENDIX_TECH_ENV_START -->"
        end_marker = "<!-- APPENDIX_TECH_ENV_END -->"
        pre, region, post = extract_marked_region(outline_text, start_marker, end_marker)
        if pre is not None and region is not None and post is not None:
            bullets_ok, region_lines = parse_outline_bullets(region)
            if bullets_ok:
                # Structure: confirm labels match expected order and allowed token patterns
                # Build a temporary "report-like" content from bullets by stripping "- "
                stripped = [ln[2:] for ln in region_lines]
                # Reuse parse_report to validate format
                joined = "\n".join(stripped)
                valid_format, _, _ = parse_report(joined)
                if valid_format:
                    scores["outline_bullets_structure"] = 1.0

                # Compare bullets with summary
                if summary_valid:
                    expected_bullets = [f"- {line}" for line in summary_lines]
                    if region_lines == expected_bullets:
                        scores["outline_bullets_match_summary"] = 1.0

                # Outside markers unchanged vs baseline (only if bullets structure looks correct)
                if scores["outline_bullets_structure"] == 1.0:
                    b_pre, _, b_post = extract_marked_region(BASELINE_KEYNOTE_MD, start_marker, end_marker)
                    if b_pre is not None and b_post is not None:
                        if pre == b_pre and post == b_post:
                            scores["outline_outside_markers_unchanged"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()