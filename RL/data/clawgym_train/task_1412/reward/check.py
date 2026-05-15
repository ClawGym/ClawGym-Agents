import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_lines(path: Path) -> Optional[List[str]]:
    txt = _read_text(path)
    if txt is None:
        return None
    return txt.splitlines()


def _safe_load_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data, None
        return None, "not_a_dict"
    except Exception as e:
        return None, str(e)


def _list_inbox_drafts(inbox_dir: Path) -> List[Path]:
    if not inbox_dir.exists():
        return []
    return sorted([p for p in inbox_dir.glob("*.txt") if p.is_file()])


def _compute_code_metrics(src_dir: Path) -> Dict[str, object]:
    py_files = sorted([p for p in src_dir.rglob("*.py") if p.is_file()])
    num_python_files = len(py_files)
    total_nonempty_lines = 0
    function_count = 0
    imports = set()

    for p in py_files:
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []
        for line in lines:
            if line.strip() != "":
                total_nonempty_lines += 1
            stripped = line.lstrip()
            if stripped.startswith("def "):
                function_count += 1
            if stripped.startswith("import ") or stripped.startswith("from "):
                # skip comments
                if stripped.startswith("#"):
                    continue
                if stripped.startswith("import "):
                    after = stripped[len("import "):]
                    parts = [part.strip() for part in after.split(",")]
                    for part in parts:
                        if not part:
                            continue
                        mod = part.split()[0]
                        top = mod.split(".")[0]
                        if top:
                            imports.add(top)
                elif stripped.startswith("from "):
                    after = stripped[len("from "):]
                    pkg = after.split()[0] if after else ""
                    top = pkg.split(".")[0]
                    if top:
                        imports.add(top)
    unique_top_level_imports = sorted(imports)
    return {
        "num_python_files": num_python_files,
        "total_nonempty_lines": total_nonempty_lines,
        "function_count": function_count,
        "unique_top_level_imports": unique_top_level_imports,
    }


def _extract_readme_segment(content: str) -> Tuple[int, int, str]:
    start_marker = "<!--AUTO-SUMMARY-START-->"
    end_marker = "<!--AUTO-SUMMARY-END-->"
    start_idx = content.find(start_marker)
    end_idx = content.find(end_marker)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        return -1, -1, ""
    seg_start = start_idx + len(start_marker)
    seg_content = content[seg_start:end_idx]
    return seg_start, end_idx, seg_content


def _parse_bullet_metrics(segment: str) -> Optional[Dict[str, object]]:
    # Expect exactly five markdown bullet lines beginning with "- "
    lines = [ln.strip() for ln in segment.strip().splitlines() if ln.strip() != ""]
    bullet_lines = [ln for ln in lines if ln.startswith("- ")]
    if len(bullet_lines) != 5 or any(not ln.startswith("- ") for ln in bullet_lines):
        return None
    expected_keys = [
        "Email drafts rewritten",
        "Python files",
        "Functions",
        "Non-empty lines",
        "Top-level imports",
    ]
    values: Dict[str, object] = {}
    for idx, ln in enumerate(bullet_lines):
        if ":" not in ln:
            return None
        left, right = ln[2:].split(":", 1)
        left = left.strip()
        right = right.strip()
        if left != expected_keys[idx]:
            return None
        if left == "Top-level imports":
            if right == "":
                items = []
            else:
                items = [item.strip() for item in right.split(",")]
            values["unique_top_level_imports"] = [i for i in items if i != ""]
        elif left == "Email drafts rewritten":
            try:
                values["email_rewritten"] = int(right)
            except Exception:
                return None
        elif left == "Python files":
            try:
                values["num_python_files"] = int(right)
            except Exception:
                return None
        elif left == "Functions":
            try:
                values["function_count"] = int(right)
            except Exception:
                return None
        elif left == "Non-empty lines":
            try:
                values["total_nonempty_lines"] = int(right)
            except Exception:
                return None
    if "unique_top_level_imports" not in values:
        return None
    if len(lines) != 5:
        return None
    return values


