import json
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Set


ALLOWED_BOOTSTRAP_PREFIXES = (
    "btn",
    "navbar",
    "container",
    "row",
    "col-",
    "alert",
    "label",
    "badge",
    "dropdown",
    "list-group",
    "form-control",
    "input-group",
    "panel",
    "card",
)


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


def _is_iso8601(s: Any) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _normalize_path_for_compare(p: Optional[str]) -> Optional[str]:
    if p is None:
        return None
    p2 = p.replace("\\", "/")
    while p2.startswith("./"):
        p2 = p2[2:]
    while "//" in p2:
        p2 = p2.replace("//", "/")
    return p2


def _is_absolute_path_like(p: str) -> bool:
    if p.startswith("/"):
        return True
    if re.match(r"^[A-Za-z]:[\\/]", p):
        return True
    return False


def _paths_are_relative_forward_slash(report: Dict[str, Any]) -> bool:
    def has_backslash(s: str) -> bool:
        return "\\" in s

    for item in report.get("controllers", []):
        f = item.get("file")
        if not isinstance(f, str):
            return False
        if _is_absolute_path_like(f) or has_backslash(f):
            return False
    for item in report.get("directives", []):
        f = item.get("file")
        if not isinstance(f, str):
            return False
        if _is_absolute_path_like(f) or has_backslash(f):
            return False
        turl = item.get("templateUrl", None)
        if turl is not None:
            if not isinstance(turl, str):
                return False
            if _is_absolute_path_like(turl) or has_backslash(turl):
                return False
    for item in report.get("templates", []):
        f = item.get("file")
        if not isinstance(f, str):
            return False
        if _is_absolute_path_like(f) or has_backslash(f):
            return False
    return True


def _extract_module_name(js_text: str) -> Optional[str]:
    m = re.search(r"angular\.module\(\s*['\"]([^'\"]+)['\"]\s*,", js_text)
    if m:
        return m.group(1)
    return None


def _extract_controllers(js_text: str) -> List[str]:
    return re.findall(r"\.controller\(\s*['\"]([^'\"]+)['\"]\s*,", js_text)


def _extract_directives(js_text: str) -> List[Tuple[str, Optional[str]]]:
    results: List[Tuple[str, Optional[str]]] = []
    for m in re.finditer(r"\.directive\(\s*['\"]([^'\"]+)['\"]\s*,", js_text):
        name = m.group(1)
        start = m.start()
        substr = js_text[start:]
        end_idx = substr.find("});")
        if end_idx == -1:
            end_idx = substr.find("})")
            if end_idx == -1:
                end_idx = len(substr)
        body = substr[: end_idx + 3] if end_idx != -1 else substr
        tm = re.search(r"templateUrl\s*:\s*['\"]([^'\"]+)['\"]", body)
        turl = tm.group(1) if tm else None
        results.append((name, turl))
    return results


def _scan_js_artifacts(app_dir: Path, workspace: Path) -> Tuple[Optional[str], List[Dict[str, str]], List[Dict[str, Optional[str]]]]:
    module_name: Optional[str] = None
    module_file = app_dir / "app.module.js"
    js_text = _read_text(module_file)
    if js_text is not None:
        mn = _extract_module_name(js_text)
        if mn:
            module_name = mn

    controllers: List[Dict[str, str]] = []
    directives: List[Dict[str, Optional[str]]] = []

    if app_dir.exists():
        for js_path in sorted(app_dir.rglob("*.js")):
            text = _read_text(js_path)
            if not text:
                continue
            for c_name in _extract_controllers(text):
                controllers.append(
                    {
                        "name": c_name,
                        "file": _normalize_path_for_compare(str(js_path.relative_to(workspace).as_posix())),
                    }
                )
            for d_name, t_url in _extract_directives(text):
                directives.append(
                    {
                        "name": d_name,
                        "file": _normalize_path_for_compare(str(js_path.relative_to(workspace).as_posix())),
                        "templateUrl": _normalize_path_for_compare(t_url) if t_url is not None else None,
                    }
                )

    seen_ctrls: Set[Tuple[str, str]] = set()
    uniq_controllers: List[Dict[str, str]] = []
    for c in controllers:
        key = (c["name"], c["file"])
        if key not in seen_ctrls:
            seen_ctrls.add(key)
            uniq_controllers.append(c)

    seen_dirs: Set[Tuple[str, str, Optional[str]]] = set()
    uniq_directives: List[Dict[str, Optional[str]]] = []
    for d in directives:
        key = (d["name"], d["file"], d["templateUrl"])
        if key not in seen_dirs:
            seen_dirs.add(key)
            uniq_directives.append(d)

    return module_name, uniq_controllers, uniq_directives


def _extract_bootstrap_classes_from_html(html_text: str) -> Set[str]:
    classes: Set[str] = set()
    for m in re.finditer(r'class\s*=\s*["\']([^"\']+)["\']', html_text, re.IGNORECASE):
        content = m.group(1)
        for token in content.split():
            for prefix in ALLOWED_BOOTSTRAP_PREFIXES:
                if token.startswith(prefix):
                    classes.add(token)
                    break
    return classes


