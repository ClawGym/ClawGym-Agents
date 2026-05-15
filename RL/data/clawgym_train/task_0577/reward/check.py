import json
import os
import re
import sys
import xml.etree.ElementTree as ET

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    target_rel = os.path.join("output", "campus-network.xml")
    target_path = os.path.join(workspace_root, target_rel)

    checks = {
        "file_exists": False,
        "xml_parsed": False,
        "root_version_ok": False,
        "devices_count_ok": False,
        "devices_names_models_ok": False,
        "devices_uuid_ok": False,
        "devices_has_slot_ok": False,
        "lines_count_ok": False,
        "lines_ref_valid_ids": False,
        "lines_pairs_match_ok": False,
        "shapes_type1_min2": False,
        "shapes_blue_present": False,
        "shapes_yellow_present": False,
        "txt_vlan10_present": False,
        "txt_vlan20_present": False,
        "txt_serial_label_present": False,
    }

    if not os.path.isfile(target_path):
        # No-op baseline: reward should be 0.0
        print(json.dumps({"reward": 0.0, **checks}))
        return

    checks["file_exists"] = True

    try:
        tree = ET.parse(target_path)
        root = tree.getroot()
        checks["xml_parsed"] = True
    except Exception:
        # Parsing failed
        print(json.dumps({"reward": 0.0, **checks}))
        return

    # Root element and version
    if root.tag == "topo" and root.get("version") == "1.3.00.100":
        checks["root_version_ok"] = True

    # Devices validation
    devices = root.find("devices")
    dev_elems = []
    if devices is not None:
        dev_elems = [d for d in list(devices) if d.tag == "dev"]

    expected_devices = {
        "R1": "AR2220",
        "R2": "AR2220",
        "FW1": "USG6000V",
        "SW1": "S5700",
        "SW2": "S5700",
        "PC-A": "PC",
        "PC-B": "PC",
        "Server1": "Server",
        "Internet": "Cloud",
        "AC1": "AC6005",
        "AP1": "AP6050",
    }

    if len(dev_elems) == 11:
        checks["devices_count_ok"] = True

    name_to_model = {}
    name_to_id = {}
    all_uuid_v4 = True
    all_have_slot = True

    uuid_v4_re = re.compile(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
    )

    for dev in dev_elems:
        name = dev.get("name", "")
        model = dev.get("model", "")
        did = dev.get("id", "")
        name_to_model[name] = model
        if did:
            name_to_id[name] = did
        if not did or not uuid_v4_re.match(did):
            all_uuid_v4 = False
        slot = dev.find("slot")
        if slot is None:
            all_have_slot = False

    # Names and models must match exactly the expected set
    if set(name_to_model.keys()) == set(expected_devices.keys()):
        names_models_match = True
        for n, m in expected_devices.items():
            if name_to_model.get(n) != m:
                names_models_match = False
                break
        if names_models_match:
            checks["devices_names_models_ok"] = True

    if all_uuid_v4 and len(name_to_id) == len(dev_elems):
        checks["devices_uuid_ok"] = True

    if all_have_slot and len(dev_elems) == 11:
        checks["devices_has_slot_ok"] = True

    # Lines validation
    lines = root.find("lines")
    line_elems = []
    if lines is not None:
        line_elems = [l for l in list(lines) if l.tag == "line"]

    if len(line_elems) == 11:
        checks["lines_count_ok"] = True

    # Map IDs to names
    id_to_name = {v: k for k, v in name_to_id.items()}

    expected_pairs = set()
    # Serial
    expected_pairs.add((frozenset({"R1", "R2"}), "Serial"))
    # Copper pairs
    copper_list = [
        ("R1", "FW1"),
        ("R2", "FW1"),
        ("FW1", "SW1"),
        ("FW1", "SW2"),
        ("SW1", "PC-A"),
        ("SW2", "PC-B"),
        ("SW2", "Server1"),
        ("SW1", "AC1"),
        ("SW1", "AP1"),
        ("R1", "Internet"),
    ]
    for a, b in copper_list:
        expected_pairs.add((frozenset({a, b}), "Copper"))

    observed_pairs = set()
    ids_valid = True

    for le in line_elems:
        src_id = le.get("srcDeviceID")
        dst_id = le.get("destDeviceID")
        if src_id not in id_to_name or dst_id not in id_to_name:
            ids_valid = False
            # Still continue to process others to collect as much as possible
        src_name = id_to_name.get(src_id)
        dst_name = id_to_name.get(dst_id)
        ipairs = [ip for ip in list(le) if ip.tag == "interfacePair"]
        if not ipairs:
            # Missing interfacePair means we cannot validate lineName; this will make pairs mismatch
            continue
        # Consider the first interfacePair for determining lineName
        line_name = ipairs[0].get("lineName")
        if src_name and dst_name and line_name:
            observed_pairs.add((frozenset({src_name, dst_name}), line_name))

    if ids_valid and len(line_elems) > 0:
        checks["lines_ref_valid_ids"] = True

    if observed_pairs == expected_pairs and len(observed_pairs) == 11:
        checks["lines_pairs_match_ok"] = True

    # Shapes validation
    shapes = root.find("shapes")
    type1_count = 0
    blue_present = False
    yellow_present = False
    if shapes is not None:
        for sh in list(shapes):
            if sh.tag != "shape":
                continue
            if sh.get("type") == "1":
                type1_count += 1
                color = sh.get("color")
                if color == "255":
                    blue_present = True
                if color == "16776960":
                    yellow_present = True
    if type1_count >= 2:
        checks["shapes_type1_min2"] = True
    if blue_present:
        checks["shapes_blue_present"] = True
    if yellow_present:
        checks["shapes_yellow_present"] = True

    # Txttips validation
    txttips = root.find("txttips")
    vlan10_ok = False
    vlan20_ok = False
    serial_label_ok = False
    if txttips is not None:
        for tt in list(txttips):
            if tt.tag != "txttip":
                continue
            content = tt.get("content") or ""
            if "VLAN10 - Users" in content:
                vlan10_ok = True
            if "VLAN20 - Servers" in content:
                vlan20_ok = True
            if "Serial link R1-R2 (DCE/DTE)" in content:
                serial_label_ok = True
    if vlan10_ok:
        checks["txt_vlan10_present"] = True
    if vlan20_ok:
        checks["txt_vlan20_present"] = True
    if serial_label_ok:
        checks["txt_serial_label_present"] = True

    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Clamp reward to [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()