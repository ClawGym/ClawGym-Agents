import json
import os
import re
import sys
from typing import Any, Dict, List

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_number(n):
    return isinstance(n, (int, float)) and not isinstance(n, bool)

def in_range01(x):
    return is_number(x) and 0.0 <= float(x) <= 1.0

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    report_path = os.path.join(output_dir, "report.json")
    dashboard_path = os.path.join(output_dir, "dashboard.txt")
    annotation_path = os.path.join(output_dir, "annotation.txt")

    checks: Dict[str, bool] = {
        "has_report": False,
        "report_valid_json": False,
        "root_intent_ok": False,
        "per_turn_count_ok": False,
        "per_turn_structure_ok": False,
        "drift_patterns_fields_ok": False,
        "contradiction_flag_present": False,
        "trends_values_ok": False,
        "alerts_structure_ok": False,
        "alert_gpr_present": False,
        "alert_dd_tangential_present": False,
        "alert_dd_circular_present": False,
        "alert_ct_present": False,
        "alert_cbs_contradiction_present": False,
        "sqp_decline_condition_ok": False,
        "overall_index_ok": False,
        "status_ok": False,
        "status_not_healthy": False,
        "dashboard_exists_and_contains_required": False,
        "annotation_format_ok": False,
    }

    report = load_json(report_path)
    if report is None:
        # No report -> no further checks pass
        result = finalize(checks)
        print(json.dumps(result))
        return

    checks["has_report"] = True
    checks["report_valid_json"] = isinstance(report, dict)

    if not isinstance(report, dict):
        result = finalize(checks)
        print(json.dumps(result))
        return

    # root_intent check
    root_intent = report.get("root_intent")
    if isinstance(root_intent, str):
        ri = root_intent.strip()
        if ri:
            # Must include "EU" and indicate a summary goal
            contains_eu = ("eu" in ri.lower())
            summary_markers = ["summary", "summarize", "overview", "outline", "plan", "guide", "guidelines", "brief", "summary goal", "eu-only", "eu only", "focus"]
            indicates_summary = any(m in ri.lower() for m in summary_markers)
            if contains_eu and indicates_summary:
                checks["root_intent_ok"] = True

    # per_turn count and structure
    per_turn = report.get("per_turn")
    if isinstance(per_turn, list) and len(per_turn) == 5:
        checks["per_turn_count_ok"] = True

    # Initialize accumulators for alerts and trends
    all_alerts: List[Dict[str, Any]] = []
    sqp_scores: List[float] = []
    any_declining_trend = False

    structure_ok_all = True
    drift_patterns_ok_all = True
    contradiction_flag_present_any = False
    trends_values_ok_all = True
    alerts_structure_ok_all = True

    if isinstance(per_turn, list):
        for item in per_turn:
            # turn_number
            if not isinstance(item, dict):
                structure_ok_all = False
                continue
            tn = item.get("turn_number")
            if not isinstance(tn, int):
                structure_ok_all = False

            sensors = item.get("sensors")
            if not isinstance(sensors, dict):
                structure_ok_all = False
                continue

            # Required sensor keys
            required_sensors = [
                "goalProximityRadar",
                "confidenceTopography",
                "driftDetection",
                "capabilityBoundary",
                "sessionQualityPulse",
            ]
            for sk in required_sensors:
                if sk not in sensors or not isinstance(sensors[sk], dict):
                    structure_ok_all = False

            # Scores in [0,1]
            for sk in required_sensors:
                sd = sensors.get(sk, {})
                if not in_range01(sd.get("score")):
                    structure_ok_all = False

            # Drift patterns fields
            dd = sensors.get("driftDetection", {})
            patterns = dd.get("patterns")
            if not isinstance(patterns, dict):
                drift_patterns_ok_all = False
            else:
                circ = patterns.get("circular")
                tang = patterns.get("tangential")
                if not isinstance(circ, bool) or not isinstance(tang, bool):
                    drift_patterns_ok_all = False

            # Capability boundary contradiction
            cbs = sensors.get("capabilityBoundary", {})
            details = cbs.get("details")
            has_contra_present = False
            if isinstance(details, dict) and "hasContradiction" in details and isinstance(details.get("hasContradiction"), bool):
                has_contra_present = True
                if details.get("hasContradiction"):
                    contradiction_flag_present_any = True
            if not has_contra_present:
                # presence required
                structure_ok_all = False

            # Session quality pulse trend
            sqp = sensors.get("sessionQualityPulse", {})
            trend = sqp.get("trend")
            if trend not in {"improving", "stable", "declining", "volatile"}:
                trends_values_ok_all = False
            else:
                if trend == "declining":
                    any_declining_trend = True
            if in_range01(sqp.get("score")):
                sqp_scores.append(float(sqp.get("score")))

            # Alerts structure
            alerts = item.get("alerts")
            if not isinstance(alerts, list):
                alerts_structure_ok_all = False
            else:
                for al in alerts:
                    if not isinstance(al, dict):
                        alerts_structure_ok_all = False
                        continue
                    sev = al.get("severity")
                    sensor_name = al.get("sensor")
                    msg = al.get("message")
                    if not isinstance(sev, str) or sev not in {"INFO", "WARNING", "CRITICAL"}:
                        alerts_structure_ok_all = False
                    if not isinstance(sensor_name, str):
                        alerts_structure_ok_all = False
                    if not isinstance(msg, str) or msg.strip() == "":
                        alerts_structure_ok_all = False
                    all_alerts.append(al)

    checks["per_turn_structure_ok"] = structure_ok_all and checks["per_turn_count_ok"]
    checks["drift_patterns_fields_ok"] = drift_patterns_ok_all and checks["per_turn_count_ok"]
    checks["contradiction_flag_present"] = contradiction_flag_present_any
    checks["trends_values_ok"] = trends_values_ok_all and checks["per_turn_count_ok"]
    checks["alerts_structure_ok"] = alerts_structure_ok_all and checks["per_turn_count_ok"]

    # Alerts presence checks across all turns
    def find_alert(predicate):
        for al in all_alerts:
            try:
                if predicate(al):
                    return True
            except Exception:
                continue
        return False

    # Goal Proximity Radar WARNING/CRITICAL
    checks["alert_gpr_present"] = find_alert(
        lambda a: a.get("sensor") == "Goal Proximity Radar" and a.get("severity") in {"WARNING", "CRITICAL"}
    )

    # Drift Detection tangential mention
    checks["alert_dd_tangential_present"] = find_alert(
        lambda a: a.get("sensor") == "Drift Detection" and isinstance(a.get("message"), str) and ("tangential" in a.get("message").lower())
    )

    # Drift Detection circular mention
    checks["alert_dd_circular_present"] = find_alert(
        lambda a: a.get("sensor") == "Drift Detection" and isinstance(a.get("message"), str) and ("circular" in a.get("message").lower())
    )

    # Confidence Topography WARNING/CRITICAL
    checks["alert_ct_present"] = find_alert(
        lambda a: a.get("sensor") == "Confidence Topography" and a.get("severity") in {"WARNING", "CRITICAL"}
    )

    # Capability Boundary contradiction mention
    checks["alert_cbs_contradiction_present"] = find_alert(
        lambda a: a.get("sensor") == "Capability Boundary" and isinstance(a.get("message"), str) and ("contradiction" in a.get("message").lower())
    )

    # SQP decline condition: at least one 'declining' trend and either an SQP alert or multiple low-scoring turns indicating decline
    sqp_alert_present = find_alert(lambda a: a.get("sensor") == "Session Quality Pulse")
    has_multiple_low_scoring_decline = False
    if len(sqp_scores) >= 2:
        # find any two consecutive scores that are both < 0.5 and strictly decreasing
        for i in range(1, len(sqp_scores)):
            if sqp_scores[i-1] < 0.5 and sqp_scores[i] < 0.5 and sqp_scores[i] < sqp_scores[i-1]:
                has_multiple_low_scoring_decline = True
                break
    if any_declining_trend and (sqp_alert_present or has_multiple_low_scoring_decline):
        checks["sqp_decline_condition_ok"] = True

    # overallIndex and status
    overall_index = report.get("overallIndex")
    if in_range01(overall_index):
        checks["overall_index_ok"] = True

    status = report.get("status")
    if isinstance(status, str) and status in {"HEALTHY", "WARNING", "CRITICAL"}:
        checks["status_ok"] = True
        if status != "HEALTHY":
            checks["status_not_healthy"] = True

    # dashboard checks
    dash_text = read_text(dashboard_path)
    if dash_text:
        has_header = "PROPRIOCEPTION DASHBOARD" in dash_text
        has_gpr = "Goal Proximity Radar" in dash_text
        has_ct = "Confidence Topography" in dash_text
        has_dd = "Drift Detection" in dash_text
        has_cbs = "Capability Boundary" in dash_text
        has_sqp = "Session Quality Pulse" in dash_text
        has_status = "Status:" in dash_text
        has_overall = ("Overall Proprioceptive Index" in dash_text)
        if all([has_header, has_gpr, has_ct, has_dd, has_cbs, has_sqp, has_status, has_overall]):
            checks["dashboard_exists_and_contains_required"] = True

    # annotation format check
    annotation_text = read_text(annotation_path).strip()
    # Regex per spec: ^\[P: GPR=\d\.?\d{0,2} \| CT=\d\.?\d{0,2} \| DD=\d\.?\d{0,2} \| CBS=\d\.?\d{0,2} \| SQP=\d\.?\d{0,2}\]$
    ann_re = re.compile(r"^\[P: GPR=\d\.?\d{0,2} \| CT=\d\.?\d{0,2} \| DD=\d\.?\d{0,2} \| CBS=\d\.?\d{0,2} \| SQP=\d\.?\d{0,2}\]$")
    if annotation_text and ann_re.match(annotation_text):
        checks["annotation_format_ok"] = True

    result = finalize(checks)
    print(json.dumps(result))

def finalize(checks: Dict[str, bool]) -> Dict[str, Any]:
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # If no artifacts (baseline), ensure reward is exactly 0.0
    # Baseline: when no output files so no checks passed beyond defaults
    reward = 0.0
    if passed > 0:
        reward = passed / total
        if reward < 0.0:
            reward = 0.0
        if reward > 1.0:
            reward = 1.0
    # Ensure "reward" is first field
    out: Dict[str, Any] = {"reward": reward}
    out.update(checks)
    return out

if __name__ == "__main__":
    main()