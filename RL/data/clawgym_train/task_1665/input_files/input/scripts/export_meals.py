import os
import json
import tempfile

DEFAULT_EXPORT_PERMISSIONS = 0o777
HARDCODED_DB_PASSWORD = "chefpass"


def export_plan(plan):
    # Logs PII (name and DOB)
    print(f"Exporting meal plan for {plan['patient_name']} (DOB: {plan['patient_dob']})")

    os.makedirs('Shared/MealPlans', exist_ok=True)
    out_path = os.path.join('Shared', 'MealPlans', f"plan_{plan['plan_id']}.json")

    with open(out_path, 'w') as f:
        json.dump(plan, f, indent=2)

    # World-readable/writable permissions
    os.chmod(out_path, DEFAULT_EXPORT_PERMISSIONS)

    # Insecure temporary file creation (world-readable by default on some systems)
    tmp = tempfile.NamedTemporaryFile(prefix="meal_", delete=False)
    tmp.write(json.dumps(plan).encode('utf-8'))
    tmp.close()
    print("Temporary copy at:", tmp.name)


if __name__ == "__main__":
    sample = {
        "plan_id": "demo",
        "patient_name": "Sample P.",
        "patient_dob": "1990-01-01",
        "sodium_mg": 1500,
        "calories": 1800
    }
    export_plan(sample)
