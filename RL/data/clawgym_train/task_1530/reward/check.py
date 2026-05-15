import json
import sys
import re
import csv
import ast
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        txt = _read_text_safe(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _parse_bool_str(s: str) -> Optional[bool]:
    if s is None:
        return None
    val = s.strip().lower()
    if val in ("true", "t", "yes", "y", "1"):
        return True
    if val in ("false", "f", "no", "n", "0"):
        return False
    return None


def _leading_spaces(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_inline_list(value: str) -> Optional[List[Any]]:
    try:
        parsed = ast.literal_eval(value.strip())
        if isinstance(parsed, list):
            return parsed
        return None
    except Exception:
        return None


def _parse_config_yaml(path: Path) -> Optional[Dict[str, Any]]:
    txt = _read_text_safe(path)
    if txt is None:
        return None

    lines = []
    for raw in txt.splitlines():
        no_comment = raw.split("#", 1)[0]
        if no_comment.strip() == "":
            lines.append("")
        else:
            lines.append(no_comment.rstrip("\n"))

    cfg: Dict[str, Any] = {"default_queue": None, "routing_rules": [], "queues": []}

    for line in lines:
        m = re.match(r"^\s*default_queue:\s*([^\s#]+)\s*$", line)
        if m:
            cfg["default_queue"] = m.group(1).strip()
            break

    in_queues = False
    queues_indent = None
    current_item: Dict[str, Any] = {}
    for i, line in enumerate(lines):
        if not in_queues:
            if re.match(r"^\s*queues:\s*$", line):
                in_queues = True
                queues_indent = _leading_spaces(line)
                continue
        else:
            if line.strip() == "":
                continue
            indent = _leading_spaces(line)
            if indent <= (queues_indent or 0):
                in_queues = False
                if current_item:
                    if "name" in current_item:
                        cfg["queues"].append(current_item["name"])
                    current_item = {}
                continue
            m_item = re.match(r"^\s*-\s*(.*)$", line)
            if m_item:
                if current_item:
                    if "name" in current_item:
                        cfg["queues"].append(current_item["name"])
                current_item = {}
                remainder = m_item.group(1).strip()
                if remainder:
                    kv = remainder.split(":", 1)
                    if len(kv) == 2:
                        key = kv[0].strip()
                        val = kv[1].strip()
                        if key == "name":
                            current_item["name"] = val
                continue
            if current_item is not None and ":" in line:
                kv = line.strip().split(":", 1)
                key = kv[0].strip()
                val = kv[1].strip()
                if key == "name":
                    current_item["name"] = val
    if current_item:
        if "name" in current_item:
            cfg["queues"].append(current_item["name"])

    in_rules = False
    rules_indent = None
    current_rule: Optional[Dict[str, Any]] = None
    for i, line in enumerate(lines):
        if not in_rules:
            if re.match(r"^\s*routing_rules:\s*$", line):
                in_rules = True
                rules_indent = _leading_spaces(line)
                continue
        else:
            if line.strip() == "":
                continue
            indent = _leading_spaces(line)
            if indent <= (rules_indent or 0):
                if current_rule:
                    if "match_any_tag" in current_rule and "send_to" in current_rule:
                        cfg["routing_rules"].append(current_rule)
                current_rule = None
                in_rules = False
                continue

            m_item = re.match(r"^\s*-\s*(.*)$", line)
            if m_item:
                if current_rule:
                    if "match_any_tag" in current_rule and "send_to" in current_rule:
                        cfg["routing_rules"].append(current_rule)
                current_rule = {}
                remainder = m_item.group(1).strip()
                if remainder:
                    kv = remainder.split(":", 1)
                    if len(kv) == 2:
                        key = kv[0].strip()
                        val = kv[1].strip()
                        if key == "match_any_tag":
                            lst = _parse_inline_list(val)
                            if lst is not None:
                                current_rule["match_any_tag"] = [str(x) for x in lst]
                        elif key == "send_to":
                            current_rule["send_to"] = val
                continue

            if current_rule is not None and ":" in line:
                kv = line.strip().split(":", 1)
                key = kv[0].strip()
                val = kv[1].strip()
                if key == "match_any_tag":
                    lst = _parse_inline_list(val)
                    if lst is not None:
                        current_rule["match_any_tag"] = [str(x) for x in lst]
                elif key == "send_to":
                    current_rule["send_to"] = val

    if in_rules and current_rule:
        if "match_any_tag" in current_rule and "send_to" in current_rule:
            cfg["routing_rules"].append(current_rule)

    if cfg.get("default_queue") is None or not isinstance(cfg.get("routing_rules"), list):
        return None
    qnames: List[str] = []
    for q in cfg.get("queues", []):
        if isinstance(q, str) and q not in qnames:
            qnames.append(q)
    cfg["queues"] = qnames
    return cfg


def _parse_task_meta_from_py(path: Path) -> Optional[Dict[str, Any]]:
    try:
        src = _read_text_safe(path)
        if src is None:
            return None
        node = ast.parse(src, filename=str(path))
        task_meta = None
        for n in node.body:
            if isinstance(n, ast.Assign):
                targets = [t.id for t in n.targets if isinstance(t, ast.Name)]
                if "TASK_META" in targets and isinstance(n.value, (ast.Dict, ast.Call, ast.Name, ast.Expr, ast.Constant, ast.List, ast.Tuple)):
                    if isinstance(n.value, ast.Dict):
                        try:
                            task_meta = ast.literal_eval(n.value)
                        except Exception:
                            task_meta = None
                        break
        if not isinstance(task_meta, dict):
            return None
        required = ["name", "version", "retries", "tags", "schedule", "enabled"]
        for k in required:
            if k not in task_meta:
                return None
        if not isinstance(task_meta["name"], str):
            return None
        if not isinstance(task_meta["version"], str):
            return None
        if not isinstance(task_meta["retries"], int):
            return None
        if not isinstance(task_meta["tags"], list):
            return None
        if not isinstance(task_meta["schedule"], str):
            return None
        if not isinstance(task_meta["enabled"], bool):
            return None
        tags = []
        for t in task_meta["tags"]:
            if not isinstance(t, str):
                return None
            tags.append(t)
        task_meta["tags"] = tags
        return task_meta
    except Exception:
        return None


def _collect_tasks(workspace: Path) -> List[Dict[str, Any]]:
    tasks_dir = workspace / "tasks"
    if not tasks_dir.exists() or not tasks_dir.is_dir():
        return []
    metas: List[Dict[str, Any]] = []
    for py in sorted(tasks_dir.rglob("*.py")):
        meta = _parse_task_meta_from_py(py)
        if meta is not None:
            metas.append(meta)
    return metas


def _compute_assigned_queue(tags: List[str], rules: List[Dict[str, Any]], default_queue: str) -> str:
    tag_set = set(tags)
    for rule in rules:
        match_tags = rule.get("match_any_tag", [])
        send_to = rule.get("send_to", None)
        if not isinstance(match_tags, list) or send_to is None:
            continue
        if any(t in tag_set for t in match_tags):
            return str(send_to)
    return default_queue


def _expected_from_workspace(workspace: Path) -> Optional[Dict[str, Any]]:
    cfg_path = workspace / "config" / "workflows.yaml"
    cfg = _parse_config_yaml(cfg_path)
    if cfg is None:
        return None
    tasks = _collect_tasks(workspace)
    expected_manifest: List[Dict[str, Any]] = []
    for t in tasks:
        assigned = _compute_assigned_queue(t["tags"], cfg["routing_rules"], cfg["default_queue"])
        expected_manifest.append({
            "name": t["name"],
            "version": t["version"],
            "enabled": t["enabled"],
            "retries": t["retries"],
            "schedule": t["schedule"],
            "tags": t["tags"],
            "assigned_queue": assigned,
        })
    expected_manifest.sort(key=lambda x: (x["name"], x["version"]))
    expected_routes = []
    for e in expected_manifest:
        expected_routes.append({
            "name": e["name"],
            "version": e["version"],
            "enabled": e["enabled"],
            "retries": e["retries"],
            "assigned_queue": e["assigned_queue"],
            "tags": e["tags"],
        })
    total_tasks = len(expected_manifest)
    enabled_tasks = sum(1 for e in expected_manifest if e["enabled"])
    disabled_tasks = total_tasks - enabled_tasks
    enabled_per_queue: Dict[str, int] = {}
    for e in expected_manifest:
        if e["enabled"]:
            q = e["assigned_queue"]
            enabled_per_queue[q] = enabled_per_queue.get(q, 0) + 1
    if enabled_tasks > 0:
        avg_retries_enabled = sum(e["retries"] for e in expected_manifest if e["enabled"]) / float(enabled_tasks)
    else:
        avg_retries_enabled = 0.0
    if total_tasks > 0:
        retries_list = [e["retries"] for e in expected_manifest]
        min_retries = min(retries_list)
        max_retries = max(retries_list)
    else:
        min_retries = 0
        max_retries = 0
    tag_freq_enabled: Dict[str, int] = {}
    for e in expected_manifest:
        if e["enabled"]:
            unique_tags = set(e["tags"])
            for t in unique_tags:
                tag_freq_enabled[t] = tag_freq_enabled.get(t, 0) + 1

    return {
        "config": cfg,
        "manifest": expected_manifest,
        "routes": expected_routes,
        "summary": {
            "total_tasks": total_tasks,
            "enabled_tasks": enabled_tasks,
            "disabled_tasks": disabled_tasks,
            "enabled_per_queue": enabled_per_queue,
            "avg_retries_enabled": avg_retries_enabled,
            "min_retries": min_retries,
            "max_retries": max_retries,
            "tag_freq_enabled": tag_freq_enabled,
        }
    }


def _parse_csv_file(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None


def _extract_int_from_line(lines: List[str], label: str) -> Optional[int]:
    pattern = re.compile(rf"{re.escape(label)}\s*:\s*(\d+)", re.IGNORECASE)
    for line in lines:
        m = pattern.search(line)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
    return None


def _extract_float_from_line(lines: List[str], label: str) -> Optional[float]:
    pattern = re.compile(rf"{re.escape(label)}\s*:\s*([-+]?\d+(\.\d+)?)", re.IGNORECASE)
    for line in lines:
        m = pattern.search(line)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                return None
    return None


def _extract_section_map(lines: List[str], section_label: str) -> Dict[str, int]:
    results: Dict[str, int] = {}
    start_idx = None
    for i, line in enumerate(lines):
        if section_label.lower() in line.lower():
            start_idx = i + 1
            break
    if start_idx is None:
        return results
    for j in range(start_idx, len(lines)):
        line = lines[j].strip()
        if line == "":
            break
        m = re.match(r"^\s*[-*\s]*([A-Za-z0-9_\-./]+)\s*[:\-–>\s]+\s*(\d+)\s*$", line)
        if m:
            key = m.group(1)
            val = int(m.group(2))
            results[key] = val
            continue
        tokens = line.split()
        if tokens and re.match(r"^\d+$", tokens[-1]):
            key = " ".join(tokens[:-1]).strip(":-")
            if key:
                results[key] = int(tokens[-1])
                continue
    return results


def _extract_tag_freq(lines: List[str], section_label: str) -> Dict[str, int]:
    return _extract_section_map(lines, section_label)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "manifest_present_and_valid": 0.0,
        "manifest_contents_correct": 0.0,
        "routes_csv_present_and_header": 0.0,
        "routes_csv_rows_correct": 0.0,
        "routes_manifest_consistency": 0.0,
        "summary_present": 0.0,
        "summary_totals_correct": 0.0,
        "summary_per_queue_correct": 0.0,
        "summary_retries_stats_correct": 0.0,
        "summary_tag_frequencies_correct": 0.0,
    }

    expected = _expected_from_workspace(workspace)
    output_dir = workspace / "output"
    manifest_path = output_dir / "tasks_manifest.json"
    routes_path = output_dir / "routes.csv"
    summary_path = output_dir / "summary.txt"

    manifest = _load_json_safe(manifest_path)
    if isinstance(manifest, list):
        required_keys = {"name", "version", "enabled", "retries", "schedule", "tags", "assigned_queue"}
        structure_ok = True
        for item in manifest:
            if not isinstance(item, dict):
                structure_ok = False
                break
            if not required_keys.issubset(set(item.keys())):
                structure_ok = False
                break
            if not isinstance(item["name"], str):
                structure_ok = False
                break
            if not isinstance(item["version"], str):
                structure_ok = False
                break
            if not isinstance(item["enabled"], bool):
                structure_ok = False
                break
            if not isinstance(item["retries"], int):
                structure_ok = False
                break
            if not isinstance(item["schedule"], str):
                structure_ok = False
                break
            if not isinstance(item["tags"], list):
                structure_ok = False
                break
            if not isinstance(item["assigned_queue"], str):
                structure_ok = False
                break
        if structure_ok:
            scores["manifest_present_and_valid"] = 1.0

    if expected is not None and isinstance(manifest, list):
        exp_by_key = {(e["name"], e["version"]): e for e in expected["manifest"]}
        man_by_key = {}
        try:
            for item in manifest:
                man_by_key[(item["name"], item["version"])] = item
            if set(exp_by_key.keys()) == set(man_by_key.keys()):
                all_ok = True
                for key, e in exp_by_key.items():
                    m = man_by_key[key]
                    if m["enabled"] != e["enabled"]:
                        all_ok = False
                        break
                    if m["retries"] != e["retries"]:
                        all_ok = False
                        break
                    if m["schedule"] != e["schedule"]:
                        all_ok = False
                        break
                    if m["assigned_queue"] != e["assigned_queue"]:
                        all_ok = False
                        break
                    if m["tags"] != e["tags"]:
                        all_ok = False
                        break
                if all_ok:
                    scores["manifest_contents_correct"] = 1.0
        except Exception:
            pass

    csv_parsed = _parse_csv_file(routes_path)
    if csv_parsed is not None:
        header, rows = csv_parsed
        expected_header = ["name", "version", "enabled", "retries", "assigned_queue", "tags"]
        if header == expected_header:
            scores["routes_csv_present_and_header"] = 1.0

    if expected is not None and csv_parsed is not None:
        header, rows = csv_parsed
        exp_by_name = {e["name"]: e for e in expected["routes"]}
        try:
            row_by_name: Dict[str, Dict[str, str]] = {}
            for r in rows:
                row_by_name[r.get("name", "")] = r
            names_match = set(row_by_name.keys()) == set(exp_by_name.keys())
            if names_match and len(rows) == len(expected["routes"]):
                all_ok = True
                for name, exp in exp_by_name.items():
                    r = row_by_name.get(name)
                    if r is None:
                        all_ok = False
                        break
                    if r.get("version", "") != exp["version"]:
                        all_ok = False
                        break
                    enabled_val = _parse_bool_str(r.get("enabled", ""))
                    if enabled_val is None or enabled_val != exp["enabled"]:
                        all_ok = False
                        break
                    try:
                        retries_val = int(r.get("retries", ""))
                    except Exception:
                        all_ok = False
                        break
                    if retries_val != exp["retries"]:
                        all_ok = False
                        break
                    if r.get("assigned_queue", "") != exp["assigned_queue"]:
                        all_ok = False
                        break
                    tags_field = r.get("tags", "")
                    parsed_tags = [t.strip() for t in tags_field.split(";")] if tags_field != "" else []
                    if parsed_tags != exp["tags"]:
                        all_ok = False
                        break
                if all_ok:
                    scores["routes_csv_rows_correct"] = 1.0
        except Exception:
            pass

    if isinstance(manifest, list) and csv_parsed is not None:
        header, rows = csv_parsed
        try:
            man_map = { (m["name"], m["version"]): m for m in manifest if isinstance(m, dict) }
            route_map = { (r.get("name",""), r.get("version","")): r for r in rows }
            keys = set(man_map.keys()) & set(route_map.keys())
            if keys:
                consistent = True
                for k in keys:
                    m = man_map[k]
                    r = route_map[k]
                    if m.get("assigned_queue") != r.get("assigned_queue"):
                        consistent = False
                        break
                    tags_field = r.get("tags", "")
                    parsed_tags = [t.strip() for t in tags_field.split(";")] if tags_field != "" else []
                    if parsed_tags != m.get("tags"):
                        consistent = False
                        break
                if len(man_map) == len(route_map) and consistent:
                    scores["routes_manifest_consistency"] = 1.0
        except Exception:
            pass

    summary_text = _read_text_safe(summary_path)
    if summary_text is not None:
        scores["summary_present"] = 1.0

    if expected is not None and summary_text is not None:
        lines = [ln.strip() for ln in summary_text.splitlines()]
        total_val = _extract_int_from_line(lines, "Total tasks")
        enabled_val = _extract_int_from_line(lines, "Enabled tasks")
        disabled_val = _extract_int_from_line(lines, "Disabled tasks")
        if (total_val == expected["summary"]["total_tasks"] and
            enabled_val == expected["summary"]["enabled_tasks"] and
            disabled_val == expected["summary"]["disabled_tasks"]):
            scores["summary_totals_correct"] = 1.0

        per_queue_reported = _extract_section_map(lines, "Enabled tasks per queue")
        per_queue_ok = True
        for q, cnt in expected["summary"]["enabled_per_queue"].items():
            r_cnt = per_queue_reported.get(q)
            if r_cnt != cnt:
                per_queue_ok = False
                break
        if expected["summary"]["enabled_tasks"] == 0:
            per_queue_ok = True
        if per_queue_ok:
            scores["summary_per_queue_correct"] = 1.0

        avg_retries_val = _extract_float_from_line(lines, "Average retries across enabled tasks")
        min_retries_val = _extract_int_from_line(lines, "Minimum retries")
        max_retries_val = _extract_int_from_line(lines, "Maximum retries")
        retries_ok = True
        if avg_retries_val is None or abs(avg_retries_val - float(expected["summary"]["avg_retries_enabled"])) > 1e-6:
            retries_ok = False
        if min_retries_val != expected["summary"]["min_retries"]:
            retries_ok = False
        if max_retries_val != expected["summary"]["max_retries"]:
            retries_ok = False
        if retries_ok:
            scores["summary_retries_stats_correct"] = 1.0

        tag_freq_reported = _extract_tag_freq(lines, "Tag frequencies among enabled tasks")
        tag_ok = True
        for tag, cnt in expected["summary"]["tag_freq_enabled"].items():
            if tag_freq_reported.get(tag) != cnt:
                tag_ok = False
                break
        if expected["summary"]["enabled_tasks"] == 0:
            tag_ok = True
        if tag_ok:
            scores["summary_tag_frequencies_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()