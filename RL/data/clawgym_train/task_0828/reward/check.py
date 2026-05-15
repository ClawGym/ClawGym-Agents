import json
import os
import sys
from typing import Any, Dict, List, Tuple

def load_json(path: str) -> Tuple[bool, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def is_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)

def is_number(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool)

def coerce_per_page_counts(obj: Any) -> Tuple[bool, Dict[int, int]]:
    # Accept dict with int-or-str keys or list of counts
    result: Dict[int, int] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            try:
                key_int = int(k)
            except Exception:
                return False, {}
            if not is_int(v):
                return False, {}
            if v < 0:
                return False, {}
            result[key_int] = int(v)
        return True, result
    if isinstance(obj, list):
        for idx, v in enumerate(obj):
            if not is_int(v):
                return False, {}
            if v < 0:
                return False, {}
            result[idx] = int(v)
        return True, result
    return False, {}

def word_count(text: str) -> int:
    return len([w for w in text.strip().split() if w])

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        "has_preflight": False,
        "preflight_valid": False,
        "has_highlight_plan": False,
        "metadata_valid": False,
        "highlight_counts_consistent": False,
        "highlights_valid": False,
        "limits_respected": False,
        "core_categories_present": False,
        "has_notes": False,
        "notes_valid": False,
    }

    # Paths
    preflight_path = os.path.join(output_dir, "preflight.json")
    plan_path = os.path.join(output_dir, "highlight_plan.json")
    notes_path = os.path.join(output_dir, "notes.json")

    # Allowed values
    core_categories = {"goal", "motivation", "method", "contribution", "result"}
    optional_categories = {"definitions", "limitations"}
    allowed_levels = {"low", "medium", "high", "extreme"}
    allowed_opacity = {"light", "dark"}
    allowed_note_modes_non_none = {"flow", "full"}

    # 1) Preflight
    ok, preflight = load_json(preflight_path)
    if ok and isinstance(preflight, dict):
        checks["has_preflight"] = True
        pc = preflight.get("page_count")
        cc = preflight.get("char_count")
        wc = preflight.get("word_count")
        te = preflight.get("token_estimate")
        if all(is_int(v) for v in [pc, cc, wc, te]):
            if pc is not None and pc >= 1 and cc is not None and wc is not None and te is not None:
                if cc >= wc >= 100 and te > 0:
                    checks["preflight_valid"] = True

    # 2) Highlight plan
    ok, plan = load_json(plan_path)
    highlights: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {}
    if ok and isinstance(plan, dict):
        checks["has_highlight_plan"] = True
        # Require 'metadata' and 'highlights'
        metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
        highlights = plan.get("highlights") if isinstance(plan.get("highlights"), list) else []
        # Validate metadata basics
        meta_ok = True
        hl = metadata.get("highlight_level")
        op = metadata.get("opacity")
        inc_opt = metadata.get("include_optional")
        dis_opt = metadata.get("disabled_optional")
        max_per_page = metadata.get("max_per_page")
        max_total = metadata.get("max_total")
        min_score = metadata.get("min_score")
        if hl not in allowed_levels:
            meta_ok = False
        if op not in allowed_opacity:
            meta_ok = False
        if not isinstance(inc_opt, bool):
            meta_ok = False
        if not isinstance(dis_opt, list):
            meta_ok = False
        else:
            for item in dis_opt:
                if item not in optional_categories:
                    meta_ok = False
                    break
        if not (is_int(max_per_page) and max_per_page >= 1):
            meta_ok = False
        if not (is_int(max_total) and max_total >= 1):
            meta_ok = False
        if not (is_number(min_score) and float(min_score) > 0):
            meta_ok = False
        if meta_ok:
            checks["metadata_valid"] = True

        # Summary counts: accept at top-level or inside metadata
        # Fetch total_highlights
        summary_total = None
        if is_int(plan.get("total_highlights", None)):
            summary_total = int(plan["total_highlights"])
        elif is_int(metadata.get("total_highlights", None)):
            summary_total = int(metadata["total_highlights"])

        # Fetch per_page_counts
        ppc_raw = None
        if plan.get("per_page_counts") is not None:
            ppc_raw = plan.get("per_page_counts")
        elif metadata.get("per_page_counts") is not None:
            ppc_raw = metadata.get("per_page_counts")

        ppc_ok, ppc_map = coerce_per_page_counts(ppc_raw) if ppc_raw is not None else (False, {})

        # Validate counts consistency
        if isinstance(highlights, list) and summary_total is not None and ppc_ok:
            len_highlights = len(highlights)
            # Compute counts by page from highlights
            counts_by_page: Dict[int, int] = {}
            for h in highlights:
                pi = h.get("page_index")
                if isinstance(pi, int) and pi >= 0:
                    counts_by_page[pi] = counts_by_page.get(pi, 0) + 1
            # Check equality of total_highlights
            if summary_total == len_highlights:
                # Check both directions for per_page_counts
                per_page_match = True
                # Check keys present for pages in highlights
                for pi, cnt in counts_by_page.items():
                    if ppc_map.get(pi) != cnt:
                        per_page_match = False
                        break
                # Check provided map matches computed for all provided keys
                if per_page_match:
                    for pi, cnt in ppc_map.items():
                        if counts_by_page.get(pi, 0) != cnt:
                            per_page_match = False
                            break
                if per_page_match:
                    checks["highlight_counts_consistent"] = True

        # Validate highlights entries and limits and core coverage
        if checks["metadata_valid"] and checks["highlight_counts_consistent"]:
            # Allowed categories set
            include_optional = bool(metadata.get("include_optional"))
            disabled_optional = set(metadata.get("disabled_optional", [])) if isinstance(metadata.get("disabled_optional"), list) else set()
            allowed = set(core_categories)
            if include_optional:
                for cat in optional_categories:
                    if cat not in disabled_optional:
                        allowed.add(cat)
            # Validate each highlight
            entries_ok = True
            for h in highlights:
                # page_index
                pi = h.get("page_index")
                if not (is_int(pi) and pi >= 0):
                    entries_ok = False
                    break
                # category
                cat = h.get("category")
                if not isinstance(cat, str) or cat not in allowed:
                    entries_ok = False
                    break
                # score
                sc = h.get("score")
                if not is_number(sc) or float(sc) < float(metadata.get("min_score")):
                    entries_ok = False
                    break
                # reasons
                rs = h.get("reasons")
                if not isinstance(rs, list) or len(rs) == 0:
                    entries_ok = False
                    break
            if entries_ok:
                checks["highlights_valid"] = True

            # Limits
            limits_ok = True
            if summary_total is None or not is_int(summary_total):
                limits_ok = False
            else:
                if summary_total > int(metadata.get("max_total")):
                    limits_ok = False
                # Per-page
                max_pp = int(metadata.get("max_per_page"))
                for pi, cnt in ppc_map.items():
                    if cnt > max_pp:
                        limits_ok = False
                        break
            if limits_ok:
                checks["limits_respected"] = True

            # Core categories coverage
            present_cats = set()
            for h in highlights:
                cat = h.get("category")
                if isinstance(cat, str):
                    present_cats.add(cat)
            core_ok = all(cat in present_cats for cat in core_categories)
            if core_ok:
                checks["core_categories_present"] = True

    # 3) Notes
    ok, notes = load_json(notes_path)
    if ok and isinstance(notes, dict):
        checks["has_notes"] = True
        meta = notes.get("metadata")
        if isinstance(meta, dict):
            note_mode = meta.get("note_mode")
            # Require note_mode to exist
            if isinstance(note_mode, str):
                if note_mode == "none":
                    # Must not contain tldr or section_flows
                    if ("tldr" not in notes) and ("section_flows" not in notes):
                        # section_items may be present; if present it should be <= 0 or int
                        si = meta.get("section_items")
                        si_ok = True
                        if si is not None:
                            si_ok = is_int(si) and si >= 0
                        if si_ok:
                            checks["notes_valid"] = True
                else:
                    # Must be resolved to flow/full
                    if note_mode in allowed_note_modes_non_none:
                        section_items = meta.get("section_items")
                        if is_int(section_items) and section_items > 0:
                            tldr = notes.get("tldr")
                            sflows = notes.get("section_flows")
                            if isinstance(tldr, str):
                                wc = word_count(tldr)
                                if 30 <= wc <= 120 and isinstance(sflows, list) and len(sflows) == section_items:
                                    flows_ok = True
                                    for item in sflows:
                                        if not isinstance(item, dict):
                                            flows_ok = False
                                            break
                                        sec = item.get("section")
                                        summ = item.get("summary")
                                        if not (isinstance(sec, str) and isinstance(summ, str)):
                                            flows_ok = False
                                            break
                                    if flows_ok:
                                        checks["notes_valid"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0
    # Enforce no-op baseline: if no outputs present, reward must be 0.0
    outputs_exist = any(os.path.exists(p) for p in [preflight_path, plan_path, notes_path])
    if not outputs_exist:
        reward = 0.0

    # Print single JSON object
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()