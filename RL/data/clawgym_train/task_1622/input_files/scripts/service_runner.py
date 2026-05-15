import yaml

def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

# The runner expects specific keys in the YAML file.
def expected_keys():
    return {
        "watering": ["enabled", "start_time", "duration_minutes"],
        "weather_logger": ["enabled", "schedule_time"]
    }

# Extracts the keys the runner actually uses at runtime.
def get_service_settings(cfg):
    services = cfg.get("services", {})
    watering = services.get("watering", {})
    weather = services.get("weather_logger", {})

    watering_enabled = bool(watering.get("enabled", False))  # expects 'enabled'
    weather_enabled = bool(weather.get("enabled", False))

    start_time = watering.get("start_time")  # daily HH:MM
    schedule_time = weather.get("schedule_time")  # daily HH:MM

    return {
        "watering": {"enabled": watering_enabled, "start_time": start_time},
        "weather_logger": {"enabled": weather_enabled, "schedule_time": schedule_time}
    }

if __name__ == "__main__":
    cfg = load_config("input/garden_config.yaml")
    print(get_service_settings(cfg))
