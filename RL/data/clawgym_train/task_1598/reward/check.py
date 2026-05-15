import json
import os
import re
import sys
import csv

def load_yaml(path):
    try:
        import yaml  # Prefer standard library, but use PyYAML if available
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f), True
    except Exception:
        return None, False

def is_hex6(s):
    return isinstance(s, str) and re.fullmatch(r"#([0-9A-Fa-f]{6})", s) is not None

def words_count(s):
    if not isinstance(s, str):
        return 0
    return len([w for w in re.split(r"\s+", s.strip()) if w])

def norm_str(s):
    if not isinstance(s, str):
        return ""
    return s.strip().lower()

def norm_key(s):
    if not isinstance(s, str):
        return ""
    # normalize keys by lowercasing, mapping special dashes/apostrophes, and collapsing spaces/slashes/hyphens to underscores
    s2 = s.lower()
    s2 = s2.replace("’", "'").replace("‑", "-").replace("–", "-").replace("—", "-")
    s2 = re.sub(r"[\/\s\-]+", "_", s2)
    return s2

def get_nested(d, path_list):
    cur = d
    for p in path_list:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur

def ensure_list(x):
    return x if isinstance(x, list) else []

def ensure_dict(x):
    return x if isinstance(x, dict) else {}

def numeric(value):
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.replace(",", ""))
            return True
        except Exception:
            return False
    return False

