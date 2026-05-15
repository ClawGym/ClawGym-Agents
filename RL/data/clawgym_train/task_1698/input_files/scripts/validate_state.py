import argparse
import json
import sys


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def compare_state(cfg, st):
    mismatches = []
    checks = 0

    # Audio fields
    for k in ["sample_rate_hz", "buffer_size", "bit_depth"]:
        checks += 1
        cfg_v = cfg.get("audio", {}).get(k)
        st_v = st.get("audio", {}).get(k)
        if cfg_v != st_v:
            mismatches.append(f"audio.{k}: expected {cfg_v}, got {st_v}")

    # System fields
    for k in ["disable_sleep", "power_mode"]:
        checks += 1
        cfg_v = cfg.get("system", {}).get(k)
        st_v = st.get("system", {}).get(k)
        if cfg_v != st_v:
            mismatches.append(f"system.{k}: expected {cfg_v}, got {st_v}")

    # Profile name
    checks += 1
    if cfg.get("profile_name") != st.get("profile_name"):
        mismatches.append(
            f"profile_name: expected {cfg.get('profile_name')}, got {st.get('profile_name')}"
        )

    # Devices list comparison (names and preferred flags)
    cfg_devs = cfg.get("devices", [])
    st_devs = st.get("devices", [])
    checks += 1
    if len(cfg_devs) != len(st_devs):
        mismatches.append(f"devices length: expected {len(cfg_devs)}, got {len(st_devs)}")
    else:
        for i, (cd, sd) in enumerate(zip(cfg_devs, st_devs)):
            checks += 1
            if cd.get("name") != sd.get("name") or cd.get("preferred") != sd.get("preferred"):
                mismatches.append(
                    f"devices[{i}]: expected (name={cd.get('name')}, preferred={cd.get('preferred')}), "
                    f"got (name={sd.get('name')}, preferred={sd.get('preferred')})"
                )

    passed = len(mismatches) == 0
    return passed, mismatches, checks


def main():
    ap = argparse.ArgumentParser(description="Validate studio profile application state")
    ap.add_argument("--config", required=True, help="Path to studio_profile.json")
    ap.add_argument("--state", required=True, help="Path to generated system_state.json")
    ap.add_argument("--report", required=True, help="Path to write validation report JSON")
    args = ap.parse_args()

    try:
        cfg = load_json(args.config)
        st = load_json(args.state)
    except Exception as e:
        print(f"ERROR: Failed to load JSON: {e}")
        sys.exit(2)

    passed, mismatches, checks = compare_state(cfg, st)
    summary = "PASS" if passed else f"FAIL ({len(mismatches)} mismatch(es))"

    report = {
        "passed": passed,
        "summary": summary,
        "mismatches": mismatches,
        "fields_checked": checks
    }

    with open(args.report, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)

    print(summary)
    if not passed:
        for m in mismatches:
            print(f"- {m}")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
