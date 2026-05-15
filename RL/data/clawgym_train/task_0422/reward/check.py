import json
import re
import sys
from pathlib import Path
from datetime import datetime


def _safe_read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _is_iso8601(s: str) -> bool:
    try:
        datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def _extract_paragraph_after_header(text: str, header: str, use_last: bool = False):
    """
    Returns (paragraph_text, remainder_after_paragraph, found_idx)
    - paragraph_text: single paragraph text under the header (joined single line), or "" if not found
    - remainder_after_paragraph: raw text following the paragraph end (could be empty string)
    - found_idx: index where header was found in the full text, or -1 if not found
    """
    idx = text.rfind(header) if use_last else text.find(header)
    if idx == -1:
        return "", "", -1
    after = text[idx + len(header):]
    after_lstripped = after.lstrip("\r\n")
    lines = after_lstripped.splitlines(True)
    para_lines = []
    end_idx = 0
    for i, line in enumerate(lines):
        if not line.strip():
            end_idx = i
            break
        if line.startswith("## "):
            end_idx = i
            break
        para_lines.append(line.strip())
        end_idx = i + 1
    paragraph = " ".join(para_lines).strip()
    remainder = "".join(lines[end_idx:]) if end_idx is not None else ""
    return paragraph, remainder, idx


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "system_report_present": 0.0,
        "system_report_schema_types": 0.0,
        "system_report_disk_consistency": 0.0,
        "system_report_timestamp_iso8601": 0.0,
        "blog_section_present": 0.0,
        "blog_paragraph_present": 0.0,
        "blog_word_limit_respected": 0.0,
        "blog_mentions_os_name": 0.0,
        "blog_mentions_python_version": 0.0,
        "blog_no_template_placeholders": 0.0,
        "blog_section_appended_at_end": 0.0,
    }

    # Check system report
    report_path = workspace / "output" / "system_report.json"
    data = _safe_load_json(report_path)
    if data is not None:
        scores["system_report_present"] = 1.0
        required_top = ["system", "python", "cpu", "disk", "collected_at"]
        if all(k in data for k in required_top):
            sys_obj = data.get("system", {})
            py_obj = data.get("python", {})
            cpu_obj = data.get("cpu", {})
            disk_obj = data.get("disk", {})
            types_ok = True
            for k in ["os_name", "kernel", "machine"]:
                v = sys_obj.get(k)
                if not isinstance(v, str) or not v:
                    types_ok = False
                    break
            pv = py_obj.get("version")
            if not (isinstance(pv, str) and pv):
                types_ok = False
            lc = cpu_obj.get("logical_cores")
            if not (isinstance(lc, int) and lc >= 0):
                types_ok = False
            for k in ["total_bytes", "used_bytes", "free_bytes"]:
                dv = disk_obj.get(k)
                if not (isinstance(dv, int) and dv >= 0):
                    types_ok = False
                    break
            if types_ok:
                scores["system_report_schema_types"] = 1.0
            if (
                isinstance(disk_obj.get("total_bytes"), int)
                and isinstance(disk_obj.get("used_bytes"), int)
                and isinstance(disk_obj.get("free_bytes"), int)
            ):
                if disk_obj["used_bytes"] + disk_obj["free_bytes"] == disk_obj["total_bytes"]:
                    scores["system_report_disk_consistency"] = 1.0
            ca = data.get("collected_at")
            if isinstance(ca, str) and _is_iso8601(ca):
                scores["system_report_timestamp_iso8601"] = 1.0

    # Check blog draft and system note
    blog_path = workspace / "blog" / "draft.md"
    blog_text = _safe_read_text(blog_path)
    header = "## System note (auto-generated)"
    os_name = None
    py_version = None
    if data is not None and isinstance(data, dict):
        try:
            os_name = data["system"]["os_name"]
            py_version = data["python"]["version"]
        except Exception:
            os_name = None
            py_version = None

    if blog_text is not None:
        if blog_text.find(header) != -1:
            scores["blog_section_present"] = 1.0

        paragraph, remainder, idx_last = _extract_paragraph_after_header(blog_text, header, use_last=True)

        if idx_last != -1 and paragraph:
            scores["blog_paragraph_present"] = 1.0

            words = re.findall(r"\b\w+\b", paragraph)
            if len(words) <= 60:
                scores["blog_word_limit_respected"] = 1.0

            if os_name is not None and isinstance(os_name, str) and os_name and os_name in paragraph:
                scores["blog_mentions_os_name"] = 1.0
            if py_version is not None and isinstance(py_version, str) and py_version and py_version in paragraph:
                scores["blog_mentions_python_version"] = 1.0

            if "{{" not in paragraph and "}}" not in paragraph:
                scores["blog_no_template_placeholders"] = 1.0

            if remainder.strip() == "":
                scores["blog_section_appended_at_end"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()