def to_float(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except Exception:
            return None
    return None

def list_contains_all_strings(lst, required_strings, case_insensitive=True):
    if not isinstance(lst, list):
        return False
    if case_insensitive:
        setlst = set([norm_str(x) for x in lst if isinstance(x, str)])
        return all(norm_str(req) in setlst for req in required_strings)
    else:
        setlst = set([x for x in lst if isinstance(x, str)])
        return all(req in setlst for req in required_strings)

def score_from_checks(checks_dict):
    # reward is average of boolean checks; if no checks true, reward 0.0
    bools = list(checks_dict.values())
    if not bools:
        return 0.0
    total = len(bools)
    passed = sum(1 for b in bools if b)
    return (passed / total) if total > 0 else 0.0

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Paths
opsforge_dir = os.path.join(output_dir, "opsforge")
p1_path = os.path.join(opsforge_dir, "phase1_foundations.yaml")
p2_path = os.path.join(opsforge_dir, "phase2_positioning.yaml")
p3_path = os.path.join(opsforge_dir, "phase3_voice.yaml")
p4_path = os.path.join(opsforge_dir, "phase4_visual.yaml")
p5_path = os.path.join(opsforge_dir, "phase5_gtm.yaml")
p6_path = os.path.join(opsforge_dir, "phase6_measurement.yaml")
csv_path = os.path.join(opsforge_dir, "voice_scorecard.csv")

checks = {
    # Existence and parse checks
    "exists_phase1": False, "parse_phase1": False,
    "exists_phase2": False, "parse_phase2": False,
    "exists_phase3": False, "parse_phase3": False,
    "exists_phase4": False, "parse_phase4": False,
    "exists_phase5": False, "parse_phase5": False,
    "exists_phase6": False, "parse_phase6": False,
    "exists_csv": False, "parse_csv": False,

    # Phase 1 checks
    "p1_values_three": False,
    "p1_values_structure": False,
    "p1_personality_archetypes": False,
    "p1_competitive_map_fields": False,
    "p1_competitors_min3": False,
    "p1_competitors_fields": False,

    # Phase 2 checks
    "p2_positioning_fields": False,
    "p2_combined_format": False,
    "p2_value_props_three": False,
    "p2_tagline_len": False,
    "p2_icp_anti_signals_3": False,

    # Phase 3 checks
    "p3_voice_three_words": False,
    "p3_rules_min6": False,
    "p3_vocab_lists": False,
    "p3_tone_keys": False,
    "p3_channel_adaptations_keys": False,
    "p3_scorecard_dims_sum100": False,

    # Phase 4 checks
    "p4_colors_valid": False,
    "p4_typography_fields": False,
    "p4_logo_brief_fields": False,
    "p4_variations_contains_required": False,
    "p4_imagery_aspect_ratios": False,

    # Phase 5 checks
    "p5_acv_numeric": False,
    "p5_motion_vs_acv": False,
    "p5_prelaunch_weeks": False,
    "p5_launch_checklist_len": False,
    "p5_channels_min3_and_fields": False,
    "p5_battlecards_min2_and_fields": False,
    "p5_battlecards_names_match_phase1": False,

    # Phase 6 checks
    "p6_health_metrics_present": False,
    "p6_audit_sections": False,
    "p6_rebrand_framework": False,

    # CSV checks
    "csv_headers_exact": False,
    "csv_rows_six_and_weights": False,
}

# Load phase files
p1 = None
if os.path.isfile(p1_path):
    checks["exists_phase1"] = True
    p1, checks["parse_phase1"] = load_yaml(p1_path)

p2 = None
if os.path.isfile(p2_path):
    checks["exists_phase2"] = True
    p2, checks["parse_phase2"] = load_yaml(p2_path)

p3 = None
if os.path.isfile(p3_path):
    checks["exists_phase3"] = True
    p3, checks["parse_phase3"] = load_yaml(p3_path)

p4 = None
if os.path.isfile(p4_path):
    checks["exists_phase4"] = True
    p4, checks["parse_phase4"] = load_yaml(p4_path)

p5 = None
if os.path.isfile(p5_path):
    checks["exists_phase5"] = True
    p5, checks["parse_phase5"] = load_yaml(p5_path)

p6 = None
if os.path.isfile(p6_path):
    checks["exists_phase6"] = True
    p6, checks["parse_phase6"] = load_yaml(p6_path)

# CSV load
csv_rows = []
if os.path.isfile(csv_path):
    checks["exists_csv"] = True
    try:
        with open(csv_path, "r", encoding="utf-8") as cf:
            reader = csv.reader(cf)
            rows = list(reader)
        if rows:
            checks["parse_csv"] = True
            csv_rows = rows
    except Exception:
        checks["parse_csv"] = False

# Phase 1 validations
allowed_archetypes = {
    "sage","creator","hero","explorer","rebel","caregiver","ruler","everyman","magician","jester","lover","innocent"
}
phase1_competitor_names = set()
if checks["parse_phase1"] and isinstance(p1, dict):
    # brand_values exactly 3 and structure keys
    brand_values = p1.get("brand_values")
    if isinstance(brand_values, list) and len(brand_values) == 3:
        checks["p1_values_three"] = True
        structure_ok = True
        for item in brand_values:
            if not isinstance(item, dict):
                structure_ok = False
                break
            if not all(k in item for k in ["value","behavior","anti_pattern"]):
                structure_ok = False
                break
        checks["p1_values_structure"] = structure_ok

    # brand_personality archetypes
    bp = p1.get("brand_personality")
    if isinstance(bp, dict):
        prim = bp.get("primary")
        sec = bp.get("secondary")
        if isinstance(prim, str) and isinstance(sec, str):
            if norm_str(prim) in allowed_archetypes and norm_str(sec) in allowed_archetypes:
                checks["p1_personality_archetypes"] = True

    # competitive_map fields and competitors
    cm = p1.get("competitive_map")
    required_cm_fields = ["category","white_space","category_conventions","our_contrarian_angle","competitors"]
    if isinstance(cm, dict) and all(k in cm for k in required_cm_fields):
        checks["p1_competitive_map_fields"] = True
        comps = cm.get("competitors")
        if isinstance(comps, list) and len(comps) >= 3:
            checks["p1_competitors_min3"] = True
            comp_fields_ok = True
            for c in comps:
                if not isinstance(c, dict):
                    comp_fields_ok = False
                    break
                if not all(k in c for k in ["name","positioning","strengths","weaknesses","price_tier","brand_vibe"]):
                    comp_fields_ok = False
                    break
                if not isinstance(c.get("strengths"), list) or not isinstance(c.get("weaknesses"), list):
                    comp_fields_ok = False
                    break
                name = c.get("name")
                if isinstance(name, str):
                    phase1_competitor_names.add(name.strip())
            checks["p1_competitors_fields"] = comp_fields_ok

# Phase 2 validations
if checks["parse_phase2"] and isinstance(p2, dict):
    pos = p2.get("positioning")
    req_pos_keys = ["competitive_alternatives","unique_capabilities","enabled_value","best_fit_customers","market_category"]
    if isinstance(pos, dict) and all(k in pos for k in req_pos_keys):
        checks["p2_positioning_fields"] = True

    combined = p2.get("combined_statement")
    if isinstance(combined, str) and combined.strip().startswith("For") and ("Unlike" in combined):
        checks["p2_combined_format"] = True

    vps = p2.get("value_propositions")
    if isinstance(vps, list) and len(vps) == 3:
        checks["p2_value_props_three"] = True

    tagline = p2.get("tagline")
    if isinstance(tagline, str) and words_count(tagline) <= 6 and words_count(tagline) > 0:
        checks["p2_tagline_len"] = True

    icp = p2.get("icp")
    if isinstance(icp, dict):
        anti = icp.get("anti_signals")
        if isinstance(anti, list) and len(anti) >= 3:
            checks["p2_icp_anti_signals_3"] = True

# Phase 3 validations
if checks["parse_phase3"] and isinstance(p3, dict):
    bv = p3.get("brand_voice")
    if isinstance(bv, dict):
        vi3w = bv.get("voice_in_3_words")
        if isinstance(vi3w, list) and len(vi3w) == 3:
            checks["p3_voice_three_words"] = True
        wr = bv.get("writing_rules")
        if isinstance(wr, list) and len(wr) >= 6:
            checks["p3_rules_min6"] = True
        vocab = bv.get("vocabulary")
        if isinstance(vocab, dict):
            use = vocab.get("use")
            avoid = vocab.get("avoid")
            if isinstance(use, list) and isinstance(avoid, list):
                checks["p3_vocab_lists"] = True
        ts = bv.get("tone_spectrum")
        tone_keys = {"celebration","education","error_state","sales","support"}
        if isinstance(ts, dict) and tone_keys.issubset(set(ts.keys())):
            checks["p3_tone_keys"] = True

    ca = p3.get("channel_adaptations")
    required_channels = {"website","email_marketing","email_support","linkedin","twitter","blog","sales_deck","product_ui"}
    if isinstance(ca, dict) and required_channels.issubset(set(ca.keys())):
        checks["p3_channel_adaptations_keys"] = True

    # brand_voice_scorecard
    sc = p3.get("brand_voice_scorecard")
    required_dims = {"clarity","personality","specificity","action","consistency","audience_fit"}
    dims_present = set()
    weight_sum = 0
    valid = False
    if isinstance(sc, dict):
        # mapping form
        dims_present = set(norm_key(k) for k in sc.keys())
        if required_dims.issubset(dims_present):
            vals = []
            all_numeric = True
            for k in sc:
                v = sc[k]
                if isinstance(v, (int, float)):
                    vals.append(float(v))
                elif isinstance(v, str):
                    try:
                        vals.append(float(v))
                    except Exception:
                        all_numeric = False
                        break
                else:
                    all_numeric = False
                    break
            if all_numeric:
                weight_sum = sum(vals)
                if abs(weight_sum - 100.0) < 1e-6:
                    valid = True
    elif isinstance(sc, list):
        dims_list = []
        sumw = 0.0
        all_ok = True
        for item in sc:
            if not isinstance(item, dict):
                all_ok = False
                break
            dim = item.get("dimension") or item.get("name")
            w = item.get("weight")
            if dim is None or w is None:
                all_ok = False
                break
            dims_list.append(norm_key(dim))
            if isinstance(w, (int, float)):
                sumw += float(w)
            elif isinstance(w, str):
                try:
                    sumw += float(w)
                except Exception:
                    all_ok = False
                    break
        if all_ok and required_dims.issubset(set(dims_list)) and abs(sumw - 100.0) < 1e-6:
            valid = True
    checks["p3_scorecard_dims_sum100"] = valid

# Phase 4 validations
if checks["parse_phase4"] and isinstance(p4, dict):
    colors = p4.get("colors")
    color_paths = [
        ("primary","main"),
        ("primary","accent"),
        ("neutral","dark"),
        ("neutral","medium"),
        ("neutral","light"),
        ("neutral","white"),
        ("semantic","success"),
        ("semantic","warning"),
        ("semantic","error"),
        ("semantic","info"),
    ]
    colors_ok = False
    if isinstance(colors, dict):
        ok = True
        for a,b in color_paths:
            sub = colors.get(a)
            if not isinstance(sub, dict):
                ok = False
                break
            val = sub.get(b)
            if not is_hex6(val):
                ok = False
                break
        colors_ok = ok
    checks["p4_colors_valid"] = colors_ok

    ty = p4.get("typography")
    typo_ok = False
    if isinstance(ty, dict):
        heading = ty.get("heading")
        body = ty.get("body")
        mono = ty.get("mono")
        pairing = ty.get("pairing_rationale")
        if (isinstance(heading, dict) and isinstance(heading.get("family"), str)
            and isinstance(heading.get("weights"), list) and isinstance(heading.get("style"), str)
            and isinstance(body, dict) and isinstance(body.get("family"), str)
            and isinstance(body.get("weights"), list) and isinstance(body.get("style"), str)
            and isinstance(mono, dict) and isinstance(mono.get("family"), str)
            and isinstance(pairing, str)):
            typo_ok = True
    checks["p4_typography_fields"] = typo_ok

    lb = p4.get("logo_brief")
    lb_ok = False
    lb_variations_ok = False
    allowed_types = {"wordmark","lettermark","icon+wordmark","abstract","mascot"}
    if isinstance(lb, dict):
        lb_type = lb.get("type")
        must_convey = lb.get("must_convey")
        avoid = lb.get("avoid")
        usage = lb.get("usage_contexts")
        comp_look = lb.get("competitors_look_like")
        feel = lb.get("we_want_to_feel")
        min_size = lb.get("min_size")
        variations = lb.get("variations_needed")
        req_fields_ok = (isinstance(lb_type, str) and norm_str(lb_type) in allowed_types
                         and isinstance(must_convey, list) and len(must_convey) == 3
                         and isinstance(avoid, list) and 2 <= len(avoid) <= 3
                         and isinstance(usage, list) and isinstance(comp_look, str)
                         and isinstance(feel, str) and isinstance(min_size, str)
                         and isinstance(variations, list))
        if req_fields_ok:
            lb_ok = True
            required_variations = {"full color","single color","reversed (white)","icon only"}
            norm_vars = set(norm_str(v) for v in variations if isinstance(v, str))
            lb_variations_ok = required_variations.issubset(norm_vars)
    checks["p4_logo_brief_fields"] = lb_ok
    checks["p4_variations_contains_required"] = lb_variations_ok

    im = p4.get("imagery")
    im_ok = False
    if isinstance(im, dict):
        style = im.get("style")
        mood = im.get("mood")
        subjects = im.get("subjects")
        avoid_i = im.get("avoid")
        filters = im.get("filters")
        ar = im.get("aspect_ratios")
        if (isinstance(style, str) and isinstance(mood, str)
            and isinstance(subjects, list) and isinstance(avoid_i, list)
            and isinstance(filters, str)
            and isinstance(ar, dict) and all(k in ar for k in ["hero","social","blog"])):
            im_ok = True
    checks["p4_imagery_aspect_ratios"] = im_ok

# Phase 5 validations
if checks["parse_phase5"] and isinstance(p5, dict):
    gtm = p5.get("gtm")
    acv_value = None
    if isinstance(gtm, dict):
        acv = gtm.get("acv")
        if numeric(acv):
            checks["p5_acv_numeric"] = True
            acv_value = to_float(acv)
        sel = gtm.get("selected_motion")
        # motion vs ACV rule (only enforce for 10k-50k inclusive)
        if acv_value is not None and sel is not None and isinstance(sel, str):
            if 10000.0 <= acv_value <= 50000.0:
                if "sales" in sel.lower():
                    checks["p5_motion_vs_acv"] = True
            else:
                # Not required to enforce for other ranges, mark as true to not penalize
                checks["p5_motion_vs_acv"] = True

    pre = p5.get("pre_launch")
    if isinstance(pre, dict):
        weeks_ok = all(isinstance(pre.get(w), list) for w in ["week_4","week_3","week_2","week_1"])
        checks["p5_prelaunch_weeks"] = weeks_ok

    ldc = p5.get("launch_day_checklist")
    if isinstance(ldc, list) and len(ldc) >= 6:
        checks["p5_launch_checklist_len"] = True

    channels = p5.get("channels")
    chan_ok = False
    if isinstance(channels, list) and len(channels) >= 3:
        subkeys = {"name","purpose","target_audience","content_types","posting_cadence","kpi","target","budget","owner"}
        ok = True
        for ch in channels:
            if not isinstance(ch, dict) or not subkeys.issubset(set(ch.keys())):
                ok = False
                break
            if not isinstance(ch.get("content_types"), list):
                ok = False
                break
        chan_ok = ok
    checks["p5_channels_min3_and_fields"] = chan_ok

    battlecards = p5.get("battlecards")
    bc_ok = False
    bc_names_match = False
    if isinstance(battlecards, list) and len(battlecards) >= 2:
        req_bc_keys = {"competitor","their_pitch","their_strengths","their_weaknesses","landmine_questions","our_counter","win_themes","loss_reasons","trap_to_avoid"}
        ok = True
        names = set()
        for bc in battlecards:
            if not isinstance(bc, dict) or not req_bc_keys.issubset(set(bc.keys())):
                ok = False
                break
            if not isinstance(bc.get("their_strengths"), list) or not isinstance(bc.get("their_weaknesses"), list):
                ok = False
                break
            if not isinstance(bc.get("landmine_questions"), list):
                ok = False
                break
            oc = bc.get("our_counter")
            if not isinstance(oc, dict) or not all(k in oc for k in ["when_they_say","we_say"]):
                ok = False
                break
            names.add(bc.get("competitor"))
        bc_ok = ok
        # Names match Phase 1 competitors if Phase 1 parsed and has competitors
        if checks["p1_competitors_min3"] and checks["p1_competitors_fields"] and phase1_competitor_names:
            # Battlecard competitor names must be subset of phase1 competitor names
            match = True
            for nm in names:
                if not isinstance(nm, str) or nm.strip() not in phase1_competitor_names:
                    match = False
                    break
            bc_names_match = match
    checks["p5_battlecards_min2_and_fields"] = bc_ok
    checks["p5_battlecards_names_match_phase1"] = bc_names_match

# Phase 6 validations
if checks["parse_phase6"] and isinstance(p6, dict):
    hd = p6.get("health_dashboard")
    metrics_ok = False
    expected_metrics = [
        "aided awareness",
        "share of voice",
        "brand sentiment",
        "nps",
        "direct traffic",
        "branded search",
        "repeat purchase/renewal rate",
        "content engagement",
    ]
    # normalize and check each has how_to_measure and benchmark or target
    if isinstance(hd, dict):
        norm_map = {norm_key(k): v for k, v in hd.items()}
        ok = True
        for m in expected_metrics:
            mk = norm_key(m)
            item = norm_map.get(mk)
            if not isinstance(item, dict):
                ok = False
                break
            has_how = "how_to_measure" in item
            has_bench = ("benchmark" in item) or ("target" in item) or ("directional_target" in item)
            if not (has_how and has_bench):
                ok = False
                break
        metrics_ok = ok
    checks["p6_health_metrics_present"] = metrics_ok

    audit = p6.get("audit_checklist")
    audit_ok = False
    evo_ok = False
    if isinstance(audit, dict):
        cons = audit.get("consistency")
        eff = audit.get("effectiveness")
        evo = audit.get("evolution_signals")
        if isinstance(cons, list) and len(cons) >= 2 and isinstance(eff, list) and len(eff) >= 2:
            audit_ok = True
        if isinstance(evo, list) and len(evo) >= 1:
            evo_ok = True
    checks["p6_audit_sections"] = audit_ok and evo_ok

    rf = p6.get("rebrand_framework")
    rf_ok = False
    if isinstance(rf, dict):
        # find don't/do rebrand when (handle apostrophes and case)
        keys_norm = {norm_key(k): k for k in rf.keys()}
        dont_key = None
        do_key = None
        for nk, orig in keys_norm.items():
            if "dont_rebrand_when" in nk or "don't_rebrand_when" in nk:
                dont_key = orig
            if "do_rebrand_when" in nk:
                do_key = orig
        # scope options: either keys refresh/reposition/rename or under scope_options list
        scope_ok = False
        refresh_present = False
        reposition_present = False
        rename_present = False
        for k in rf.keys():
            nk = norm_key(k)
            if nk == "refresh":
                refresh_present = True
            if nk == "reposition":
                reposition_present = True
            if nk == "rename":
                rename_present = True
        scope_opts = rf.get("scope_options")
        if isinstance(scope_opts, dict):
            rset = set(norm_key(x) for x in scope_opts.keys())
            refresh_present = refresh_present or ("refresh" in rset)
            reposition_present = reposition_present or ("reposition" in rset)
            rename_present = rename_present or ("rename" in rset)
        elif isinstance(scope_opts, list):
            names = set()
            for it in scope_opts:
                if isinstance(it, dict):
                    # look for name or type field
                    nm = it.get("name") or it.get("type") or it.get("option")
                    if isinstance(nm, str):
                        names.add(norm_key(nm))
                elif isinstance(it, str):
                    names.add(norm_key(it))
            refresh_present = refresh_present or ("refresh" in names)
            reposition_present = reposition_present or ("reposition" in names)
            rename_present = rename_present or ("rename" in names)

        lists_ok = (dont_key in rf and isinstance(rf.get(dont_key), list) and len(rf.get(dont_key)) >= 1
                    and do_key in rf and isinstance(rf.get(do_key), list) and len(rf.get(do_key)) >= 1)
        scope_ok = refresh_present and reposition_present and rename_present
        rf_ok = lists_ok and scope_ok
    checks["p6_rebrand_framework"] = rf_ok

# CSV validations
if checks["parse_csv"] and csv_rows:
    header = csv_rows[0]
    if header == ["Dimension","Weight"]:
        checks["csv_headers_exact"] = True
    # Validate six required rows and weights
    dims_required = {
        "clarity": 25,
        "personality": 20,
        "specificity": 20,
        "action": 15,
        "consistency": 10,
        "audience_fit": 10,
    }
    rows_ok = False
    if len(csv_rows) == 7:  # header + 6 rows
        dims_seen = {}
        ok = True
        for row in csv_rows[1:]:
            if len(row) != 2:
                ok = False
                break
            dim = row[0]
            wt = row[1]
            nk = norm_key(dim)
            if nk not in dims_required:
                ok = False
                break
            try:
                wt_val = float(wt)
            except Exception:
                ok = False
                break
            dims_seen[nk] = wt_val
        if ok and set(dims_seen.keys()) == set(dims_required.keys()):
            # exact weights
            exact = True
            for k, v in dims_required.items():
                if abs(dims_seen.get(k, -1) - float(v)) > 1e-6:
                    exact = False
                    break
            rows_ok = exact
    checks["csv_rows_six_and_weights"] = rows_ok

# Compute reward
# Ensure no-op baseline: if output dir missing or no required artifacts, reward stays 0.0
any_exist = any(checks[k] for k in ["exists_phase1","exists_phase2","exists_phase3","exists_phase4","exists_phase5","exists_phase6","exists_csv"])
if not any_exist:
    reward = 0.0
else:
    reward = score_from_checks({k: v for k, v in checks.items() if isinstance(v, bool)})

# Print result JSON
result = {"reward": reward}
result.update(checks)
print(json.dumps(result))