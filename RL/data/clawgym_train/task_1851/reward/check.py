import json
import os
import sys
import math
import csv
import re

def read_json(path):
    with open(path, "r") as f:
        return json.load(f)

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def mat_transpose(R):
    return [[R[j][i] for j in range(3)] for i in range(3)]

def mat_mul(A, B):
    return [
        [
            A[i][0]*B[0][j] + A[i][1]*B[1][j] + A[i][2]*B[2][j]
            for j in range(3)
        ]
        for i in range(3)
    ]

def mat_identity():
    return [[1.0,0.0,0.0],[0.0,1.0,0.0],[0.0,0.0,1.0]]

def mat_diff_max(A, B):
    m = 0.0
    for i in range(3):
        for j in range(3):
            m = max(m, abs(A[i][j] - B[i][j]))
    return m

def det3(R):
    a,b,c = R[0]
    d,e,f = R[1]
    g,h,i = R[2]
    return a*(e*i - f*h) - b*(d*i - f*g) + c*(d*h - e*g)

def is_orthonormal_det1(R, ortho_tol=1e-6, det_tol=1e-6):
    if not (isinstance(R, list) and len(R) == 3 and all(isinstance(row, list) and len(row) == 3 for row in R)):
        return False, False
    # numeric
    try:
        _ = float(R[0][0])
    except Exception:
        return False, False
    RtR = mat_mul(mat_transpose(R), R)
    ortho_ok = mat_diff_max(RtR, mat_identity()) <= ortho_tol
    d = det3(R)
    det_ok = abs(d - 1.0) <= det_tol
    return ortho_ok, det_ok

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def axis_angle_to_matrix(axis, angle):
    x,y,z = axis
    c = math.cos(angle)
    s = math.sin(angle)
    C = 1 - c
    return [
        [c + x*x*C,     x*y*C - z*s, x*z*C + y*s],
        [y*x*C + z*s,   c + y*y*C,   y*z*C - x*s],
        [z*x*C - y*s,   z*y*C + x*s, c + z*z*C  ],
    ]

def euler_zyx_to_matrix(euler):
    # euler = [z, y, x] (yaw, pitch, roll), intrinsic 'zyx'
    z, y, x = euler
    cz, sz = math.cos(z), math.sin(z)
    cy, sy = math.cos(y), math.sin(y)
    cx, sx = math.cos(x), math.sin(x)
    # R = Rz(z) @ Ry(y) @ Rx(x)
    Rz = [[cz,-sz,0.0],[sz,cz,0.0],[0.0,0.0,1.0]]
    Ry = [[cy,0.0,sy],[0.0,1.0,0.0],[-sy,0.0,cy]]
    Rx = [[1.0,0.0,0.0],[0.0,cx,-sx],[0.0,sx,cx]]
    return mat_mul(mat_mul(Rz, Ry), Rx)

def matrix_to_euler_zyx(R):
    # Returns [z, y, x]
    # For R = Rz(z) @ Ry(y) @ Rx(x)
    # y = asin(-R[2][0]) with sign conventions
    # z = atan2(R[1][0], R[0][0])
    # x = atan2(R[2][1], R[2][2])
    r20 = R[2][0]
    y = math.asin(-r20)
    cy = math.cos(y)
    if abs(cy) > 1e-8:
        z = math.atan2(R[1][0], R[0][0])
        x = math.atan2(R[2][1], R[2][2])
    else:
        # Gimbal lock fallback
        z = math.atan2(-R[0][1], R[1][1])
        x = 0.0
    return [z, y, x]

def quat_wxyz_to_matrix(q):
    w,x,y,z = q
    ww, xx, yy, zz = w*w, x*x, y*y, z*z
    wx, wy, wz = w*x, w*y, w*z
    xy, xz, yz = x*y, x*z, y*z
    return [
        [1 - 2*(yy+zz), 2*(xy - wz),   2*(xz + wy)],
        [2*(xy + wz),   1 - 2*(xx+zz), 2*(yz - wx)],
        [2*(xz - wy),   2*(yz + wx),   1 - 2*(xx+yy)],
    ]

