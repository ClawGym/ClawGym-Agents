import json
import csv
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from html.parser import HTMLParser


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        out = []
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            out.append(json.loads(ln))
        return out
    except Exception:
        return None


def _load_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_policy_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the simple expected structure:
    - top-level keys with scalar values
    - top-level keys that start a list (colon followed by nothing), with indented "- item" lines
    """
    text = _read_text(path)
    if text is None:
        return None
    cfg: Dict[str, Any] = {}
    current_list_key: Optional[str] = None
    try:
        for raw_line in text.splitlines():
            line = raw_line.rstrip("\n")
            if not line.strip() or line.strip().startswith("#"):
                continue
            if re.match(r"^\S[^:]*:\s*(.+)$", line):
                # key: value
                m = re.match(r"^(\S[^:]*):\s*(.+)$", line)
                if not m:
                    continue
                key = m.group(1).strip()
                value = _strip_quotes(m.group(2).strip())
                current_list_key = None
                # Try to parse int if possible
                if key == "char_limit":
                    try:
                        cfg[key] = int(value)
                    except ValueError:
                        return None
                elif key in ("platform", "policy_version"):
                    cfg[key] = value
                else:
                    # Could be an inline list, but we don't expect that here
                    cfg[key] = value
            elif re.match(r"^(\S[^:]*):\s*$", line):
                # key: (start of list)
                m = re.match(r"^(\S[^:]*):\s*$", line)
                if not m:
                    continue
                key = m.group(1).strip()
                cfg[key] = []
                current_list_key = key
            elif current_list_key is not None and re.match(r"^\s*-\s+.+$", line):
                # list item
                m = re.match(r"^\s*-\s+(.+)$", line)
                if not m:
                    continue
                item = _strip_quotes(m.group(1).strip())
                cfg[current_list_key].append(item)
            else:
                # Unrecognized line; for robustness, ignore
                continue
        # Validate required keys
        required_keys = {"allowed_hashtags", "banned_phrases", "platform", "char_limit", "policy_version"}
        if not required_keys.issubset(set(cfg.keys())):
            return None
        if not isinstance(cfg["allowed_hashtags"], list) or not isinstance(cfg["banned_phrases"], list):
            return None
        if not isinstance(cfg["char_limit"], int):
            return None
        return cfg
    except Exception:
        return None


class _FooterHTMLParser(HTMLParser):
    def __init__(self, target_id: str):
        super().__init__()
        self.target_id = target_id
        self._in_target = False
        self._data: List[str] = []
        self._current_tag_stack: List[str] = []

    def handle_starttag(self, tag, attrs):
        self._current_tag_stack.append(tag)
        attrs_dict = dict(attrs)
        if attrs_dict.get("id") == self.target_id:
            self._in_target = True

    def handle_endtag(self, tag):
        if self._current_tag_stack:
            self._current_tag_stack.pop()
        if self._in_target and tag == "p":
            # Assuming the target is a <p> element
            self._in_target = False

    def handle_data(self, data):
        if self._in_target:
            self._data.append(data)

    def get_text(self) -> str:
        return "".join(self._data).strip()


def _extract_footer_from_html(path: Path, element_id: str = "mandatory-caption-footer") -> Optional[str]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        parser = _FooterHTMLParser(element_id)
        parser.feed(text)
        footer = parser.get_text()
        return footer if footer else None
    except Exception:
        return None


def _bool_from_csv(value: str) -> Optional[bool]:
    if value is None:
        return None
    v = value.strip().lower()
    if v == "true":
        return True
    if v == "false":
        return False
    return None


def _manifest_index(manifest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    media_list = manifest.get("media", [])
    if isinstance(media_list, list):
        for item in media_list:
            if isinstance(item, dict):
                file_name = item.get("file")
                if isinstance(file_name, str):
                    idx[file_name] = item
    return idx


def _list_media_files(media_dir: Path) -> List[str]:
    try:
        if not media_dir.exists() or not media_dir.is_dir():
            return []
        return [p.name for p in media_dir.iterdir() if p.is_file()]
    except Exception:
        return []


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Initialize scores with all checks set to 0.0
    scores: Dict[str, float] = {
        "content_plan_exists_and_valid_json": 0.0,
        "plan_has_correct_length_and_order": 0.0,
        "plan_fields_exact_and_types": 0.0,
        "captions_end_with_footer_and_within_char_limit": 0.0,
        "captions_no_banned_phrases": 0.0,
        "hashtags_valid_nonempty_and_no_duplicates": 0.0,
        "policy_version_correct_in_plan": 0.0,
        "media_references_valid_when_present": 0.0,
        "alt_text_correct_when_media_present": 0.0,
        "media_null_when_no_compliant_available": 0.0,
        "compliance_report_exists_and_structure": 0.0,
        "compliance_rows_align_with_schedule": 0.0,
        "compliance_media_selected_matches_plan": 0.0,
        "compliance_derived_fields_correct": 0.0,
    }

    # Load inputs
    schedule_path = workspace / "input" / "schedule.csv"
    manifest_path = workspace / "input" / "media_manifest.json"
    policy_path = workspace / "input" / "policy_config.yaml"
    guidelines_path = workspace / "input" / "district_guidelines.html"
    media_dir = workspace / "media"
    content_plan_path = workspace / "output" / "content_plan.json"
    compliance_report_path = workspace / "output" / "compliance_report.csv"

    schedule_rows = _load_csv_rows(schedule_path)
    manifest = _load_json(manifest_path)
    policy = _parse_policy_yaml(policy_path)
    footer = _extract_footer_from_html(guidelines_path)
    media_files = _list_media_files(media_dir)

    # Plan loading
    plan = _load_json(content_plan_path)
    plan_is_list = isinstance(plan, list)

    # Compliance report loading
    compliance_rows = _load_csv_rows(compliance_report_path)

    # Precompute structures if possible
    manifest_idx = _manifest_index(manifest) if isinstance(manifest, dict) else {}
    allowed_hashtags = set(policy["allowed_hashtags"]) if isinstance(policy, dict) and isinstance(policy.get("allowed_hashtags"), list) else set()
    banned_phrases = list(policy["banned_phrases"]) if isinstance(policy, dict) and isinstance(policy.get("banned_phrases"), list) else []
    char_limit = policy["char_limit"] if isinstance(policy, dict) and isinstance(policy.get("char_limit"), int) else None
    policy_version = policy["policy_version"] if isinstance(policy, dict) and isinstance(policy.get("policy_version"), str) else None

    # Helper lambdas
    def caption_has_banned(caption: str) -> bool:
        low = caption.lower()
        for phrase in banned_phrases:
            if isinstance(phrase, str) and phrase.strip():
                if phrase.lower() in low:
                    return True
        return False

    # Check 1: content_plan_exists_and_valid_json
    if plan_is_list:
        scores["content_plan_exists_and_valid_json"] = 1.0

    # Check 2: plan_has_correct_length_and_order
    plan_len_ok = False
    if plan_is_list and schedule_rows is not None:
        if len(plan) == len(schedule_rows):
            order_ok = True
            for i, row in enumerate(schedule_rows):
                try:
                    p = plan[i]
                    if not isinstance(p, dict):
                        order_ok = False
                        break
                    if p.get("date") != row.get("date") or p.get("topic") != row.get("topic"):
                        order_ok = False
                        break
                except Exception:
                    order_ok = False
                    break
            plan_len_ok = order_ok
    if plan_len_ok:
        scores["plan_has_correct_length_and_order"] = 1.0

    # Check 3: plan_fields_exact_and_types
    fields_ok = False
    required_fields = {"date", "topic", "caption", "hashtags", "media_file", "alt_text", "policy_version"}
    if plan_is_list:
        fields_ok = True
        for p in plan:
            if not isinstance(p, dict):
                fields_ok = False
                break
            if set(p.keys()) != required_fields:
                fields_ok = False
                break
            if not isinstance(p.get("date"), str):
                fields_ok = False
                break
            if not isinstance(p.get("topic"), str):
                fields_ok = False
                break
            if not isinstance(p.get("caption"), str):
                fields_ok = False
                break
            hashtags_val = p.get("hashtags")
            if not isinstance(hashtags_val, list) or not all(isinstance(h, str) for h in hashtags_val):
                fields_ok = False
                break
            media_val = p.get("media_file")
            if media_val is not None and not isinstance(media_val, str):
                fields_ok = False
                break
            alt_val = p.get("alt_text")
            if alt_val is not None and not isinstance(alt_val, str):
                fields_ok = False
                break
            if not isinstance(p.get("policy_version"), str):
                fields_ok = False
                break
    if fields_ok:
        scores["plan_fields_exact_and_types"] = 1.0

    # Check 4: captions_end_with_footer_and_within_char_limit
    captions_ok = False
    if plan_is_list and footer is not None and isinstance(char_limit, int):
        captions_ok = True
        for p in plan:
            cap = p.get("caption", "")
            if not isinstance(cap, str):
                captions_ok = False
                break
            if not cap.endswith(footer):
                captions_ok = False
                break
            if len(cap) > char_limit:
                captions_ok = False
                break
    if captions_ok:
        scores["captions_end_with_footer_and_within_char_limit"] = 1.0

    # Check 5: captions_no_banned_phrases
    banned_ok = False
    if plan_is_list and isinstance(banned_phrases, list):
        banned_ok = True
        for p in plan:
            cap = p.get("caption", "")
            if not isinstance(cap, str):
                banned_ok = False
                break
            if caption_has_banned(cap):
                banned_ok = False
                break
    if banned_ok:
        scores["captions_no_banned_phrases"] = 1.0

    # Check 6: hashtags_valid_nonempty_and_no_duplicates
    hashtags_ok = False
    if plan_is_list and allowed_hashtags:
        hashtags_ok = True
        for p in plan:
            tags = p.get("hashtags", [])
            if not isinstance(tags, list) or len(tags) == 0:
                hashtags_ok = False
                break
            # no duplicates
            if len(tags) != len(set(tags)):
                hashtags_ok = False
                break
            # allowed only
            if any(t not in allowed_hashtags for t in tags):
                hashtags_ok = False
                break
    if hashtags_ok:
        scores["hashtags_valid_nonempty_and_no_duplicates"] = 1.0

    # Check 7: policy_version_correct_in_plan
    policy_version_ok = False
    if plan_is_list and isinstance(policy_version, str):
        policy_version_ok = all(isinstance(p, dict) and p.get("policy_version") == policy_version for p in plan)
    if policy_version_ok:
        scores["policy_version_correct_in_plan"] = 1.0

    # Precompute compliant media per topic (permission True and file exists)
    compliant_media_by_topic: Dict[str, List[str]] = {}
    if isinstance(manifest, dict):
        for item in manifest.get("media", []):
            if not isinstance(item, dict):
                continue
            file_name = item.get("file")
            topics = item.get("topics", [])
            permission = item.get("permission", False)
            if isinstance(file_name, str) and isinstance(topics, list) and permission is True:
                if file_name in media_files:
                    for t in topics:
                        if isinstance(t, str):
                            compliant_media_by_topic.setdefault(t, []).append(file_name)

    # Check 8: media_references_valid_when_present
    media_valid = False
    if plan_is_list and isinstance(manifest, dict):
        media_valid = True
        for p in plan:
            media_file = p.get("media_file", None)
            topic = p.get("topic")
            if media_file is None:
                continue
            if not isinstance(media_file, str):
                media_valid = False
                break
            if not media_file.startswith("media/"):
                media_valid = False
                break
            base = Path(media_file).name
            # file exists
            if base not in media_files:
                media_valid = False
                break
            # manifest entry
            entry = manifest_idx.get(base)
            if not isinstance(entry, dict):
                media_valid = False
                break
            if not entry.get("permission", False):
                media_valid = False
                break
            topics = entry.get("topics", [])
            if not isinstance(topics, list) or topic not in topics:
                media_valid = False
                break
    if media_valid:
        scores["media_references_valid_when_present"] = 1.0

    # Check 9: alt_text_correct_when_media_present
    alt_ok = False
    if plan_is_list and isinstance(manifest, dict):
        alt_ok = True
        for p in plan:
            media_file = p.get("media_file", None)
            alt_text = p.get("alt_text", None)
            if media_file is None:
                if alt_text is not None:
                    alt_ok = False
                    break
                continue
            base = Path(str(media_file)).name if isinstance(media_file, str) else ""
            entry = manifest_idx.get(base)
            if not isinstance(entry, dict):
                alt_ok = False
                break
            if alt_text != entry.get("alt_text"):
                alt_ok = False
                break
    if alt_ok:
        scores["alt_text_correct_when_media_present"] = 1.0

    # Check 10: media_null_when_no_compliant_available
    null_when_none_available_ok = False
    if plan_is_list:
        null_when_none_available_ok = True
        for p in plan:
            topic = p.get("topic")
            media_file = p.get("media_file", None)
            compliant = compliant_media_by_topic.get(topic, [])
            if not compliant:
                if media_file is not None:
                    null_when_none_available_ok = False
                    break
    if null_when_none_available_ok:
        scores["media_null_when_no_compliant_available"] = 1.0

    # Compliance checks

    # Check 11: compliance_report_exists_and_structure
    compliance_structure_ok = False
    required_columns = [
        "date",
        "topic",
        "media_selected",
        "permission_ok",
        "file_exists",
        "caption_length",
        "within_limit",
        "banned_phrases_found",
        "footer_included",
        "hashtags_allowed_only",
        "policy_version",
        "notes",
    ]
    # To check header order, re-read header directly
    header_ok = False
    if compliance_report_path.exists():
        try:
            with compliance_report_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header == required_columns:
                    header_ok = True
        except Exception:
            header_ok = False
    if compliance_rows is not None and header_ok:
        compliance_structure_ok = True
    if compliance_structure_ok:
        scores["compliance_report_exists_and_structure"] = 1.0

    # Check 12: compliance_rows_align_with_schedule
    compliance_align_ok = False
    if compliance_rows is not None and schedule_rows is not None:
        if len(compliance_rows) == len(schedule_rows):
            ok = True
            for i, row in enumerate(compliance_rows):
                if row.get("date") != schedule_rows[i].get("date") or row.get("topic") != schedule_rows[i].get("topic"):
                    ok = False
                    break
            compliance_align_ok = ok
    if compliance_align_ok:
        scores["compliance_rows_align_with_schedule"] = 1.0

    # Check 13: compliance_media_selected_matches_plan
    comp_media_match_ok = False
    if compliance_rows is not None and plan_is_list:
        if len(compliance_rows) == len(plan):
            ok = True
            for i in range(len(plan)):
                plan_media = plan[i].get("media_file", None)
                expected = "None" if plan_media is None else str(plan_media)
                if compliance_rows[i].get("media_selected") != expected:
                    ok = False
                    break
            comp_media_match_ok = ok
    if comp_media_match_ok:
        scores["compliance_media_selected_matches_plan"] = 1.0

    # Check 14: compliance_derived_fields_correct
    comp_derived_ok = False
    if (
        compliance_rows is not None
        and plan_is_list
        and isinstance(manifest, dict)
        and isinstance(char_limit, int)
        and footer is not None
        and allowed_hashtags
        and isinstance(policy_version, str)
        and len(compliance_rows) == len(plan)
    ):
        ok = True
        for i, crow in enumerate(compliance_rows):
            plan_row = plan[i]
            caption = plan_row.get("caption", "")
            if not isinstance(caption, str):
                ok = False
                break
            # media_selected parsing
            media_selected = crow.get("media_selected")
            selected_base: Optional[str] = None
            if media_selected == "None":
                selected_base = None
            elif isinstance(media_selected, str):
                selected_base = Path(media_selected).name
            else:
                ok = False
                break
            # Compute expected permission_ok and file_exists
            expected_permission_ok = False
            expected_file_exists = False
            if selected_base:
                entry = manifest_idx.get(selected_base)
                expected_permission_ok = bool(entry.get("permission")) if isinstance(entry, dict) else False
                expected_file_exists = selected_base in media_files
            # Compare permission_ok
            po = _bool_from_csv(crow.get("permission_ok", ""))
            fe = _bool_from_csv(crow.get("file_exists", ""))
            if po is None or fe is None or po != expected_permission_ok or fe != expected_file_exists:
                ok = False
                break
            # caption_length
            try:
                cap_len_val = int(crow.get("caption_length", ""))
            except Exception:
                ok = False
                break
            if cap_len_val != len(caption):
                ok = False
                break
            # within_limit
            wl = _bool_from_csv(crow.get("within_limit", ""))
            if wl is None or wl != (len(caption) <= char_limit):
                ok = False
                break
            # banned_phrases_found
            bpf = _bool_from_csv(crow.get("banned_phrases_found", ""))
            if bpf is None or bpf != caption_has_banned(caption):
                ok = False
                break
            # footer_included
            fi = _bool_from_csv(crow.get("footer_included", ""))
            if fi is None or fi != caption.endswith(footer):
                ok = False
                break
            # hashtags_allowed_only
            tags = plan_row.get("hashtags", [])
            tags_allowed_only = isinstance(tags, list) and all(t in allowed_hashtags for t in tags)
            hao = _bool_from_csv(crow.get("hashtags_allowed_only", ""))
            if hao is None or hao != tags_allowed_only:
                ok = False
                break
            # policy_version
            if crow.get("policy_version") != policy_version:
                ok = False
                break
        comp_derived_ok = ok
    if comp_derived_ok:
        scores["compliance_derived_fields_correct"] = 1.0

    return scores


def main() -> None:
        workspace = sys.argv[1] if len(sys.argv) > 1 else "."
        result = grade([], workspace)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()