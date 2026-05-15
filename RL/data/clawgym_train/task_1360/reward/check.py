import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def regex_search(text, pattern, flags=0):
    if text is None:
        return False
    return re.search(pattern, text, flags) is not None

def contains(text, substring):
    if text is None:
        return False
    return substring in text

def load_patches(patches_path):
    # Default assumptions if file missing or unparseable
    result = {
        "inlet": "inlet",
        "outlet": "outlet",
        "walls": "walls",
        "thin_empty": ["frontAndBack"]
    }
    try:
        with open(patches_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        names = []
        # Many possible shapes; try to normalize
        thin_empty = set()
        inlet_name = None
        outlet_name = None
        walls_name = None

        # Case A: {"patches":[{"name":"inlet","type":"patch"},...]}
        if isinstance(data, dict) and "patches" in data and isinstance(data["patches"], list):
            for p in data["patches"]:
                if not isinstance(p, dict):
                    continue
                n = p.get("name")
                t = (p.get("type") or "").lower()
                if not n:
                    continue
                names.append(n)
                if n == "inlet":
                    inlet_name = n
                if n == "outlet":
                    outlet_name = n
                if n == "walls" or t == "wall":
                    walls_name = n if walls_name is None else walls_name
                if t == "empty":
                    thin_empty.add(n)
        # Case B: dict mapping names to types or detail
        elif isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, dict):
                    t = (v.get("type") or "").lower()
                elif isinstance(v, str):
                    t = v.lower()
                else:
                    t = ""
                names.append(k)
                if k == "inlet":
                    inlet_name = k
                if k == "outlet":
                    outlet_name = k
                if k == "walls" or t == "wall":
                    walls_name = k if walls_name is None else walls_name
                if t == "empty":
                    thin_empty.add(k)
        # Fallback: try top-level list of names
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    names.append(item)
                elif isinstance(item, dict):
                    n = item.get("name")
                    t = (item.get("type") or "").lower()
                    if n:
                        names.append(n)
                        if n == "inlet":
                            inlet_name = n
                        if n == "outlet":
                            outlet_name = n
                        if n == "walls" or t == "wall":
                            walls_name = n if walls_name is None else walls_name
                        if t == "empty":
                            thin_empty.add(n)

        # Apply defaults if unresolved
        result["inlet"] = inlet_name or result["inlet"]
        result["outlet"] = outlet_name or result["outlet"]
        result["walls"] = walls_name or ( "walls" if "walls" in names else result["walls"] )
        if thin_empty:
            result["thin_empty"] = sorted(thin_empty)
    except Exception:
        pass
    return result

def extract_patch_block(text, patch_name):
    if text is None or not patch_name:
        return None
    # Find the patch block by name followed by a '{' and parse braces
    # Use regex to find the start index of the patch name token
    pattern = r'(^|\s)'+re.escape(patch_name)+r'\s*\{'
    m = re.search(pattern, text)
    if not m:
        return None
    # Find the '{' after patch name
    start_brace = text.find('{', m.start())
    if start_brace == -1:
        return None
    depth = 0
    for i in range(start_brace, len(text)):
        ch = text[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start_brace:i+1]
    return None

def has_empty_patch_in_file(text, empty_patch_names):
    # "judge by presence of one patch whose type is 'empty'"
    for n in empty_patch_names:
        block = extract_patch_block(text, n)
        if block and ("type" in block) and ("empty" in block):
            # ensure 'type empty' appears
            if regex_search(block, r'\btype\s+empty\b'):
                return True
    return False

def patch_block_has(block, substrings_or_regex_list, regex=False):
    if block is None:
        return False
    if not regex:
        return all((s in block) for s in substrings_or_regex_list)
    else:
        return all((re.search(p, block) is not None) for p in substrings_or_regex_list)