def _tokenize_words(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9']+", text.lower())


def _contains_hedging(tokens: List[str], phrases: List[str]) -> bool:
    toks = tokens
    joined = " ".join(toks)
    for phrase in phrases:
        p_toks = _tokenize_words(phrase)
        if not p_toks:
            continue
        if len(p_toks) == 1:
            if p_toks[0] in toks:
                return True
        else:
            if " ".join(p_toks) in joined:
                return True
    return False


def _join_body_lines_as_paragraph(lines: List[str]) -> str:
    parts = []
    for ln in lines:
        s = ln.strip()
        if s != "":
            parts.append(s)
    return " ".join(parts)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_present": 0.0,
        "run_succeeded": 0.0,
        "stdout_summary_ok": 0.0,
        "original_drafts_unchanged": 0.0,
        "rewritten_files_count": 0.0,
        "subjects_preserved": 0.0,
        "body_single_paragraph": 0.0,
        "hedging_removed": 0.0,
        "word_limit_respected": 0.0,
        "terminal_punctuation": 0.0,
        "readme_updated_correct": 0.0,
        "summary_json_valid": 0.0,
        "code_metrics_correct": 0.0,
        "idempotent_rerun": 0.0,
    }

    script_path = workspace / "tools" / "prepare_release.py"
    readme_path = workspace / "README.md"
    inbox_dir = workspace / "input" / "inbox_drafts"
    outbox_dir = workspace / "outbox" / "rewritten"
    summary_json_path = workspace / "output" / "report" / "summary.json"
    src_dir = workspace / "src"

    if script_path.exists() and script_path.is_file():
        scores["script_present"] = 1.0

    drafts = _list_inbox_drafts(inbox_dir)
    original_draft_contents: Dict[str, str] = {}
    for d in drafts:
        txt = _read_text(d)
        if txt is None:
            original_draft_contents[d.name] = ""
        else:
            original_draft_contents[d.name] = txt

    _ = _read_text(readme_path) or ""

    expected_metrics = _compute_code_metrics(src_dir)

    run_ok = False
    stdout_first = ""
    if script_path.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
            )
            run_ok = proc.returncode == 0
            stdout_first = proc.stdout.strip()
        except Exception:
            run_ok = False
            stdout_first = ""
    else:
        run_ok = False

    if run_ok:
        scores["run_succeeded"] = 1.0

    if run_ok:
        expected_count = len(drafts)
        has_count = str(expected_count) in stdout_first
        has_updated = ("updated" in stdout_first.lower()) and ("readme" in stdout_first.lower())
        if has_count and has_updated:
            scores["stdout_summary_ok"] = 1.0

    if run_ok:
        unchanged_ok = True
        for d in drafts:
            after = _read_text(d)
            if after is None:
                unchanged_ok = False
                break
            if after != original_draft_contents.get(d.name, ""):
                unchanged_ok = False
                break
        scores["original_drafts_unchanged"] = 1.0 if unchanged_ok else 0.0

        rewritten_ok_count = 0
        subjects_ok = 0
        paragraph_ok = 0
        hedges_ok = 0
        wordlimit_ok = 0
        punct_ok = 0

        hedges = ["just", "kind of", "sort of", "maybe", "possibly", "I think", "I was thinking", "a bit", "hopefully"]

        if outbox_dir.exists():
            for d in drafts:
                rewritten_path = outbox_dir / d.name
                if rewritten_path.exists():
                    rewritten_ok_count += 1
                    orig_lines = _read_lines(d) or []
                    new_lines = _read_lines(rewritten_path) or []
                    if orig_lines and new_lines:
                        orig_subject = None
                        for ln in orig_lines:
                            if ln.startswith("Subject:"):
                                orig_subject = ln
                                break
                        new_subject = new_lines[0] if len(new_lines) > 0 else None
                        if orig_subject is not None and new_subject == orig_subject:
                            subjects_ok += 1

                        body_lines = new_lines[1:] if len(new_lines) > 1 else []
                        if body_lines and all(ln.strip() != "" for ln in body_lines):
                            paragraph_ok += 1

                        paragraph_text = _join_body_lines_as_paragraph(body_lines)
                        tokens = _tokenize_words(paragraph_text)
                        if not _contains_hedging(tokens, hedges):
                            hedges_ok += 1

                        word_count = len(tokens)
                        if word_count <= 120:
                            wordlimit_ok += 1

                        pt = paragraph_text.strip()
                        end_ok = len(pt) > 0 and pt[-1] in ".!?"
                        if end_ok:
                            punct_ok += 1

        total = len(drafts) if len(drafts) > 0 else 1
        scores["rewritten_files_count"] = float(rewritten_ok_count == len(drafts))
        scores["subjects_preserved"] = subjects_ok / total
        scores["body_single_paragraph"] = paragraph_ok / total
        scores["hedging_removed"] = hedges_ok / total
        scores["word_limit_respected"] = wordlimit_ok / total
        scores["terminal_punctuation"] = punct_ok / total

        readme_after = _read_text(readme_path) or ""
        seg_start, seg_end, seg_content = _extract_readme_segment(readme_after)
        readme_ok = False
        metrics_ok = False
        if seg_start != -1 and seg_end != -1:
            parsed = _parse_bullet_metrics(seg_content)
            if parsed is not None:
                cm = expected_metrics
                if parsed.get("email_rewritten") == len(drafts):
                    if (
                        parsed.get("num_python_files") == cm["num_python_files"]
                        and parsed.get("function_count") == cm["function_count"]
                        and parsed.get("total_nonempty_lines") == cm["total_nonempty_lines"]
                    ):
                        imports_list = parsed.get("unique_top_level_imports", [])
                        imports_list = [s for s in (s.strip() for s in imports_list) if s != ""]
                        if imports_list == cm["unique_top_level_imports"]:
                            readme_ok = True
                            metrics_ok = True
        scores["readme_updated_correct"] = 1.0 if readme_ok else 0.0
        scores["code_metrics_correct"] = 1.0 if metrics_ok else 0.0

        json_ok = False
        if summary_json_path.exists():
            data, err = _safe_load_json(summary_json_path)
            if err is None and isinstance(data, dict):
                has_keys = (
                    "processed_email_files" in data
                    and "code_metrics" in data
                    and "readme_updated" in data
                )
                if has_keys:
                    pef = data.get("processed_email_files")
                    if isinstance(pef, list) and len(pef) == len(drafts):
                        expected_names = {p.name for p in drafts}
                        got_names = set()
                        per_file_ok = True
                        for item in pef:
                            if not isinstance(item, dict):
                                per_file_ok = False
                                break
                            fn = item.get("filename")
                            owc = item.get("original_word_count")
                            rwc = item.get("rewritten_word_count")
                            if not isinstance(fn, str) or not isinstance(owc, int) or not isinstance(rwc, int):
                                per_file_ok = False
                                break
                            got_names.add(fn)
                            rewritten_path = outbox_dir / fn
                            new_lines = _read_lines(rewritten_path) or []
                            body_lines = new_lines[1:] if len(new_lines) > 1 else []
                            tokens = _tokenize_words(_join_body_lines_as_paragraph(body_lines))
                            if len(tokens) != rwc:
                                per_file_ok = False
                                break
                            orig_lines = _read_lines(inbox_dir / fn) or []
                            orig_body = _join_body_lines_as_paragraph(orig_lines[1:] if len(orig_lines) > 1 else [])
                            if len(_tokenize_words(orig_body)) != owc:
                                per_file_ok = False
                                break
                        names_ok = got_names == expected_names
                    else:
                        per_file_ok = False
                        names_ok = False

                    cm_ok = False
                    cm = data.get("code_metrics")
                    if isinstance(cm, dict):
                        cm_ok = (
                            cm.get("num_python_files") == expected_metrics["num_python_files"]
                            and cm.get("total_nonempty_lines") == expected_metrics["total_nonempty_lines"]
                            and cm.get("function_count") == expected_metrics["function_count"]
                            and cm.get("unique_top_level_imports") == expected_metrics["unique_top_level_imports"]
                        )

                    readme_flag_ok = data.get("readme_updated") is True

                    if per_file_ok and names_ok and cm_ok and readme_flag_ok:
                        json_ok = True

        scores["summary_json_valid"] = 1.0 if json_ok else 0.0

        idempotent_ok = False
        rd1 = _read_text(readme_path) or ""
        outbox_files1 = {}
        if outbox_dir.exists():
            for p in sorted(outbox_dir.glob("*.txt")):
                outbox_files1[p.name] = _read_text(p) or ""
        js1 = _read_text(summary_json_path) or ""
        try:
            proc2 = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
            )
            run2_ok = proc2.returncode == 0
            stdout_second = proc2.stdout.strip()
        except Exception:
            run2_ok = False
            stdout_second = ""
        if run2_ok:
            rd2 = _read_text(readme_path) or ""
            outbox_files2 = {}
            if outbox_dir.exists():
                for p in sorted(outbox_dir.glob("*.txt")):
                    outbox_files2[p.name] = _read_text(p) or ""
            js2 = _read_text(summary_json_path) or ""
            if rd1 == rd2 and outbox_files1 == outbox_files2 and js1 == js2 and stdout_first == stdout_second:
                idempotent_ok = True
        scores["idempotent_rerun"] = 1.0 if idempotent_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()