def matrix_to_quat_wxyz(R):
    t = R[0][0] + R[1][1] + R[2][2]
    if t > 0.0:
        s = math.sqrt(t + 1.0) * 2.0
        w = 0.25 * s
        x = (R[2][1] - R[1][2]) / s
        y = (R[0][2] - R[2][0]) / s
        z = (R[1][0] - R[0][1]) / s
    else:
        if R[0][0] > R[1][1] and R[0][0] > R[2][2]:
            s = math.sqrt(1.0 + R[0][0] - R[1][1] - R[2][2]) * 2.0
            w = (R[2][1] - R[1][2]) / s
            x = 0.25 * s
            y = (R[0][1] + R[1][0]) / s
            z = (R[0][2] + R[2][0]) / s
        elif R[1][1] > R[2][2]:
            s = math.sqrt(1.0 + R[1][1] - R[0][0] - R[2][2]) * 2.0
            w = (R[0][2] - R[2][0]) / s
            x = (R[0][1] + R[1][0]) / s
            y = 0.25 * s
            z = (R[1][2] + R[2][1]) / s
        else:
            s = math.sqrt(1.0 + R[2][2] - R[0][0] - R[1][1]) * 2.0
            w = (R[1][0] - R[0][1]) / s
            x = (R[0][2] + R[2][0]) / s
            y = (R[1][2] + R[2][1]) / s
            z = 0.25 * s
    # Normalize
    n = math.sqrt(w*w + x*x + y*y + z*z)
    if n > 0:
        w,x,y,z = w/n, x/n, y/n, z/n
    return [w,x,y,z]

def log_map(R, eps=1e-12):
    # Returns rotation vector (omega): axis * angle
    tr = R[0][0] + R[1][1] + R[2][2]
    cos_theta = (tr - 1.0) * 0.5
    cos_theta = clamp(cos_theta, -1.0, 1.0)
    theta = math.acos(cos_theta)
    if theta < 1e-12:
        return [0.0, 0.0, 0.0]
    s = math.sin(theta)
    if abs(s) < eps:
        s = eps
    # Axis from off-diagonal skew part
    wx = (R[2][1] - R[1][2]) / (2.0 * s)
    wy = (R[0][2] - R[2][0]) / (2.0 * s)
    wz = (R[1][0] - R[0][1]) / (2.0 * s)
    return [wx*theta, wy*theta, wz*theta]

def parse_rotation_entry(entry):
    # Returns rotation matrix 3x3 or None if cannot parse
    # Accept keys: "matrix", "quaternion_wxyz" or "quaternion", "euler_zyx" or {"euler":[...], "axes":"zyx","intrinsic":true}, "axis"+ "angle"
    if isinstance(entry, dict):
        # matrix
        if "matrix" in entry:
            M = entry["matrix"]
            if (isinstance(M, list) and len(M) == 3 and all(isinstance(r, list) and len(r) == 3 for r in M)):
                try:
                    _ = float(M[0][0])
                    return [[float(M[i][j]) for j in range(3)] for i in range(3)]
                except Exception:
                    pass
        # quaternion
        for k in ("quaternion_wxyz", "quaternion"):
            if k in entry:
                q = entry[k]
                if isinstance(q, list) and len(q) == 4 and all(is_number(v) for v in q):
                    return quat_wxyz_to_matrix([float(v) for v in q])
        # euler
        if "euler_zyx" in entry:
            e = entry["euler_zyx"]
            if isinstance(e, list) and len(e) == 3 and all(is_number(v) for v in e):
                return euler_zyx_to_matrix([float(v) for v in e])
        if "euler" in entry and isinstance(entry["euler"], list) and len(entry["euler"]) == 3:
            axes = entry.get("axes", "zyx")
            intrinsic = bool(entry.get("intrinsic", True))
            if axes == "zyx" and intrinsic:
                e = entry["euler"]
                if all(is_number(v) for v in e):
                    return euler_zyx_to_matrix([float(v) for v in e])
        # axis-angle
        if "axis" in entry and "angle" in entry:
            axis = entry["axis"]
            angle = entry["angle"]
            if isinstance(axis, list) and len(axis) == 3 and all(is_number(v) for v in axis) and is_number(angle):
                ax, ay, az = float(axis[0]), float(axis[1]), float(axis[2])
                n = math.sqrt(ax*ax + ay*ay + az*az)
                if n > 0:
                    ax, ay, az = ax/n, ay/n, az/n
                return axis_angle_to_matrix([ax, ay, az], float(angle))
    return None