def _scan_templates(templates_dir: Path, workspace: Path) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    if not templates_dir.exists():
        return result
    for html_path in sorted(templates_dir.rglob("*.html")):
        txt = _read_text(html_path)
        if txt is None:
            bootstrap_classes: List[str] = []
        else:
            cls_set = _extract_bootstrap_classes_from_html(txt)
            bootstrap_classes = sorted(cls_set)
        rel = _normalize_path_for_compare(str(html_path.relative_to(workspace).as_posix()))
        result[rel] = bootstrap_classes
    return result


def _build_expected_report(workspace: Path) -> Dict[str, Any]:
    app_dir = workspace / "app"
    templates_dir = app_dir / "templates"

    module_name, controllers, directives = _scan_js_artifacts(app_dir, workspace)
    module_str = module_name if module_name is not None else ""

    controllers_sorted = sorted(controllers, key=lambda x: (x["name"], x["file"]))
    directives_sorted = sorted(directives, key=lambda x: (x["name"], x["file"], x.get("templateUrl") or ""))

    templates_map = _scan_templates(templates_dir, workspace)
    template_files_sorted = sorted(templates_map.keys())

    used_by_map: Dict[str, List[str]] = {tpl: [] for tpl in template_files_sorted}
    for d in directives_sorted:
        turl = d.get("templateUrl")
        if turl and turl in used_by_map:
            used_by_map[turl].append(d["name"])
    for tpl in used_by_map:
        used_by_map[tpl].sort()

    templates_list: List[Dict[str, Any]] = []
    for tpl in template_files_sorted:
        templates_list.append(
            {
                "file": tpl,
                "bootstrap_classes": templates_map.get(tpl, []),
                "used_by": used_by_map.get(tpl, []),
            }
        )

    unique_classes: Set[str] = set()
    for classes in templates_map.values():
        unique_classes.update(classes)
    totals = {
        "controllers": len(controllers_sorted),
        "directives": len(directives_sorted),
        "templates": len(templates_list),
        "unique_bootstrap_classes": len(unique_classes),
    }

    report = {
        "module": module_str,
        "controllers": controllers_sorted,
        "directives": directives_sorted,
        "templates": templates_list,
        "totals": totals,
    }
    return report


