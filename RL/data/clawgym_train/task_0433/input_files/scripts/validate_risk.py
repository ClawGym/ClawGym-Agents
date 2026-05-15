#!/usr/bin/env python3
import argparse
import csv
import json
import os
import sys
from typing import Dict, Any, List

def load_policy(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_noise(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({"hour": int(r["hour"]), "pred_db": float(r["pred_db"])})
    return rows

def load_traffic(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "road": r["road"],
                "road_type": r["road_type"].strip().lower(),
                "veh_per_hour": int(r["veh_per_hour"])})
    return rows

def attenuation_db(buffer_m):
    # Simple proxy attenuation: up to 20 dB reduction, 1 dB per 5 m
    return min(20.0, float(buffer_m) / 5.0)

def is_daytime(hour: int) -> bool:
    return 7 <= hour < 22

def compute_noise_violations(policy: Dict[str, Any], noise_rows: List[Dict[str, Any]]):
    violations = []
    curfew = int(policy.get("curfew_hour", 23))
    buff = float(policy.get("noise_buffer_meters", 0))
    att = attenuation_db(buff)
    day_limit = float(policy.get("day_noise_limit_db", 70))
    night_limit = float(policy.get("night_noise_limit_db", 55))

    for r in noise_rows:
        hour = r["hour"]
        pred = float(r["pred_db"])
        # Curfew: if hour >= curfew_hour, stage is considered off -> noise ~ 0
        effective = 0.0 if hour >= curfew else max(0.0, pred - att)
        limit = day_limit if is_daytime(hour) else night_limit
        if effective > limit + 1e-6:
            violations.append({
                "hour": hour,
                "effective_db": round(effective, 2),
                "limit_db": limit
            })
    return violations

def compute_traffic_violations(policy: Dict[str, Any], traffic_rows: List[Dict[str, Any]]):
    violations = []
    limit = int(policy.get("residential_vph_limit", 1000))
    if limit > 1200:
        violations.append({
            "type": "policy_limit",
            "message": f"residential_vph_limit {limit} exceeds maximum allowed 1200"
        })

    detour_enabled = bool(policy.get("detour_enabled", False))
    detour_pct = float(policy.get("detour_residential_reduction_pct", 0)) / 100.0
    stag_minutes = int(policy.get("stagger_exit_minutes", 0))
    stag_pct = float(policy.get("stagger_effect_pct_at_30min", 0)) / 100.0 if stag_minutes >= 30 else 0.0

    for r in traffic_rows:
        if r["road_type"] != "residential":
            continue
        base = float(r["veh_per_hour"])
        factor = 1.0
        if detour_enabled and detour_pct > 0:
            factor *= (1.0 - min(0.9, detour_pct))
        if stag_pct > 0:
            factor *= (1.0 - min(0.9, stag_pct))
        mitigated = base * factor
        if mitigated > float(limit) + 1e-6:
            violations.append({
                "type": "residential_vph",
                "road": r["road"],
                "base_vph": int(base),
                "mitigated_vph": int(round(mitigated)),
                "limit_vph": limit
            })
    return violations

def compute_policy_violations(policy: Dict[str, Any]):
    violations = []
    if not bool(policy.get("emergency_access_plan", False)):
        violations.append({
            "type": "emergency_access",
            "message": "emergency_access_plan must be true"
        })
    return violations

def main():
    ap = argparse.ArgumentParser(description="Validate event risk mitigations.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--noise", required=True)
    ap.add_argument("--traffic", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    policy = load_policy(args.config)
    noise_rows = load_noise(args.noise)
    traffic_rows = load_traffic(args.traffic)

    noise_v = compute_noise_violations(policy, noise_rows)
    traffic_v = compute_traffic_violations(policy, traffic_rows)
    policy_v = compute_policy_violations(policy)

    status = "pass" if not (noise_v or traffic_v or policy_v) else "fail"

    report = {
        "status": status,
        "counts": {
            "noise_violations": len(noise_v),
            "traffic_violations": len([v for v in traffic_v if v.get("type") == "residential_vph"]),
            "policy_violations": len([v for v in traffic_v if v.get("type") == "policy_limit"]) + len(policy_v)
        },
        "details": {
            "noise": noise_v,
            "traffic": traffic_v,
            "policy": policy_v
        },
        "policy_used": {
            "curfew_hour": int(policy.get("curfew_hour", 23)),
            "residential_vph_limit": int(policy.get("residential_vph_limit", 1000)),
            "noise_buffer_meters": int(policy.get("noise_buffer_meters", 0)),
            "detour_enabled": bool(policy.get("detour_enabled", False)),
            "stagger_exit_minutes": int(policy.get("stagger_exit_minutes", 0))
        }
    }

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)

    summary = (
        f"status={status} | "
        f"noise={len(noise_v)} | "
        f"traffic={len([v for v in traffic_v if v.get('type')=='residential_vph'])} | "
        f"policy={report['counts']['policy_violations']}"
    )
    print(summary)
    sys.exit(0 if status == "pass" else 1)

if __name__ == "__main__":
    main()