def get_expected_from_input(input_path):
    # Compute validity per index based on provided dataset
    data = read_json(input_path)
    valid = []
    invalid = []
    for idx, entry in enumerate(data):
        R = parse_rotation_entry(entry)
        if R is None:
            invalid.append(idx)
            continue
        ortho_ok, det_ok = is_orthonormal_det1(R, 1e-6, 1e-6)
        if ortho_ok and det_ok:
            valid.append(idx)
        else:
            invalid.append(idx)
    return valid, invalid

def parse_csv_min_decimals(s):
    # Return number of decimals if present
    s = s.strip()
    if '.' not in s:
        return 0
    dec = s.split('.', 1)[1]
    # allow scientific notation? For formatting requirement, enforce fixed decimals; if 'e' present, fail
    if 'e' in dec.lower():
        return 0
    # Only digits allowed after decimal (allow leading '-')
    m = re.match(r'^-?\d+\.(\d+)$', s)
    if not m:
        return 0
    return len(m.group(1))

def approx_equal(a, b, tol):
    return abs(a - b) <= tol

def vector_len(v):
    return math.sqrt(sum(x*x for x in v))

def check_axis_alignment(axis, tol=1e-3):
    # axis should align with ±z
    ax, ay, az = axis
    n = vector_len(axis)
    if n == 0:
        return False
    axn, ayn, azn = ax/n, ay/n, az/n
    return (abs(axn) <= tol and abs(ayn) <= tol and abs(abs(azn) - 1.0) <= tol)

