import csv
import json
import os
import sys
from collections import defaultdict, Counter
from datetime import datetime, timezone

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

# Category definitions
CATEGORY_TO_AA = {
    "Hydrophobic": set(list("VLIM")),
    "Nucleophilic": set(list("STC")),
    "Aromatic": set(list("FYW")),
    "Amide": set(list("NQ")),
    "Acidic": set(list("DE")),
    "Cationic": set(list("HKR")),
}
AA_TO_CATEGORY = {}
for cat, aas in CATEGORY_TO_AA.items():
    for aa in aas:
        AA_TO_CATEGORY[aa] = cat

EXCLUDE = set(list("XAGP-"))

# Utility helpers
def approx_equal(a, b, tol=1e-2):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def parse_float(s):
    try:
        return float(str(s).strip())
    except Exception:
        return None

def parse_int(s):
    try:
        return int(str(s).strip())
    except Exception:
        return None

def parse_iso(s):
    if not isinstance(s, str) or not s:
        return None
    s2 = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s2)
    except Exception:
        return None

def all_categories_alpha():
    return sorted(list(CATEGORY_TO_AA.keys()))

def all_pair_names_alpha_alpha():
    cats = all_categories_alpha()
    names = []
    for i, a in enumerate(cats):
        for b in cats[i:]:
            names.append(f"{a}-{b}")
    return names

ALL_UNDIRECTED_PAIRS = all_pair_names_alpha_alpha()

def undirected_pair_name(cat1, cat2):
    return "-".join(sorted([cat1, cat2]))

def filter_sequence(seq):
    return "".join([c for c in seq.upper() if c not in EXCLUDE])

def compute_counts_for_sequence(seq):
    # seq provided is already consensus; filter according to rules
    filtered = filter_sequence(seq)
    # Count directed pairs then merge symmetrically
    directed_counts = defaultdict(int)
    total_directed = 0
    for i in range(len(filtered) - 1):
        aa1 = filtered[i]
        aa2 = filtered[i + 1]
        if aa1 in AA_TO_CATEGORY and aa2 in AA_TO_CATEGORY:
            c1 = AA_TO_CATEGORY[aa1]
            c2 = AA_TO_CATEGORY[aa2]
            directed_counts[(c1, c2)] += 1
            total_directed += 1
        else:
            # Ignore unknown residues
            continue
    undirected_counts = defaultdict(int)
    for (c1, c2), cnt in directed_counts.items():
        name = undirected_pair_name(c1, c2)
        undirected_counts[name] += cnt
    # Ensure all 21 keys present
    for name in ALL_UNDIRECTED_PAIRS:
        undirected_counts.setdefault(name, 0)
    return undirected_counts, total_directed

def compute_top5_and_metrics(undirected_counts, total_pairs):
    # Sort by count desc, then by pair name alphabetically
    items = list(undirected_counts.items())
    items.sort(key=lambda x: (-x[1], x[0]))
    top5 = items[:5]
    top5_pairs = [name for name, cnt in top5]
    top5_counts = {name: cnt for name, cnt in top5}
    sum_top5 = sum(top5_counts.values())
    top5_percentage = (sum_top5 / total_pairs * 100.0) if total_pairs > 0 else 0.0
    # Compute Ni for each category (each pair contributes its count to both categories it touches)
    Ni = {cat: 0 for cat in CATEGORY_TO_AA.keys()}
    for name, cnt in top5:
        left, right = name.split("-")
        Ni[left] += cnt
        Ni[right] += cnt
    phi = {}
    denom = 2 * sum_top5
    for cat in CATEGORY_TO_AA.keys():
        phi[cat] = (Ni[cat] / denom * 100.0) if denom > 0 else 0.0
    return top5_pairs, top5_counts, sum_top5, top5_percentage, Ni, phi