def check_boundary_presence(text, required_patches, empty_patch_names):
    ok = True
    for n in required_patches:
        if extract_patch_block(text, n) is None:
            ok = False
            break
    # require at least one empty patch present
    ok = ok and any(extract_patch_block(text, n) is not None for n in empty_patch_names)
    return ok

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    case_dir = os.path.join(output_dir, "duct_case")

    # Paths
    f_U = os.path.join(case_dir, "0", "U")
    f_p = os.path.join(case_dir, "0", "p")
    f_k = os.path.join(case_dir, "0", "k")
    f_omega = os.path.join(case_dir, "0", "omega")
    f_nut = os.path.join(case_dir, "0", "nut")
    f_turb = os.path.join(case_dir, "constant", "turbulenceProperties")
    f_trans = os.path.join(case_dir, "constant", "transportProperties")
    f_control = os.path.join(case_dir, "system", "controlDict")
    f_schemes = os.path.join(case_dir, "system", "fvSchemes")
    f_solution = os.path.join(case_dir, "system", "fvSolution")
    f_decompose = os.path.join(case_dir, "system", "decomposeParDict")
    f_summary = os.path.join(case_dir, "case_summary.md")
    f_patches = os.path.join(input_dir, "patches.json")

    # Load outputs
    t_U = read_text(f_U)
    t_p = read_text(f_p)
    t_k = read_text(f_k)
    t_omega = read_text(f_omega)
    t_nut = read_text(f_nut)
    t_turb = read_text(f_turb)
    t_trans = read_text(f_trans)
    t_control = read_text(f_control)
    t_schemes = read_text(f_schemes)
    t_solution = read_text(f_solution)
    t_decompose = read_text(f_decompose)
    t_summary = read_text(f_summary)

    # Load input patches reference
    patches_info = load_patches(f_patches)
    inlet_name = patches_info["inlet"]
    outlet_name = patches_info["outlet"]
    walls_name = patches_info["walls"]
    empty_patch_names = patches_info["thin_empty"]

    required_patch_names = [inlet_name, outlet_name, walls_name]

    checks = {}

    # Presence checks
    checks["has_U_file"] = os.path.isfile(f_U)
    checks["has_p_file"] = os.path.isfile(f_p)
    checks["has_k_file"] = os.path.isfile(f_k)
    checks["has_omega_file"] = os.path.isfile(f_omega)
    checks["has_nut_file"] = os.path.isfile(f_nut)
    checks["has_turbulenceProperties"] = os.path.isfile(f_turb)
    checks["has_transportProperties"] = os.path.isfile(f_trans)
    checks["has_controlDict"] = os.path.isfile(f_control)
    checks["has_fvSchemes"] = os.path.isfile(f_schemes)
    checks["has_fvSolution"] = os.path.isfile(f_solution)
    checks["has_decomposeParDict"] = os.path.isfile(f_decompose)
    checks["has_case_summary"] = os.path.isfile(f_summary)

    # controlDict checks
    checks["controlDict_application_simpleFoam"] = regex_search(t_control, r'\bapplication\s+simpleFoam;')
    checks["controlDict_has_yPlus"] = contains(t_control, "yPlus")

    # turbulenceProperties checks
    checks["turbulenceProperties_has_RASModel"] = contains(t_turb, "RASModel")
    checks["turbulenceProperties_has_kOmegaSST"] = contains(t_turb, "kOmegaSST")
    # "contains a signal that turbulence is enabled (e.g., 'turbulence')" - require the word 'turbulence'
    checks["turbulenceProperties_enables_turbulence"] = regex_search(t_turb, r'\bturbulence\b')

    # transportProperties: "nu" with bracketed dimensions
    checks["transportProperties_has_nu_with_dimensions"] = regex_search(t_trans, r'\bnu\s*\[[^\]]+\]')

    # fvSchemes
    checks["fvSchemes_has_div_phi_U_upwind"] = (contains(t_schemes, "div(phi,U)") and regex_search(t_schemes, r'\bupwind\b'))

    # fvSolution
    checks["fvSolution_has_p_solver_block"] = regex_search(t_solution, r'^[ \t]*p[ \t\r\n]*\{', flags=re.MULTILINE)
    checks["fvSolution_has_U_solver_block"] = regex_search(t_solution, r'^[ \t]*U[ \t\r\n]*\{', flags=re.MULTILINE)
    checks["fvSolution_has_SIMPLE"] = contains(t_solution, "SIMPLE")

    # decomposeParDict
    checks["decompose_method_scotch"] = regex_search(t_decompose, r'\bmethod\s+scotch;')
    checks["decompose_nSubdomains_4"] = regex_search(t_decompose, r'\bnumberOfSubdomains\s+4;')

    # Boundary consistency and specific BCs
    # Ensure boundaryField sections have required patches and at least one empty patch with type empty
    checks["boundaries_U_has_inlet_outlet_walls_and_empty"] = False
    checks["boundaries_p_has_inlet_outlet_walls_and_empty"] = False
    checks["boundaries_k_has_inlet_outlet_walls_and_empty"] = False
    checks["boundaries_omega_has_inlet_outlet_walls_and_empty"] = False
    checks["boundaries_nut_has_inlet_outlet_walls_and_empty"] = False

    if t_U is not None:
        checks["boundaries_U_has_inlet_outlet_walls_and_empty"] = check_boundary_presence(t_U, required_patch_names, empty_patch_names)
    if t_p is not None:
        checks["boundaries_p_has_inlet_outlet_walls_and_empty"] = check_boundary_presence(t_p, required_patch_names, empty_patch_names)
    if t_k is not None:
        checks["boundaries_k_has_inlet_outlet_walls_and_empty"] = check_boundary_presence(t_k, required_patch_names, empty_patch_names)
    if t_omega is not None:
        checks["boundaries_omega_has_inlet_outlet_walls_and_empty"] = check_boundary_presence(t_omega, required_patch_names, empty_patch_names)
    if t_nut is not None:
        checks["boundaries_nut_has_inlet_outlet_walls_and_empty"] = check_boundary_presence(t_nut, required_patch_names, empty_patch_names)

    # U inlet fixedValue uniform (1 0 0)
    U_inlet_block = extract_patch_block(t_U, inlet_name) if t_U is not None else None
    checks["U_inlet_fixedValue_uniform_1_0_0"] = patch_block_has(U_inlet_block, ["type", "fixedValue", "uniform (1 0 0)"]) if U_inlet_block else False

    # U walls noSlip
    U_walls_block = extract_patch_block(t_U, walls_name) if t_U is not None else None
    checks["U_walls_noSlip"] = patch_block_has(U_walls_block, ["type", "noSlip"]) if U_walls_block else False

    # U outlet suitable type: pressureInletOutletVelocity or zeroGradient
    U_outlet_block = extract_patch_block(t_U, outlet_name) if t_U is not None else None
    checks["U_outlet_outlet_type_suitable"] = False
    if U_outlet_block:
        if ("pressureInletOutletVelocity" in U_outlet_block) or regex_search(U_outlet_block, r'\bzeroGradient\b'):
            checks["U_outlet_outlet_type_suitable"] = True

    # p outlet fixedValue uniform 0
    p_outlet_block = extract_patch_block(t_p, outlet_name) if t_p is not None else None
    checks["p_outlet_fixedValue_uniform_0"] = patch_block_has(p_outlet_block, ["type", "fixedValue", "uniform 0"]) if p_outlet_block else False

    # empty type in all relevant fields (at least one empty patch with 'type empty' in each file)
    checks["U_has_empty_patch_type_empty"] = has_empty_patch_in_file(t_U, empty_patch_names)
    checks["p_has_empty_patch_type_empty"] = has_empty_patch_in_file(t_p, empty_patch_names)
    checks["k_has_empty_patch_type_empty"] = has_empty_patch_in_file(t_k, empty_patch_names)
    checks["omega_has_empty_patch_type_empty"] = has_empty_patch_in_file(t_omega, empty_patch_names)
    checks["nut_has_empty_patch_type_empty"] = has_empty_patch_in_file(t_nut, empty_patch_names)

    # Turbulence wall functions on walls patch
    k_walls_block = extract_patch_block(t_k, walls_name) if t_k is not None else None
    omega_walls_block = extract_patch_block(t_omega, walls_name) if t_omega is not None else None
    nut_walls_block = extract_patch_block(t_nut, walls_name) if t_nut is not None else None

    checks["k_has_kqRWallFunction_on_walls"] = patch_block_has(k_walls_block, ["kqRWallFunction"]) if k_walls_block else False
    checks["omega_has_omegaWallFunction_on_walls"] = patch_block_has(omega_walls_block, ["omegaWallFunction"]) if omega_walls_block else False
    checks["nut_has_nutkWallFunction_on_walls"] = patch_block_has(nut_walls_block, ["nutkWallFunction"]) if nut_walls_block else False

    # Summary checks
    checks["summary_has_solver_simpleFoam"] = contains(t_summary, "Solver: simpleFoam")
    checks["summary_has_turbulence_model_kOmegaSST"] = contains(t_summary, "Turbulence model: kOmegaSST")
    checks["summary_has_2D_yes"] = contains(t_summary, "2D: yes")
    # Patch names in summary: require inlet, outlet, walls and at least one thin patch name mentioned
    summary_has_inlet = contains(t_summary, inlet_name)
    summary_has_outlet = contains(t_summary, outlet_name)
    summary_has_walls = contains(t_summary, walls_name)
    summary_has_thin = any(contains(t_summary, n) for n in empty_patch_names)
    checks["summary_has_patch_names"] = (summary_has_inlet and summary_has_outlet and summary_has_walls and summary_has_thin)
    checks["summary_has_parallel_subdomains_4"] = contains(t_summary, "Parallel subdomains: 4")

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Enforce no-op baseline: if output dir doesn't exist or is empty, reward must be 0
    if not os.path.isdir(case_dir):
        reward = 0.0
    else:
        # If none of the presence checks are true, set reward to 0.0
        presence_keys = [k for k in checks.keys() if k.startswith("has_")]
        if not any(checks[k] for k in presence_keys):
            reward = 0.0

    # Print single JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))


if __name__ == "__main__":
    main()