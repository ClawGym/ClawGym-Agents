import json
import os
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # Shortlist checks
        "shortlist_exists": False,
        "shortlist_json_valid": False,
        "shortlist_length_3": False,
        "shortlist_sorted_desc": False,
        "shortlist_items_match": False,
        "shortlist_ok": False,
        # Dealers CSV checks
        "dealers_exists": False,
        "dealers_header_ok": False,
        "dealers_rows_ok": False,
        "dealers_sorted_ok": False,
        "dealers_ok": False,
        # Summary checks
        "summary_exists": False,
        "summary_non_empty": False,
        "summary_contains_db12": False,
        "summary_contains_db12_volante": False,
        "summary_contains_dbx707": False,
        "summary_ok": False,
    }

    # Helper functions
    def close(a, b, tol=1e-6):
        try:
            return abs(float(a) - float(b)) <= tol
        except Exception:
            return False

    def is_rounded_to_6(x):
        try:
            x = float(x)
        except Exception:
            return False
        return abs(x - round(x, 6)) < 1e-9

    # === Check shortlist.json ===
    shortlist_path = os.path.join(output_dir, "shortlist.json")
    shortlist_data = None
    if os.path.isfile(shortlist_path):
        checks["shortlist_exists"] = True
        try:
            with open(shortlist_path, "r", encoding="utf-8") as f:
                shortlist_data = json.load(f)
            checks["shortlist_json_valid"] = isinstance(shortlist_data, list)
        except Exception:
            checks["shortlist_json_valid"] = False

    expected_items = [
        {
            "model": "DB12",
            "variant": "Coupe",
            "year": 2025,
            "msrp": 245000,
            "horsepower": 671,
            "combined_mpg": 20,
            "zero_to_60": 3.5,
            "seats": 4,
            "body_style": "coupe",
            "hp_per_kusd": 2.738776,
            "score": 4.943265,
        },
        {
            "model": "DB12",
            "variant": "Volante",
            "year": 2025,
            "msrp": 265000,
            "horsepower": 671,
            "combined_mpg": 19,
            "zero_to_60": 3.6,
            "seats": 4,
            "body_style": "convertible",
            "hp_per_kusd": 2.532075,
            "score": 4.599245,
        },
        {
            "model": "DBX707",
            # Variant for DBX707 not strictly specified in expected; require presence only
            "year": 2024,
            "msrp": 245000,
            "horsepower": 697,
            "combined_mpg": 17,
            "zero_to_60": 3.1,
            "seats": 5,
            "body_style": "suv",
            "hp_per_kusd": 2.844898,
            "score": 4.486939,
        },
    ]

    if checks["shortlist_json_valid"]:
        # Length check
        if isinstance(shortlist_data, list) and len(shortlist_data) == 3:
            checks["shortlist_length_3"] = True

            # Sorted by descending score check
            try:
                scores = [item.get("score") for item in shortlist_data]
                if all(isinstance(s, (int, float)) for s in scores):
                    sorted_desc = all(scores[i] >= scores[i+1] - 1e-12 for i in range(len(scores)-1))
                    checks["shortlist_sorted_desc"] = sorted_desc
            except Exception:
                checks["shortlist_sorted_desc"] = False

            # Content match
            required_keys = [
                "model", "variant", "year", "msrp", "horsepower",
                "combined_mpg", "zero_to_60", "seats", "body_style",
                "hp_per_kusd", "score"
            ]
            items_match = True

            for idx, (got, exp) in enumerate(zip(shortlist_data, expected_items)):
                # Check keys existence
                if not isinstance(got, dict):
                    items_match = False
                    break
                for k in required_keys:
                    if k not in got:
                        items_match = False
                        break
                if not items_match:
                    break

                # Model must match exactly
                if str(got.get("model")) != exp["model"]:
                    items_match = False
                    break

                # Variant: strict for DB12 entries; for DBX707 require string presence
                if idx in (0, 1):
                    if str(got.get("variant")) != exp["variant"]:
                        items_match = False
                        break
                else:
                    # ensure variant is a string (can be any non-empty or empty OK, require string)
                    if not isinstance(got.get("variant"), str):
                        items_match = False
                        break

                # Year (allow int or float equal to int)
                gy = got.get("year")
                if not (isinstance(gy, int) or (isinstance(gy, float) and gy.is_integer())) or int(gy) != exp["year"]:
                    items_match = False
                    break

                # Body style exact match
                if str(got.get("body_style")) != exp["body_style"]:
                    items_match = False
                    break

                # Seats integer check
                gs = got.get("seats")
                if not (isinstance(gs, int) or (isinstance(gs, float) and gs.is_integer())) or int(gs) != exp["seats"]:
                    items_match = False
                    break

                # Numeric fields with tolerance
                num_fields = ["msrp", "horsepower", "combined_mpg", "zero_to_60", "hp_per_kusd", "score"]
                for nf in num_fields:
                    gv = got.get(nf)
                    if not isinstance(gv, (int, float)):
                        items_match = False
                        break
                    if not close(float(gv), float(exp[nf]), tol=1e-6):
                        items_match = False
                        break
                    # Rounding checks for hp_per_kusd and score to 6 decimals
                    if nf in ("hp_per_kusd", "score"):
                        if not is_rounded_to_6(gv):
                            items_match = False
                            break
                if not items_match:
                    break

            checks["shortlist_items_match"] = items_match

        # Aggregate shortlist_ok
        checks["shortlist_ok"] = (
            checks["shortlist_exists"]
            and checks["shortlist_json_valid"]
            and checks["shortlist_length_3"]
            and checks["shortlist_sorted_desc"]
            and checks["shortlist_items_match"]
        )

    # === Check dealers_by_state.csv ===
    dealers_path = os.path.join(output_dir, "dealers_by_state.csv")
    if os.path.isfile(dealers_path):
        checks["dealers_exists"] = True
        try:
            with open(dealers_path, "r", encoding="utf-8") as f:
                lines = [ln.rstrip("\n\r") for ln in f.readlines()]
        except Exception:
            lines = []

        if lines:
            header = lines[0].strip()
            checks["dealers_header_ok"] = (header == "state,dealer_name")

            rows = lines[1:]
            # Normalize fields by stripping spaces around values
            norm_rows = []
            for r in rows:
                # allow one comma split, then strip spaces around parts
                parts = r.split(",", 1)
                if len(parts) != 2:
                    continue
                state = parts[0].strip()
                dealer = parts[1].strip()
                norm_rows.append((state, dealer))

            expected_rows = [
                ("CA", "Aston Martin Beverly Hills"),
                ("CA", "Aston Martin Newport Beach"),
                ("TX", "Aston Martin Dallas"),
                ("TX", "Aston Martin Houston"),
            ]

            checks["dealers_rows_ok"] = (norm_rows == expected_rows)

            # Sorted check: by state then dealer_name ascending
            sorted_rows = sorted(norm_rows, key=lambda x: (x[0], x[1]))
            checks["dealers_sorted_ok"] = (norm_rows == sorted_rows)

            checks["dealers_ok"] = checks["dealers_exists"] and checks["dealers_header_ok"] and checks["dealers_rows_ok"] and checks["dealers_sorted_ok"]

    # === Check summary.md ===
    summary_path = os.path.join(output_dir, "summary.md")
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            content = ""

        if isinstance(content, str) and len(content.strip()) > 0:
            checks["summary_non_empty"] = True
            low = content.lower()
            checks["summary_contains_db12"] = ("db12" in low)  # allows "DB12 Coupe" mentions
            checks["summary_contains_db12_volante"] = ("db12 volante" in low)
            checks["summary_contains_dbx707"] = ("dbx707" in low)

            checks["summary_ok"] = (
                checks["summary_exists"]
                and checks["summary_non_empty"]
                and checks["summary_contains_db12"]
                and checks["summary_contains_db12_volante"]
                and checks["summary_contains_dbx707"]
            )

    # Compute reward: equal weight per artifact; no credit if artifact missing/invalid
    total = 0
    total += 1 if checks["shortlist_ok"] else 0
    total += 1 if checks["dealers_ok"] else 0
    total += 1 if checks["summary_ok"] else 0
    reward = total / 3.0

    # Build final JSON with "reward" first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()