def parse_consensus_input(input_path):
    if not os.path.isfile(input_path):
        return None, {}
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None, {}

    # Threshold
    threshold = data.get("threshold")
    if not isinstance(threshold, (int, float)):
        # Try nested
        for key in ["meta", "config", "params"]:
            if isinstance(data.get(key), dict) and isinstance(data[key].get("threshold"), (int, float)):
                threshold = data[key]["threshold"]
                break
    if not isinstance(threshold, (int, float)):
        threshold = 0.5

    # Species mapping
    species_map = {}

    # Common structures
    if isinstance(data.get("species"), list):
        for item in data["species"]:
            if not isinstance(item, dict):
                continue
            name = item.get("species") or item.get("name") or item.get("id") or item.get("label")
            seq = item.get("consensus") or item.get("consensus_sequence") or item.get("sequence") or item.get("seq")
            if name and isinstance(seq, str):
                species_map[name] = seq
    elif isinstance(data.get("species"), dict):
        for name, val in data["species"].items():
            seq = None
            if isinstance(val, str):
                seq = val
            elif isinstance(val, dict):
                seq = val.get("consensus") or val.get("consensus_sequence") or val.get("sequence") or val.get("seq")
            if name and isinstance(seq, str):
                species_map[name] = seq

    # Alternative keys
    if not species_map:
        for key in ["consensus_sequences", "sequences", "data", "items"]:
            val = data.get(key)
            if isinstance(val, dict):
                for name, seq in val.items():
                    if isinstance(seq, str):
                        species_map[name] = seq
                    elif isinstance(seq, dict):
                        s = seq.get("consensus") or seq.get("consensus_sequence") or seq.get("sequence") or seq.get("seq")
                        if isinstance(s, str):
                            species_map[name] = s
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        name = item.get("species") or item.get("name") or item.get("id") or item.get("label")
                        seq = item.get("consensus") or item.get("consensus_sequence") or item.get("sequence") or item.get("seq")
                        if name and isinstance(seq, str):
                            species_map[name] = seq

    # Fallback: top-level dict mapping species->seq (excluding known meta keys)
    if not species_map and isinstance(data, dict):
        for k, v in data.items():
            if k in ("threshold", "meta", "config", "params", "species", "consensus_sequences", "sequences", "data", "items"):
                continue
            if isinstance(v, str):
                species_map[k] = v

    return threshold, species_map

