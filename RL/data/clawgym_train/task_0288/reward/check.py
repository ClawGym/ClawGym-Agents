import json
import sys
import re
import hashlib
import csv
from pathlib import Path
from datetime import datetime


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _read_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_parse_env_spec(yaml_path: Path) -> dict:
    content = _read_text(yaml_path)
    if not content:
        return {}
    lines = content.splitlines()
    data = {
        "project": None,
        "python_version": None,
        "dependencies": [],
        "entry_script": None,
        "entry_output": None,
    }
    in_deps = False
    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"^dependencies:\s*$", stripped):
            in_deps = True
            continue
        if in_deps:
            if re.match(r"^- ", stripped):
                dep = stripped[2:].strip()
                dep = dep.strip("'").strip('"')
                if dep:
                    data["dependencies"].append(dep)
                continue
            else:
                in_deps = False
        m = re.match(r"^project:\s*(.+)$", stripped)
        if m:
            val = m.group(1).strip().strip("'").strip('"')
            data["project"] = val
            continue
        m = re.match(r"^python_version:\s*(.+)$", stripped)
        if m:
            val = m.group(1).strip().strip("'").strip('"')
            data["python_version"] = val
            continue
        m = re.match(r"^entry_script:\s*(.+)$", stripped)
        if m:
            val = m.group(1).strip().strip("'").strip('"')
            data["entry_script"] = val
            continue
        m = re.match(r"^entry_output:\s*(.+)$", stripped)
        if m:
            val = m.group(1).strip().strip("'").strip('"')
            data["entry_output"] = val
            continue
    return data


def _csv_read_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = list(reader)
            return headers, rows
    except Exception:
        return [], []


def _compute_summary_from_input(input_csv: Path):
    headers, rows = _csv_read_rows(input_csv)
    if not rows or not headers:
        return None
    required_cols = {"Product", "Ingredient", "BatchSizeKg", "CostPerKg"}
    if not required_cols.issubset(set(headers)):
        return None
    groups = {}
    for r in rows:
        product = (r.get("Product") or "").strip()
        ingredient = (r.get("Ingredient") or "").strip()
        try:
            bkg = float(r.get("BatchSizeKg", "") or 0.0)
        except Exception:
            bkg = 0.0
        try:
            cpk = float(r.get("CostPerKg", "") or 0.0)
        except Exception:
            cpk = 0.0
        if product not in groups:
            groups[product] = {
                "total_batch_kg": 0.0,
                "total_weighted_cost": 0.0,
                "ingredients": set(),
            }
        g = groups[product]
        g["total_batch_kg"] += bkg
        g["total_weighted_cost"] += bkg * cpk
        if ingredient:
            g["ingredients"].add(ingredient)
    summary = []
    for product, g in groups.items():
        tb = g["total_batch_kg"]
        twc = g["total_weighted_cost"]
        num_ing = len(g["ingredients"])
        avg = (twc / tb) if tb else 0.0
        summary.append({
            "Product": product,
            "total_batch_kg": tb,
            "num_ingredients": num_ing,
            "avg_cost_per_kg": avg,
        })
    summary.sort(key=lambda x: x["Product"])
    return summary


def _parse_output_summary_csv(path: Path):
    headers, rows = _csv_read_rows(path)
    if not headers or not rows:
        return None, None
    expected_cols = ["Product", "total_batch_kg", "num_ingredients", "avg_cost_per_kg"]
    if headers != expected_cols:
        return None, None
    parsed = []
    for r in rows:
        product = r.get("Product", "").strip()
        try:
            total_batch_kg = float(r.get("total_batch_kg", "") or 0.0)
        except Exception:
            return None, None
        try:
            num_ingredients = int(float(r.get("num_ingredients", "") or 0.0))
        except Exception:
            return None, None
        try:
            avg_cost_per_kg = float(r.get("avg_cost_per_kg", "") or 0.0)
        except Exception:
            return None, None
        parsed.append({
            "Product": product,
            "total_batch_kg": total_batch_kg,
            "num_ingredients": num_ingredients,
            "avg_cost_per_kg": avg_cost_per_kg,
        })
    return headers, parsed


