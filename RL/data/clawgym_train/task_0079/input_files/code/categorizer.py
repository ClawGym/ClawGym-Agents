# Volunteer categorizer script (for inspection only)
# Note: Do not run this; use it only to verify config path and default mapping against config/config.yaml

CONFIG_PATH = "config/settings.yaml"  # intended to point to the YAML config

DEFAULT_VENDOR_MAP = {
    "Bright Books Online": "Books",
    "Town Print Shop": "Print Services",
    "Community Centre": "Room Rental",
}

def categorize_vendor(vendor: str, mapping: dict | None = None) -> str:
    mapping = mapping or DEFAULT_VENDOR_MAP
    return mapping.get(vendor, "Uncategorized")

if __name__ == "__main__":
    # Placeholder for future CLI; left intentionally minimal by the volunteer
    print("Categorizer ready.")