def load_csv_dicts(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames or []
            return header, rows
    except Exception:
        return None, None

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False until proven)
    checks = {
        "has_species_formulations_csv": False,
        "species_formulations_schema_ok": False,
        "species_set_match": False,
        "counts_match_all": False,
        "top5_string_correct_all": False,
        "top5_percentage_correct_all": False,
        "ni_phi_correct_all": False,
        "has_top5_details_csv": False,
        "top5_details_schema_ok": False,
        "top5_details_content_ok": False,
        "has_summary_csv": False,
        "summary_content_ok": False,
        "has_state_json": False,
        "state_json_content_ok": False,
        "has_tasks_json": False,
        "tasks_json_content_ok": False,
        "has_checkpoint_pre_analysis": False,
        "checkpoint_meta_ok": False,
    }

    # Load input reference
    input_path = os.path.join(input_dir, "consensus_sequences.json")
    threshold, species_map = parse_consensus_input(input_path)

    # Compute expected results
    expected = {}
    for sp, seq in species_map.items():
        und_counts, total_pairs = compute_counts_for_sequence(seq)
        top5_pairs, top5_counts, sum_top5, top5_pct, Ni, phi = compute_top5_and_metrics(und_counts, total_pairs)
        expected[sp] = {
            "counts": und_counts,
            "total_pairs": total_pairs,
            "top5_pairs": top5_pairs,
            "top5_counts": top5_counts,
            "sum_top5": sum_top5,
            "top5_percentage": top5_pct,
            "Ni": Ni,
            "phi": phi,
        }

    # 1) species_formulations.csv
    sf_path = os.path.join(output_dir, "species_formulations.csv")
    if os.path.isfile(sf_path):
        checks["has_species_formulations_csv"] = True
        header, rows = load_csv_dicts(sf_path)
        if header is not None and rows is not None:
            # Schema check: exactly 37 columns
            expected_first4 = ["species", "total_pairs", "top_5_pairs", "top_5_percentage"]
            cat_order_niphi = ["Hydrophobic", "Nucleophilic", "Aromatic", "Amide", "Acidic", "Cationic"]
            expected_niphi = []
            for c in cat_order_niphi:
                expected_niphi.append(f"{c}_Ni")
                expected_niphi.append(f"{c}_phi")
            # count columns: 21 count_{PairName}
            expected_pair_cols = [f"count_{name}" for name in ALL_UNDIRECTED_PAIRS]
            schema_ok = True
            if len(header) != 37:
                schema_ok = False
            else:
                if header[:4] != expected_first4:
                    schema_ok = False
                if header[4:4+12] != expected_niphi:
                    schema_ok = False
                # Remaining 21 should be count_ columns, order may vary but must match set
                tail = header[16:]
                if len(tail) != 21:
                    schema_ok = False
                else:
                    tail_set = set(tail)
                    if set(expected_pair_cols) != tail_set:
                        schema_ok = False
            if schema_ok:
                checks["species_formulations_schema_ok"] = True

            # Species set match
            file_species = [r.get("species") for r in (rows or []) if r.get("species") is not None]
            if set(file_species) == set(species_map.keys()) and len(file_species) == len(rows):
                checks["species_set_match"] = True

            # Content checks only if schema ok and have expected
            if checks["species_formulations_schema_ok"] and expected:
                counts_match_all = True
                top5_str_ok_all = True
                top5_pct_ok_all = True
                ni_phi_ok_all = True

                # Build helper: map species -> row dict
                row_by_species = {}
                for r in rows:
                    sp = r.get("species")
                    if sp is not None:
                        row_by_species[sp] = r

                for sp, exp in expected.items():
                    r = row_by_species.get(sp)
                    if not r:
                        counts_match_all = False
                        top5_str_ok_all = False
                        top5_pct_ok_all = False
                        ni_phi_ok_all = False
                        continue

                    # Check counts for all 21 pairs and total_pairs consistency
                    total_pairs_file = parse_int(r.get("total_pairs"))
                    if total_pairs_file is None:
                        counts_match_all = False
                    pair_sum = 0
                    for pair_name in ALL_UNDIRECTED_PAIRS:
                        col = f"count_{pair_name}"
                        val = parse_int(r.get(col))
                        if val is None:
                            counts_match_all = False
                            continue
                        if val != exp["counts"].get(pair_name, 0):
                            counts_match_all = False
                        pair_sum += val
                    # Verify sums
                    if total_pairs_file != pair_sum or total_pairs_file != exp["total_pairs"]:
                        counts_match_all = False

                    # Check top_5_pairs string
                    top5_str_file = (r.get("top_5_pairs") or "").strip()
                    top5_str_exp = ";".join(exp["top5_pairs"])
                    if top5_str_file != top5_str_exp:
                        top5_str_ok_all = False

                    # Check top_5_percentage
                    top5_pct_file = parse_float(r.get("top_5_percentage"))
                    if top5_pct_file is None or not approx_equal(top5_pct_file, exp["top5_percentage"], tol=1e-2):
                        top5_pct_ok_all = False

                    # Check Ni exact and phi approx
                    for c in CATEGORY_TO_AA.keys():
                        ni_col = f"{c}_Ni"
                        phi_col = f"{c}_phi"
                        ni_file = parse_int(r.get(ni_col))
                        phi_file = parse_float(r.get(phi_col))
                        if ni_file is None or ni_file != exp["Ni"][c]:
                            ni_phi_ok_all = False
                        if phi_file is None or not approx_equal(phi_file, exp["phi"][c], tol=1e-2):
                            ni_phi_ok_all = False

                if counts_match_all:
                    checks["counts_match_all"] = True
                if top5_str_ok_all:
                    checks["top5_string_correct_all"] = True
                if top5_pct_ok_all:
                    checks["top5_percentage_correct_all"] = True
                if ni_phi_ok_all:
                    checks["ni_phi_correct_all"] = True

    # 2) top_5_pairs_details.csv
    t5_path = os.path.join(output_dir, "top_5_pairs_details.csv")
    if os.path.isfile(t5_path):
        checks["has_top5_details_csv"] = True
        header, rows = load_csv_dicts(t5_path)
        schema_ok = False
        if header is not None and rows is not None:
            expected_cols = ["species", "rank", "pair", "count", "frequency_percent"]
            if header == expected_cols:
                schema_ok = True
        if schema_ok:
            checks["top_5_details_schema_ok"] = True

            content_ok = True
            # Group rows by species
            rows_by_sp = defaultdict(list)
            for r in rows:
                rows_by_sp[r.get("species")].append(r)
            # Validate per species
            for sp, exp in expected.items():
                sp_rows = rows_by_sp.get(sp, [])
                # Exactly 5 rows
                if len(sp_rows) != 5:
                    content_ok = False
                    continue
                # Sort by rank
                try:
                    sp_rows.sort(key=lambda r: int(r.get("rank", 0)))
                except Exception:
                    content_ok = False
                    continue
                # Ranks must be 1..5
                ranks = [parse_int(r.get("rank")) for r in sp_rows]
                if ranks != [1, 2, 3, 4, 5]:
                    content_ok = False
                # Compare pairs and counts and frequency percents
                for idx, r in enumerate(sp_rows):
                    pair_name_file = (r.get("pair") or "").strip()
                    count_file = parse_int(r.get("count"))
                    freq_file = parse_float(r.get("frequency_percent"))
                    if idx >= len(exp["top5_pairs"]):
                        content_ok = False
                        continue
                    pair_name_exp = exp["top5_pairs"][idx]
                    count_exp = exp["counts"][pair_name_exp]
                    total_pairs = exp["total_pairs"]
                    freq_exp = (count_exp / total_pairs * 100.0) if total_pairs > 0 else 0.0
                    if pair_name_file != pair_name_exp:
                        content_ok = False
                    if count_file is None or count_file != count_exp:
                        content_ok = False
                    if freq_file is None or not approx_equal(freq_file, freq_exp, tol=1e-2):
                        content_ok = False
            if content_ok:
                checks["top_5_details_content_ok"] = True

    # 3) formulation_summary.csv
    fs_path = os.path.join(output_dir, "formulation_summary.csv")
    if os.path.isfile(fs_path):
        checks["has_summary_csv"] = True
        header, rows = load_csv_dicts(fs_path)
        if header is not None and rows is not None and len(rows) == 1:
            row = rows[0]
            try:
                total_species_file = parse_int(row.get("total_species"))
                unique_formulations_file = parse_int(row.get("unique_formulations"))
                duplicate_formulations_file = parse_int(row.get("duplicate_formulations"))
            except Exception:
                total_species_file = unique_formulations_file = duplicate_formulations_file = None

            # Compute expected from expected dict
            total_species_exp = len(expected)
            # Build formulation strings (Top5 semicolon)
            form_strings = {}
            for sp, exp in expected.items():
                form_strings[sp] = ";".join(exp["top5_pairs"])
            counts = Counter(form_strings.values())
            unique_formulations_exp = len(counts)
            duplicate_formulations_exp = sum(cnt for cnt in counts.values() if cnt >= 2)

            if (total_species_file == total_species_exp and
                unique_formulations_file == unique_formulations_exp and
                duplicate_formulations_file == duplicate_formulations_exp):
                checks["summary_content_ok"] = True

    # 4) state.json
    state_path = os.path.join(output_dir, "state.json")
    if os.path.isfile(state_path):
        checks["has_state_json"] = True
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = None
        if isinstance(state, dict):
            status_ok = isinstance(state.get("status"), str) and len(state.get("status")) > 0
            current_task_ok = isinstance(state.get("current_task"), str)
            last_saved_ok = parse_iso(state.get("last_saved")) is not None
            notes = state.get("notes")
            notes_ok = isinstance(notes, list) and len(notes) > 0
            custom = state.get("custom")
            custom_ok = isinstance(custom, dict) and ("analysis_threshold" in custom) and (threshold is None or custom.get("analysis_threshold") == threshold)
            if status_ok and current_task_ok and last_saved_ok and notes_ok and custom_ok:
                checks["state_json_content_ok"] = True

    # 5) tasks.json
    tasks_path = os.path.join(output_dir, "tasks.json")
    if os.path.isfile(tasks_path):
        checks["has_tasks_json"] = True
        try:
            with open(tasks_path, "r", encoding="utf-8") as f:
                tasks_data = json.load(f)
        except Exception:
            tasks_data = None
        if isinstance(tasks_data, dict):
            tasks = tasks_data.get("tasks")
            next_id = tasks_data.get("next_id")
            priorities = {"critical", "high", "normal", "low"}
            statuses = {"pending", "done"}
            ok = True
            if not isinstance(tasks, list) or len(tasks) < 3:
                ok = False
            else:
                seen_ids = []
                has_pending = False
                has_done = False
                for t in tasks:
                    if not isinstance(t, dict):
                        ok = False
                        break
                    tid = t.get("id")
                    tdesc = t.get("task")
                    pri = t.get("priority")
                    st = t.get("status")
                    created = t.get("created")
                    if not isinstance(tid, int):
                        ok = False
                    else:
                        seen_ids.append(tid)
                    if not isinstance(tdesc, str) or len(tdesc) == 0:
                        ok = False
                    if pri not in priorities:
                        ok = False
                    if st not in statuses:
                        ok = False
                    if parse_iso(created) is None:
                        ok = False
                    if st == "done":
                        has_done = True
                        if parse_iso(t.get("completed")) is None:
                            ok = False
                    if st == "pending":
                        has_pending = True
                if not has_done or not has_pending:
                    ok = False
                if not isinstance(next_id, int) or (seen_ids and next_id <= max(seen_ids)):
                    ok = False
            if ok:
                checks["tasks_json_content_ok"] = True

    # 6) checkpoint pre-analysis
    cp_dir = os.path.join(output_dir, "checkpoints", "pre-analysis")
    if os.path.isdir(cp_dir):
        checks["has_checkpoint_pre_analysis"] = True
        meta_path = os.path.join(cp_dir, "meta.json")
        state_snap = os.path.join(cp_dir, "state.json")
        tasks_snap = os.path.join(cp_dir, "tasks.json")
        meta_ok = False
        if os.path.isfile(meta_path) and os.path.isfile(state_snap) and os.path.isfile(tasks_snap):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                meta = None
            if isinstance(meta, dict) and isinstance(meta.get("name"), str) and parse_iso(meta.get("created")) is not None:
                meta_ok = True
        if meta_ok:
            checks["checkpoint_meta_ok"] = True

    # Compute reward
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if output missing important artifacts, many checks remain False -> reward near 0
    # Ensure numeric in [0,1]
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()