def _nearly_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _sha256_of_file(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _count_input_rows(path: Path) -> int:
    _, rows = _csv_read_rows(path)
    return len(rows)


def _count_unique_products(path: Path) -> int:
    headers, rows = _csv_read_rows(path)
    if not rows or not headers:
        return 0
    prods = set()
    for r in rows:
        prods.add((r.get("Product") or "").strip())
    return len(prods)


def _find_section(text: str, title: str) -> str:
    lines = text.splitlines()
    idx = -1
    for i, ln in enumerate(lines):
        if title.lower() in ln.lower():
            idx = i
            break
    if idx == -1:
        return ""
    known_titles = [
        "Environment Summary",
        "Data Summary",
        "Deployment Outcome",
        "Next Steps",
        "Action Items",
        "Constraints",
        "Open Questions",
    ]
    buf = []
    for j in range(idx + 1, len(lines)):
        ln = lines[j]
        if ln.strip().startswith("#"):
            break
        title_starts = tuple(t.lower() for t in known_titles)
        if ln.strip().lower().startswith(title_starts) and (title.lower() not in ln.strip().lower()):
            break
        buf.append(ln)
    return "\n".join(buf).strip()


def _extract_bullets(section_text: str) -> list:
    bullets = []
    for ln in section_text.splitlines():
        s = ln.strip()
        if s.startswith("- ") or s.startswith("* "):
            bullets.append(s[2:].strip())
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "requirements_parsed_correctly": 0.0,
        "setup_sh_venv_install_freeze": 0.0,
        "installed_packages_snapshot_contains_dependencies": 0.0,
        "run_summary_sh_uses_venv_and_entry_script": 0.0,
        "summary_csv_correct": 0.0,
        "run_metadata_json_correct": 0.0,
        "status_update_content": 0.0,
        "meeting_notes_content": 0.0,
    }

    env_spec_path = workspace / "input" / "env_spec.yaml"
    spec = _safe_parse_env_spec(env_spec_path)
    deps = spec.get("dependencies") or []
    py_ver_spec = spec.get("python_version")
    entry_script = spec.get("entry_script")
    entry_output = spec.get("entry_output")

    req_path = workspace / "env" / "requirements.txt"
    req_text = _read_text(req_path)
    try:
        if deps and req_text:
            expected_lines = sorted(deps, key=lambda x: x.split("==")[0].lower())
            actual_lines = [ln.strip() for ln in req_text.splitlines() if ln.strip() != ""]
            if actual_lines == expected_lines:
                scores["requirements_parsed_correctly"] = 1.0
    except Exception:
        scores["requirements_parsed_correctly"] = 0.0

    setup_sh = workspace / "env" / "setup.sh"
    setup_text = _read_text(setup_sh)
    try:
        if setup_text:
            has_shebang = setup_text.lstrip().startswith("#!")
            mentions_venv = "env/.venv" in setup_text or "./env/.venv" in setup_text
            installs_reqs = ("-r env/requirements.txt" in setup_text) or ("-r ./env/requirements.txt" in setup_text)
            writes_freeze = ("pip freeze" in setup_text or "pip list --format=freeze" in setup_text) and ("env/installed_packages.txt" in setup_text or "./env/installed_packages.txt" in setup_text)
            if has_shebang and mentions_venv and installs_reqs and writes_freeze:
                scores["setup_sh_venv_install_freeze"] = 1.0
    except Exception:
        scores["setup_sh_venv_install_freeze"] = 0.0

    installed = workspace / "env" / "installed_packages.txt"
    installed_text = _read_text(installed)
    try:
        if installed_text and deps:
            need_pkgs = [d.split("==")[0].lower() for d in deps if "==" in d]
            found = []
            for pkg in need_pkgs:
                if re.search(rf"(?im)^{re.escape(pkg)}==", installed_text):
                    found.append(pkg)
            if len(found) == len(need_pkgs):
                scores["installed_packages_snapshot_contains_dependencies"] = 1.0
    except Exception:
        scores["installed_packages_snapshot_contains_dependencies"] = 0.0

    run_sh = workspace / "run_summary.sh"
    run_text = _read_text(run_sh)
    try:
        if run_text and entry_script:
            uses_venv = ("env/.venv/bin/python" in run_text) or ("./env/.venv/bin/python" in run_text)
            references_script = (entry_script in run_text)
            ensures_output = (entry_output in run_text) or ("output/formulation_summary.csv" in run_text)
            if uses_venv and references_script and ensures_output:
                scores["run_summary_sh_uses_venv_and_entry_script"] = 1.0
    except Exception:
        scores["run_summary_sh_uses_venv_and_entry_script"] = 0.0

    input_csv = workspace / "input" / "data" / "formulations.csv"
    expected_summary = None
    if input_csv.exists():
        expected_summary = _compute_summary_from_input(input_csv)
    out_csv = workspace / "output" / "formulation_summary.csv"
    headers, parsed_out = _parse_output_summary_csv(out_csv)
    try:
        if expected_summary is not None and parsed_out is not None:
            if len(expected_summary) == len(parsed_out):
                out_sorted = all(parsed_out[i]["Product"] <= parsed_out[i + 1]["Product"] for i in range(len(parsed_out) - 1))
                if out_sorted:
                    mapping = {r["Product"]: r for r in parsed_out}
                    ok = True
                    for exp in expected_summary:
                        prod = exp["Product"]
                        if prod not in mapping:
                            ok = False
                            break
                        got = mapping[prod]
                        if not _nearly_equal(exp["total_batch_kg"], got["total_batch_kg"]):
                            ok = False
                            break
                        if int(exp["num_ingredients"]) != int(got["num_ingredients"]):
                            ok = False
                            break
                        if not _nearly_equal(exp["avg_cost_per_kg"], got["avg_cost_per_kg"]):
                            ok = False
                            break
                    if ok:
                        scores["summary_csv_correct"] = 1.0
    except Exception:
        scores["summary_csv_correct"] = 0.0

    meta_path = workspace / "output" / "run_metadata.json"
    meta = _read_json(meta_path)
    try:
        if meta is not None and isinstance(meta, dict):
            req_keys = {"source_csv_sha256", "rows_in", "rows_out", "run_timestamp", "python_version"}
            if req_keys.issubset(set(meta.keys())):
                expected_sha = _sha256_of_file(input_csv) if input_csv.exists() else ""
                sha_ok = (meta.get("source_csv_sha256") == expected_sha and expected_sha != "")
                rows_in_ok = isinstance(meta.get("rows_in"), int) and (meta["rows_in"] == _count_input_rows(input_csv))
                rows_out_ok = isinstance(meta.get("rows_out"), int) and (meta["rows_out"] == _count_unique_products(input_csv))
                ts = str(meta.get("run_timestamp", ""))
                ts_ok = bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$", ts))
                pv = str(meta.get("python_version", ""))
                py_ok = bool(re.match(r"^\d+\.\d+\.\d+$", pv))
                if sha_ok and rows_in_ok and rows_out_ok and ts_ok and py_ok:
                    scores["run_metadata_json_correct"] = 1.0
    except Exception:
        scores["run_metadata_json_correct"] = 0.0

    status_md = workspace / "output" / "status_update.md"
    status_text = _read_text(status_md)
    try:
        if status_text:
            sections_present = all(s in status_text for s in [
                "Environment Summary", "Data Summary", "Deployment Outcome", "Next Steps"
            ])
            env_ok = False
            if spec:
                env_ok = True
                if not (py_ver_spec and py_ver_spec in status_text):
                    env_ok = False
                num_deps = len(deps)
                if not re.search(rf"\b{num_deps}\b", status_text):
                    env_ok = False
                if "env/.venv" not in status_text and "./env/.venv" not in status_text:
                    env_ok = False
            data_ok = False
            if input_csv.exists():
                uniq = _count_unique_products(input_csv)
                rin = _count_input_rows(input_csv)
                has_uniq = re.search(rf"\b{uniq}\b", status_text) is not None
                has_rin = re.search(rf"\b{rin}\b", status_text) is not None
                data_ok = has_uniq and has_rin
            required_paths = [
                "env/requirements.txt",
                "env/setup.sh",
                "env/installed_packages.txt",
                "run_summary.sh",
                "output/formulation_summary.csv",
                "output/run_metadata.json",
                "output/status_update.md",
                "output/meeting_notes.md",
            ]
            outcome_ok = all(p in status_text for p in required_paths)
            next_steps_sec = _find_section(status_text, "Next Steps")
            bullets = _extract_bullets(next_steps_sec)
            bullets_ok = 2 <= len(bullets) <= 4
            if sections_present and env_ok and data_ok and outcome_ok and bullets_ok:
                scores["status_update_content"] = 1.0
    except Exception:
        scores["status_update_content"] = 0.0

    notes_md = workspace / "output" / "meeting_notes.md"
    notes_text = _read_text(notes_md)
    owner_md = workspace / "input" / "owner_feedback.md"
    owner_text = _read_text(owner_md)
    try:
        if notes_text and owner_text:
            has_title = "Formulation Summarizer Deployment Touchpoint".lower() in notes_text.lower()
            has_date = re.search(r"\d{4}-\d{2}-\d{2}", notes_text) is not None
            header_ok = has_title and has_date

            priority_lines = []
            for ln in owner_text.splitlines():
                if "PRIORITY:" in ln:
                    priority_lines.append(ln.split("PRIORITY:", 1)[1].strip())
            top3 = priority_lines[:3]

            ai_sec = _find_section(notes_text, "Action Items")
            ai_bullets = _extract_bullets(ai_sec)
            ai_ok = False
            if len(ai_bullets) == 3 and top3:
                need1 = any(re.search(r"\bweighted\b", b, flags=re.I) and re.search(r"\bcost\b", b, flags=re.I) for b in ai_bullets)
                need2 = any(
                    (re.search(r"\bsingle\b", b, flags=re.I) or re.search(r"\bone-?command\b", b, flags=re.I))
                    and re.search(r"\breproducible\b", b, flags=re.I)
                    for b in ai_bullets
                )
                need3 = any(re.search(r"\bSHA256\b", b) and re.search(r"\btimestamp\b", b, flags=re.I) for b in ai_bullets)
                assignments_ok = all(("Ops/Dev" in b) for b in ai_bullets)
                due_ok = all((re.search(r"\bTBD\b", b, flags=re.I) or re.search(r"\d{4}-\d{2}-\d{2}", b)) for b in ai_bullets)
                ai_ok = need1 and need2 and need3 and assignments_ok and due_ok

            cons_sec = _find_section(notes_text, "Constraints")
            cons_lines = cons_sec.lower()
            cons_ok = all([
                ("local" in cons_lines and "cloud" in cons_lines),
                ("python 3.10" in cons_lines),
                ("posix" in cons_lines),
            ])

            oq_sec = _find_section(notes_text, "Open Questions")
            oq_lines = oq_sec.lower()
            oq_ok = ("top-2" in oq_lines and "cost drivers" in oq_lines) and ("allergen" in oq_lines)

            if header_ok and ai_ok and cons_ok and oq_ok:
                scores["meeting_notes_content"] = 1.0
    except Exception:
        scores["meeting_notes_content"] = 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()