def flatten_checks(checks):
    # ensure booleans
    for k, v in list(checks.items()):
        checks[k] = bool(v)
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    report_path = os.path.join(output_dir, "report.json")
    csv_path = os.path.join(output_dir, "rotvecs.csv")
    diag_path = os.path.join(output_dir, "diagnostics.txt")
    input_rotations_path = os.path.join(input_dir, "rotations.json")

    # Initialize all checks to False
    checks = {
        "report_exists": False,
        "report_json_valid": False,
        "conventions_ok": False,
        "valid_indices_match": False,
        "invalid_indices_match": False,
        "valid_count_match": False,
        "invalid_count_match": False,
        "mean_matrix_orthonormal_det": False,
        "mean_quaternion_unit": False,
        "mean_euler_yaw_ok": False,
        "mean_euler_pitch_roll_zero": False,
        "mean_rotvec_ok": False,
        "relative_matrix_orthonormal_det": False,
        "relative_euler_yaw_ok": False,
        "relative_quaternion_unit": False,
        "relative_axis_ok": False,
        "relative_angle_ok": False,
        "relative_rotvec_ok": False,
        "csv_exists": False,
        "csv_header_ok": False,
        "csv_row_count_ok": False,
        "csv_values_ok": False,
        "csv_decimals_ok": False,
        "diagnostics_exists": False,
        "diagnostics_has_keywords": False,
        "required_outputs_present": False,
    }

    # Required outputs gating
    required_exist = (os.path.isfile(report_path) and os.path.isfile(csv_path) and os.path.isfile(diag_path))
    checks["required_outputs_present"] = required_exist
    checks["report_exists"] = os.path.isfile(report_path)
    checks["csv_exists"] = os.path.isfile(csv_path)
    checks["diagnostics_exists"] = os.path.isfile(diag_path) and os.path.getsize(diag_path) > 0

    # Compute expected sets from input
    try:
        exp_valid, exp_invalid = get_expected_from_input(input_rotations_path)
    except Exception:
        # Fallback to known expected if input read fails
        exp_valid, exp_invalid = [0,1,2,3], [4]

    # Parse report.json
    report = None
    if checks["report_exists"]:
        try:
            report = read_json(report_path)
            if isinstance(report, dict):
                checks["report_json_valid"] = True
        except Exception:
            checks["report_json_valid"] = False

    # Validate report contents
    if report and checks["report_json_valid"]:
        # conventions
        conv = report.get("conventions")
        if isinstance(conv, dict):
            if conv.get("quaternion") == "wxyz" and conv.get("euler_axes") == "zyx" and bool(conv.get("euler_intrinsic", False)) is True:
                checks["conventions_ok"] = True

        # indices and counts
        v_idx = report.get("valid_indices")
        iv_idx = report.get("invalid_indices")
        v_count = report.get("valid_count")
        iv_count = report.get("invalid_count")
        if isinstance(v_idx, list) and all(isinstance(i, int) for i in v_idx):
            checks["valid_indices_match"] = (v_idx == exp_valid)
        if isinstance(iv_idx, list) and all(isinstance(i, int) for i in iv_idx):
            checks["invalid_indices_match"] = (iv_idx == exp_invalid)
        if isinstance(v_count, int):
            checks["valid_count_match"] = (v_count == len(exp_valid))
        if isinstance(iv_count, int):
            checks["invalid_count_match"] = (iv_count == len(exp_invalid))

        # mean checks
        mean = report.get("mean", {})
        if isinstance(mean, dict):
            # matrix
            M = mean.get("matrix")
            if isinstance(M, list) and len(M) == 3 and all(isinstance(r, list) and len(r) == 3 for r in M):
                ortho_ok, det_ok = is_orthonormal_det1(M, 1e-6, 1e-6)
                checks["mean_matrix_orthonormal_det"] = (ortho_ok and det_ok)
            # quaternion unit
            q = mean.get("quaternion_wxyz")
            if isinstance(q, list) and len(q) == 4 and all(is_number(x) for x in q):
                n = math.sqrt(sum(float(x)*float(x) for x in q))
                checks["mean_quaternion_unit"] = (abs(n - 1.0) <= 1e-3)
            # euler yaw
            eul = mean.get("euler_zyx")
            if isinstance(eul, list) and len(eul) == 3 and all(is_number(x) for x in eul):
                yaw, pitch, roll = float(eul[0]), float(eul[1]), float(eul[2])
                checks["mean_euler_yaw_ok"] = approx_equal(yaw, math.pi/8.0, 0.02)
                checks["mean_euler_pitch_roll_zero"] = (abs(pitch) <= 1e-3 and abs(roll) <= 1e-3)
            # rotvec
            rv = mean.get("rotvec")
            if isinstance(rv, list) and len(rv) == 3 and all(is_number(x) for x in rv):
                checks["mean_rotvec_ok"] = (abs(float(rv[0])) <= 1e-3 and abs(float(rv[1])) <= 1e-3 and approx_equal(float(rv[2]), math.pi/8.0, 0.02))

        # relative checks
        rel = report.get("relative_first_to_last_valid", {})
        if isinstance(rel, dict):
            # matrix
            RM = rel.get("matrix")
            if isinstance(RM, list) and len(RM) == 3 and all(isinstance(r, list) and len(r) == 3 for r in RM):
                ortho_ok, det_ok = is_orthonormal_det1(RM, 1e-6, 1e-6)
                checks["relative_matrix_orthonormal_det"] = (ortho_ok and det_ok)
            # euler yaw
            e2 = rel.get("euler_zyx")
            if isinstance(e2, list) and len(e2) == 3 and all(is_number(x) for x in e2):
                yaw2, pitch2, roll2 = float(e2[0]), float(e2[1]), float(e2[2])
                checks["relative_euler_yaw_ok"] = approx_equal(yaw2, math.pi/4.0, 0.02) and (abs(pitch2) <= 1e-3 and abs(roll2) <= 1e-3)
            # quaternion unit
            q2 = rel.get("quaternion_wxyz")
            if isinstance(q2, list) and len(q2) == 4 and all(is_number(x) for x in q2):
                n2 = math.sqrt(sum(float(x)*float(x) for x in q2))
                checks["relative_quaternion_unit"] = (abs(n2 - 1.0) <= 1e-3)
            # axis and angle
            ax = rel.get("axis")
            ang = rel.get("angle")
            if isinstance(ax, list) and len(ax) == 3 and all(is_number(x) for x in ax):
                checks["relative_axis_ok"] = check_axis_alignment([float(ax[0]), float(ax[1]), float(ax[2])], 1e-3)
            if is_number(ang):
                checks["relative_angle_ok"] = approx_equal(float(ang), math.pi/4.0, 0.02)
            # rotvec
            rv2 = rel.get("rotvec")
            if isinstance(rv2, list) and len(rv2) == 3 and all(is_number(x) for x in rv2):
                checks["relative_rotvec_ok"] = (abs(float(rv2[0])) <= 1e-3 and abs(float(rv2[1])) <= 1e-3 and approx_equal(float(rv2[2]), math.pi/4.0, 0.02))

    # CSV checks
    if checks["csv_exists"]:
        try:
            with open(csv_path, "r", newline="") as f:
                lines = f.read().splitlines()
            if lines:
                header = lines[0].strip()
                checks["csv_header_ok"] = (header == "index,rx,ry,rz")
                rows = []
                for ln in lines[1:]:
                    if not ln.strip():
                        continue
                    parts = ln.split(",")
                    if len(parts) != 4:
                        continue
                    idx_str, rx_str, ry_str, rz_str = [p.strip() for p in parts]
                    # parse index
                    try:
                        idx = int(idx_str)
                        rx = float(rx_str)
                        ry = float(ry_str)
                        rz = float(rz_str)
                        rows.append((idx, rx, ry, rz, rx_str, ry_str, rz_str))
                    except Exception:
                        continue
                # Expect exactly indices 0,1,2,3
                indices = [r[0] for r in rows]
                checks["csv_row_count_ok"] = (len(rows) == 4 and set(indices) == {0,1,2,3})
                # Values match expected within 1e-3
                expected = {
                    0: (0.0, 0.0, 0.0),
                    1: (0.0, 0.0, math.pi/2.0),
                    2: (0.0, 0.0, -math.pi/2.0),
                    3: (0.0, 0.0, math.pi/4.0),
                }
                vals_ok = True
                dec_ok = True
                for idx, rx, ry, rz, rx_s, ry_s, rz_s in rows:
                    if idx in expected:
                        ex = expected[idx]
                        if not (abs(rx - ex[0]) <= 1e-3 and abs(ry - ex[1]) <= 1e-3 and abs(rz - ex[2]) <= 1e-3):
                            vals_ok = False
                    else:
                        vals_ok = False
                    # at least 6 decimals
                    if parse_csv_min_decimals(rx_s) < 6 or parse_csv_min_decimals(ry_s) < 6 or parse_csv_min_decimals(rz_s) < 6:
                        dec_ok = False
                checks["csv_values_ok"] = vals_ok
                checks["csv_decimals_ok"] = dec_ok
        except Exception:
            pass

    # Diagnostics checks
    if checks["diagnostics_exists"]:
        try:
            with open(diag_path, "r") as f:
                txt = f.read()
            low = txt.lower()
            checks["diagnostics_has_keywords"] = ("orthogonality" in low and "determinant" in low and "tolerance" in low)
        except Exception:
            pass

    # Compute reward
    # If any required artifact is missing, reward must be exactly 0.0
    if not checks["required_outputs_present"]:
        reward = 0.0
    else:
        # Aggregate deterministic score: average of all check booleans except 'report_exists','csv_exists','diagnostics_exists','required_outputs_present' which are included too? They are concrete checks; keep them in average for simplicity.
        # However to avoid double-penalizing, include all checks equally.
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total if total > 0 else 0.0
        # Clamp
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Output JSON with "reward" first
    result = {"reward": float(reward)}
    result.update(flatten_checks(checks))
    print(json.dumps(result))

if __name__ == "__main__":
    main()