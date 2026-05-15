import json
import os
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def is_feature_collection(obj):
    return isinstance(obj, dict) and obj.get("type") == "FeatureCollection" and isinstance(obj.get("features"), list)

def get_feature_count(fc):
    return len(fc.get("features", [])) if is_feature_collection(fc) else 0

def coords_have_abs_gt_threshold(geom, threshold=1000):
    # Recursively search coordinates for any numeric value with abs > threshold
    if not isinstance(geom, dict):
        return False
    if geom.get("type") is None or geom.get("coordinates") is None:
        return False
    coords = geom.get("coordinates")

    def recurse(node):
        if isinstance(node, (int, float)):
            return abs(node) > threshold
        if isinstance(node, list):
            for v in node:
                if recurse(v):
                    return True
        return False

    return recurse(coords)

def any_geometry_coord_mag_gt_threshold(fc, threshold=1000):
    if not is_feature_collection(fc):
        return False
    for feat in fc.get("features", []):
        geom = feat.get("geometry")
        if geom and coords_have_abs_gt_threshold(geom, threshold=threshold):
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    sites_buffer_path = os.path.join(output_dir, "sites_buffer_250m_dissolved.json")
    roads_within_path = os.path.join(output_dir, "roads_within_250m.json")
    report_path = os.path.join(output_dir, "processing_report.json")

    checks = {
        # Sites buffer dissolved checks
        "sites_buffer_file_exists": False,
        "sites_buffer_valid_geojson": False,
        "sites_buffer_featurecount_correct": False,  # expect exactly 2
        "sites_buffer_metric_crs_indicated": False,  # any coord abs > 1000

        # Roads within checks
        "roads_within_file_exists": False,
        "roads_within_valid_geojson": False,
        "roads_within_featurecount_minimum": False,  # expect >= 2
        "roads_within_metric_crs_indicated": False,  # any coord abs > 1000

        # Report checks
        "report_file_exists": False,
        "report_valid_json": False,
        "report_target_crs_correct": False,
        "report_counts_match": False
    }

    # Load and validate sites buffer dissolved
    sites_fc = None
    if os.path.isfile(sites_buffer_path):
        checks["sites_buffer_file_exists"] = True
        sites_fc, err = load_json(sites_buffer_path)
        if sites_fc is not None and is_feature_collection(sites_fc):
            checks["sites_buffer_valid_geojson"] = True
            # exact feature count expected: 2
            if get_feature_count(sites_fc) == 2:
                checks["sites_buffer_featurecount_correct"] = True
            # EPSG:3857 indication by coordinate magnitude
            if any_geometry_coord_mag_gt_threshold(sites_fc, threshold=1000):
                checks["sites_buffer_metric_crs_indicated"] = True

    # Load and validate roads within
    roads_fc = None
    if os.path.isfile(roads_within_path):
        checks["roads_within_file_exists"] = True
        roads_fc, err = load_json(roads_within_path)
        if roads_fc is not None and is_feature_collection(roads_fc):
            checks["roads_within_valid_geojson"] = True
            # at least 2 features expected
            if get_feature_count(roads_fc) >= 2:
                checks["roads_within_featurecount_minimum"] = True
            # EPSG:3857 indication
            if any_geometry_coord_mag_gt_threshold(roads_fc, threshold=1000):
                checks["roads_within_metric_crs_indicated"] = True

    # Load and validate processing report
    report = None
    if os.path.isfile(report_path):
        checks["report_file_exists"] = True
        report, err = load_json(report_path)
        if isinstance(report, dict):
            required_keys_present = all(k in report for k in ["target_crs", "sites_buffer_dissolved_count", "roads_within_250m_count"])
            if required_keys_present:
                checks["report_valid_json"] = True
                # target_crs exact match
                if report.get("target_crs") == "EPSG:3857":
                    checks["report_target_crs_correct"] = True
                # counts match observed feature counts
                sites_count = get_feature_count(sites_fc) if sites_fc and is_feature_collection(sites_fc) else None
                roads_count = get_feature_count(roads_fc) if roads_fc and is_feature_collection(roads_fc) else None
                if sites_count is not None and roads_count is not None:
                    if report.get("sites_buffer_dissolved_count") == sites_count and report.get("roads_within_250m_count") == roads_count:
                        checks["report_counts_match"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Ensure no-op baseline: if no outputs exist, reward is 0.0
    outputs_exist = any([checks["sites_buffer_file_exists"], checks["roads_within_file_exists"], checks["report_file_exists"]])
    if not outputs_exist:
        reward = 0.0

    # Print final JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()