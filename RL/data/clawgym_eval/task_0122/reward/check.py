import json
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[Any]:
    try:
        text = read_text_file(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _parse_scalar(value: str) -> Any:
    v = value.strip()
    if v.startswith(("'", '"')) and v.endswith(("'", '"')) and len(v) >= 2:
        return v[1:-1]
    low = v.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        if re.fullmatch(r"-?\d+", v):
            return int(v)
    except Exception:
        pass
    return v


def simple_yaml_load(text: str) -> Dict[str, Any]:
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    lines = text.splitlines()
    for raw in lines:
        if not raw.strip():
            continue
        content = raw.split("#", 1)[0].rstrip("\r\n")
        if not content.strip():
            continue
        indent = len(content) - len(content.lstrip(" "))
        while stack and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1] if stack else root
        stripped = content.strip()
        if ":" not in stripped:
            raise ValueError("Invalid YAML line (no colon): " + stripped)
        key_part, value_part = stripped.split(":", 1)
        key = key_part.strip()
        value = value_part.strip()
        if not key:
            raise ValueError("Empty key in YAML.")
        if value == "":
            new: Dict[str, Any] = {}
            current[key] = new
            stack.append((indent, new))
        else:
            current[key] = _parse_scalar(value)
    return root


def simple_yaml_load_path(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = read_text_file(path)
        if text is None:
            return None
        return simple_yaml_load(text)
    except Exception:
        return None


def parse_iso_dt(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def parse_log_line(line: str) -> Optional[Dict[str, Any]]:
    line = line.strip()
    if not line:
        return None
    parts = line.split()
    if len(parts) < 2:
        return None
    ts = parts[0]
    data: Dict[str, Any] = {"timestamp": ts}
    for token in parts[1:]:
        if "=" in token:
            k, v = token.split("=", 1)
            k = k.strip()
            v = v.strip().rstrip(",")
            low = v.lower()
            if low == "true":
                val: Any = True
            elif low == "false":
                val = False
            else:
                if k == "attempt":
                    try:
                        val = int(v)
                    except Exception:
                        val = v
                else:
                    val = v
            data[k] = val
    return data


def compute_incident_from_logs(log_path: Path) -> Optional[Dict[str, Any]]:
    text = read_text_file(log_path)
    if text is None:
        return None
    impacted_info: Dict[str, Dict[str, Any]] = {}
    all_events: List[Dict[str, Any]] = []
    for raw in text.splitlines():
        parsed = parse_log_line(raw)
        if not parsed:
            continue
        if "post_id" not in parsed:
            continue
        all_events.append(parsed)
    if not all_events:
        return {
            "timeframe_start": None,
            "timeframe_end": None,
            "impacted_posts": {},
        }
    per_post: Dict[str, Dict[str, Any]] = {}
    for ev in all_events:
        pid = ev.get("post_id")
        if not pid:
            continue
        d = per_post.setdefault(pid, {"max_attempt": 0, "dup": False, "events": []})
        att = ev.get("attempt")
        if isinstance(att, int):
            if att > d["max_attempt"]:
                d["max_attempt"] = att
        if ev.get("possible_duplicate") is True:
            d["dup"] = True
        d["events"].append(ev)
    impacted_posts: Dict[str, Dict[str, Any]] = {}
    for pid, info in per_post.items():
        if info["max_attempt"] > 1 or info["dup"]:
            impacted_posts[pid] = {
                "attempts": info["max_attempt"],
                "possible_duplicate_flagged": bool(info["dup"]),
                "events": info["events"],
            }
    if not impacted_posts:
        return {
            "timeframe_start": None,
            "timeframe_end": None,
            "impacted_posts": {},
        }
    timestamps: List[Tuple[datetime, str]] = []
    for info in impacted_posts.values():
        for ev in info["events"]:
            ts_str = ev.get("timestamp")
            if not ts_str:
                continue
            dt = parse_iso_dt(ts_str)
            if dt is None:
                continue
            timestamps.append((dt, ts_str))
    if not timestamps:
        ts_strings: List[str] = []
        for info in impacted_posts.values():
            for ev in info["events"]:
                ts_s = ev.get("timestamp")
                if ts_s:
                    ts_strings.append(ts_s)
        if not ts_strings:
            return None
        start_str = min(ts_strings)
        end_str = max(ts_strings)
        return {
            "timeframe_start": start_str,
            "timeframe_end": end_str,
            "impacted_posts": {
                pid: {"attempts": v["attempts"], "possible_duplicate_flagged": v["possible_duplicate_flagged"]}
                for pid, v in impacted_posts.items()
            },
        }
    timestamps.sort(key=lambda x: x[0])
    start_dt, start_str = timestamps[0]
    end_dt, end_str = timestamps[-1]
    return {
        "timeframe_start": start_str,
        "timeframe_end": end_str,
        "impacted_posts": {
            pid: {"attempts": v["attempts"], "possible_duplicate_flagged": v["possible_duplicate_flagged"]}
            for pid, v in impacted_posts.items()
        },
    }


def count_sentences(text: str) -> int:
    separators = re.compile(r"[\.!\?。！？]+")
    parts = [p.strip() for p in separators.split(text)]
    count = 0
    for p in parts:
        if re.search(r"[A-Za-z\u4e00-\u9fff]", p):
            count += 1
    return count


def extract_apology_sections(text: str) -> Optional[Tuple[str, str]]:
    start = text.find("[ZH]")
    if start == -1:
        return None
    before = text[:start].strip()
    if before:
        return None
    after_zh = text[start + len("[ZH]") :]
    en_idx = after_zh.find("[EN]")
    if en_idx == -1:
        return None
    zh_body = after_zh[:en_idx].strip()
    en_body = after_zh[en_idx + len("[EN]") :].strip()
    return zh_body, en_body


def check_root_cause_summary(summary: str) -> float:
    sent_count = count_sentences(summary)
    if sent_count < 1 or sent_count > 3:
        return 0.0
    text = summary.lower()
    mentions_retry = bool(re.search(r"\bretries?\b", text)) or ("max_attempts" in text)
    mentions_dedup = ("dedup" in text) or ("idempot" in text)
    mentions_prefix = ("id_key_prefix" in text) or ("idprefix" in text) or ("prefix" in text)
    mentions_backoff_or_jitter = ("backoff" in text) or ("jitter" in text) or ("network" in text)
    mentions_mismatch = ("mismatch" in text) or ("wrong" in text) or ("missing" in text) or ("default" in text)
    score_bits = [
        mentions_retry,
        mentions_dedup,
        mentions_prefix,
        mentions_backoff_or_jitter,
        mentions_mismatch,
    ]
    score = sum(1.0 for b in score_bits if b) / len(score_bits)
    return float(score)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "incident_report_exists_and_schema": 0.0,
        "incident_timeframe_correct": 0.0,
        "incident_impacted_posts_summary_correct": 0.0,
        "incident_incident_id_correct": 0.0,
        "incident_root_cause_quality": 0.0,
        "incident_fixed_config_path_correct": 0.0,
        "fixed_config_yaml_valid": 0.0,
        "fixed_config_keyset_correct": 0.0,
        "apology_bilingual_structure": 0.0,
        "apology_required_lines_correct": 0.0,
        "apology_sentence_count_ok": 0.0,
        "cross_file_consistency": 0.0,
    }

    logs_path = workspace / "input" / "logs" / "poster.log"
    computed = compute_incident_from_logs(logs_path)

    expected_start = None
    expected_end = None
    expected_impacted_posts: Dict[str, Dict[str, Any]] = {}
    expected_count = 0
    if computed:
        expected_start = computed.get("timeframe_start")
        expected_end = computed.get("timeframe_end")
        expected_impacted_posts = computed.get("impacted_posts", {})
        expected_count = len(expected_impacted_posts)

    ir_path = workspace / "output" / "incident_report.json"
    ir = safe_load_json(ir_path)
    schema_ok = False
    timeframe_ok = False
    impacted_ok = False
    incident_id_ok = False
    root_cause_quality = 0.0
    fixed_path_ok = False

    if isinstance(ir, dict):
        required_fields = {"incident_id", "timeframe", "impacted_post_count", "impacted_posts", "root_cause_summary", "fixed_config_path"}
        schema_ok = required_fields.issubset(ir.keys()) and isinstance(ir.get("timeframe"), dict) and isinstance(ir.get("impacted_posts"), list)
        if schema_ok:
            tf = ir.get("timeframe", {})
            if expected_start is not None and expected_end is not None:
                timeframe_ok = (tf.get("start") == expected_start and tf.get("end") == expected_end)
            else:
                timeframe_ok = False
            ip_list = ir.get("impacted_posts", [])
            if isinstance(ip_list, list):
                got_map: Dict[str, Dict[str, Any]] = {}
                valid_objs = True
                for obj in ip_list:
                    if not isinstance(obj, dict):
                        valid_objs = False
                        break
                    allowed_keys = {"post_id", "attempts", "possible_duplicate_flagged"}
                    if set(obj.keys()) != allowed_keys:
                        valid_objs = False
                        break
                    pid = obj.get("post_id")
                    attempts = obj.get("attempts")
                    dup = obj.get("possible_duplicate_flagged")
                    if not isinstance(pid, str) or not isinstance(attempts, int) or not isinstance(dup, bool):
                        valid_objs = False
                        break
                    got_map[pid] = {"attempts": attempts, "possible_duplicate_flagged": dup}
                if valid_objs:
                    impacted_ok = (got_map == expected_impacted_posts)
            if impacted_ok and isinstance(ir.get("impacted_post_count"), int):
                impacted_ok = impacted_ok and (ir.get("impacted_post_count") == expected_count)
            else:
                impacted_ok = False
            if expected_start:
                try:
                    date_part = expected_start.split("T", 1)[0].replace("-", "")
                    expected_incident_id = f"IR-{date_part}-duplicate-posts"
                    incident_id_ok = (ir.get("incident_id") == expected_incident_id)
                except Exception:
                    incident_id_ok = False
            else:
                incident_id_ok = False
            rcs = ir.get("root_cause_summary")
            if isinstance(rcs, str):
                root_cause_quality = check_root_cause_summary(rcs)
            fixed_path_ok = (ir.get("fixed_config_path") == "output/post_scheduler.fixed.yaml")

    scores["incident_report_exists_and_schema"] = 1.0 if schema_ok else 0.0
    scores["incident_timeframe_correct"] = 1.0 if timeframe_ok else 0.0
    scores["incident_impacted_posts_summary_correct"] = 1.0 if impacted_ok else 0.0
    scores["incident_incident_id_correct"] = 1.0 if incident_id_ok else 0.0
    scores["incident_root_cause_quality"] = float(root_cause_quality)
    scores["incident_fixed_config_path_correct"] = 1.0 if fixed_path_ok else 0.0

    fixed_cfg_path = workspace / "output" / "post_scheduler.fixed.yaml"
    cfg_obj = simple_yaml_load_path(fixed_cfg_path)
    yaml_valid = isinstance(cfg_obj, dict)
    scores["fixed_config_yaml_valid"] = 1.0 if yaml_valid else 0.0

    keyset_ok = False
    if yaml_valid and isinstance(cfg_obj, dict):
        retries = cfg_obj.get("retries")
        network = cfg_obj.get("network")
        safety = cfg_obj.get("safety")
        publisher = cfg_obj.get("publisher")
        try:
            conds = []
            conds.append(isinstance(retries, dict) and isinstance(retries.get("max_attempts"), int) and retries.get("max_attempts") <= 3)
            conds.append(isinstance(network, dict) and isinstance(network.get("backoff_seconds"), int) and 8 <= network.get("backoff_seconds") <= 15)
            conds.append(isinstance(network, dict) and network.get("jitter") is True)
            conds.append(isinstance(safety, dict) and safety.get("dedup_enabled") is True)
            conds.append(isinstance(publisher, dict) and isinstance(publisher.get("id_key_prefix"), str) and len(publisher.get("id_key_prefix")) > 0)
            keyset_ok = all(conds)
        except Exception:
            keyset_ok = False
    scores["fixed_config_keyset_correct"] = 1.0 if keyset_ok else 0.0

    apology_path = workspace / "output" / "apology_bilingual.txt"
    apology_text = read_text_file(apology_path)
    structure_ok = False
    required_lines_ok = False
    sentence_count_ok = 0.0
    cross_ok = False
    if apology_text is not None:
        sections = extract_apology_sections(apology_text)
        if sections is not None:
            zh_body, en_body = sections
            structure_ok = True
            tf_line = None
            cnt_line = None
            if expected_start is not None and expected_end is not None:
                tf_line = f"Timeframe: {expected_start} to {expected_end}"
            if expected_start is not None:
                cnt_line = f"Impacted posts: {expected_count}"
            if tf_line is not None and cnt_line is not None:
                zh_lines = [ln.strip() for ln in zh_body.splitlines() if ln.strip()]
                en_lines = [ln.strip() for ln in en_body.splitlines() if ln.strip()]
                zh_has_tf = tf_line in zh_lines
                zh_has_cnt = cnt_line in zh_lines
                en_has_tf = tf_line in en_lines
                en_has_cnt = cnt_line in en_lines
                required_lines_ok = zh_has_tf and zh_has_cnt and en_has_tf and en_has_cnt
                zh_remaining = "\n".join([ln for ln in zh_lines if ln not in (tf_line, cnt_line)])
                en_remaining = "\n".join([ln for ln in en_lines if ln not in (tf_line, cnt_line)])
                zh_sent = count_sentences(zh_remaining)
                en_sent = count_sentences(en_remaining)
                sc = 0.0
                if 2 <= zh_sent <= 4:
                    sc += 0.5
                if 2 <= en_sent <= 4:
                    sc += 0.5
                sentence_count_ok = sc
                if isinstance(ir, dict) and isinstance(ir.get("timeframe"), dict) and isinstance(ir.get("impacted_post_count"), int):
                    ir_tf_start = ir["timeframe"].get("start")
                    ir_tf_end = ir["timeframe"].get("end")
                    ir_cnt = ir.get("impacted_post_count")
                    cross_ok = (ir_tf_start == expected_start and ir_tf_end == expected_end and ir_cnt == expected_count and required_lines_ok)
    scores["apology_bilingual_structure"] = 1.0 if structure_ok else 0.0
    scores["apology_required_lines_correct"] = 1.0 if required_lines_ok else 0.0
    scores["apology_sentence_count_ok"] = float(sentence_count_ok)
    scores["cross_file_consistency"] = 1.0 if cross_ok else 0.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()