def _normalize_report_for_compare(report: Dict[str, Any]) -> Dict[str, Any]:
    norm: Dict[str, Any] = {}
    norm["module"] = report.get("module", "")

    controllers = report.get("controllers", [])
    n_controllers: List[Dict[str, str]] = []
    for c in controllers:
        name = c.get("name")
        file = _normalize_path_for_compare(c.get("file", "")) if isinstance(c.get("file"), str) else c.get("file")
        n_controllers.append({"name": name, "file": file})
    n_controllers = sorted(n_controllers, key=lambda x: (x.get("name"), x.get("file") or ""))
    norm["controllers"] = n_controllers

    directives = report.get("directives", [])
    n_directives: List[Dict[str, Optional[str]]] = []
    for d in directives:
        name = d.get("name")
        file = _normalize_path_for_compare(d.get("file", "")) if isinstance(d.get("file"), str) else d.get("file")
        turl = d.get("templateUrl", None)
        if isinstance(turl, str):
            turl = _normalize_path_for_compare(turl)
        elif turl is not None:
            turl = None
        n_directives.append({"name": name, "file": file, "templateUrl": turl})
    n_directives = sorted(n_directives, key=lambda x: (x.get("name"), x.get("file") or "", x.get("templateUrl") or ""))
    norm["directives"] = n_directives

    templates = report.get("templates", [])
    n_templates: List[Dict[str, Any]] = []
    for t in templates:
        file = t.get("file")
        if isinstance(file, str):
            file = _normalize_path_for_compare(file)
        classes = t.get("bootstrap_classes", [])
        if isinstance(classes, list):
            classes = sorted([c for c in classes if isinstance(c, str)])
        else:
            classes = []
        used_by = t.get("used_by", [])
        if isinstance(used_by, list):
            used_by = sorted([u for u in used_by if isinstance(u, str)])
        else:
            used_by = []
        n_templates.append({"file": file, "bootstrap_classes": classes, "used_by": used_by})
    n_templates = sorted(n_templates, key=lambda x: (x.get("file") or ""))
    norm["templates"] = n_templates

    totals = report.get("totals", {})
    n_totals = {
        "controllers": totals.get("controllers"),
        "directives": totals.get("directives"),
        "templates": totals.get("templates"),
        "unique_bootstrap_classes": totals.get("unique_bootstrap_classes"),
    }
    norm["totals"] = n_totals

    return norm


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "report_exists_and_valid_json": 0.0,
        "report_module_correct": 0.0,
        "report_controllers_correct": 0.0,
        "report_directives_correct": 0.0,
        "report_templates_files_and_used_by_correct": 0.0,
        "report_bootstrap_classes_correct": 0.0,
        "report_totals_correct": 0.0,
        "report_paths_relative_forward_slash": 0.0,
        "config_bootstrap_audit_section_valid": 0.0,
        "config_unique_class_count_matches_report": 0.0,
    }

    expected_report = _build_expected_report(workspace)

    report_path = workspace / "output" / "bootstrap_audit.json"
    report_obj = _load_json(report_path)
    if isinstance(report_obj, dict):
        scores["report_exists_and_valid_json"] = 1.0
    else:
        report_obj = None

    expected_norm = _normalize_report_for_compare(expected_report)
    student_norm = _normalize_report_for_compare(report_obj) if isinstance(report_obj, dict) else None

    if student_norm is not None:
        if isinstance(student_norm.get("module"), str) and student_norm["module"] == expected_norm["module"]:
            scores["report_module_correct"] = 1.0

    if student_norm is not None:
        exp_ctrls = expected_norm.get("controllers", [])
        stu_ctrls = student_norm.get("controllers", [])
        if isinstance(stu_ctrls, list):
            exp_set = {(c.get("name"), c.get("file")) for c in exp_ctrls}
            stu_set = {(c.get("name"), c.get("file")) for c in stu_ctrls}
            if exp_set == stu_set:
                scores["report_controllers_correct"] = 1.0

    if student_norm is not None:
        exp_dirs = expected_norm.get("directives", [])
        stu_dirs = student_norm.get("directives", [])
        if isinstance(stu_dirs, list):
            exp_set = {(d.get("name"), d.get("file"), d.get("templateUrl")) for d in exp_dirs}
            stu_set = {(d.get("name"), d.get("file"), d.get("templateUrl")) for d in stu_dirs}
            if exp_set == stu_set:
                scores["report_directives_correct"] = 1.0

    if student_norm is not None:
        exp_tpls = expected_norm.get("templates", [])
        stu_tpls = student_norm.get("templates", [])
        if isinstance(stu_tpls, list):
            exp_files = {t.get("file") for t in exp_tpls}
            stu_files = {t.get("file") for t in stu_tpls}
            files_ok = exp_files == stu_files
            used_by_ok = True
            if files_ok:
                exp_used_by_map = {t.get("file"): tuple(sorted(t.get("used_by", []))) for t in exp_tpls}
                stu_used_by_map = {t.get("file"): tuple(sorted(t.get("used_by", []))) for t in stu_tpls}
                used_by_ok = exp_used_by_map == stu_used_by_map
            if files_ok and used_by_ok:
                scores["report_templates_files_and_used_by_correct"] = 1.0

    if student_norm is not None:
        exp_tpls = expected_norm.get("templates", [])
        stu_tpls = student_norm.get("templates", [])
        classes_ok = True
        if isinstance(stu_tpls, list):
            exp_cls_map = {t.get("file"): tuple(sorted(t.get("bootstrap_classes", []))) for t in exp_tpls}
            stu_cls_map = {t.get("file"): tuple(sorted(t.get("bootstrap_classes", []))) for t in stu_tpls}
            classes_ok = exp_cls_map == stu_cls_map
        else:
            classes_ok = False
        if classes_ok:
            scores["report_bootstrap_classes_correct"] = 1.0

    if student_norm is not None:
        exp_tot = expected_norm.get("totals", {})
        stu_tot = student_norm.get("totals", {})
        if isinstance(stu_tot, dict):
            totals_ok = (
                stu_tot.get("controllers") == exp_tot.get("controllers")
                and stu_tot.get("directives") == exp_tot.get("directives")
                and stu_tot.get("templates") == exp_tot.get("templates")
                and stu_tot.get("unique_bootstrap_classes") == exp_tot.get("unique_bootstrap_classes")
            )
            if totals_ok:
                scores["report_totals_correct"] = 1.0

    if isinstance(report_obj, dict) and _paths_are_relative_forward_slash(report_obj):
        scores["report_paths_relative_forward_slash"] = 1.0

    config_path = workspace / "config" / "app.config.json"
    config_obj = _load_json(config_path)
    if isinstance(config_obj, dict):
        ba = config_obj.get("bootstrapAudit")
        ba_ok = False
        if isinstance(ba, dict):
            rp_ok = ba.get("reportPath") == "output/bootstrap_audit.json"
            ucc_ok = isinstance(ba.get("uniqueClassCount"), int) and ba.get("uniqueClassCount") == expected_report["totals"]["unique_bootstrap_classes"]
            ts_ok = _is_iso8601(ba.get("lastUpdated"))
            ba_ok = rp_ok and ucc_ok and ts_ok
        if ba_ok:
            scores["config_bootstrap_audit_section_valid"] = 1.0

        if isinstance(report_obj, dict) and isinstance(report_obj.get("totals"), dict) and isinstance(ba, dict):
            rep_ucc = report_obj.get("totals", {}).get("unique_bootstrap_classes")
            cfg_ucc = ba.get("uniqueClassCount")
            if isinstance(rep_ucc, int) and cfg_ucc == rep_ucc:
                scores["config_unique_class_count_matches_report"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()