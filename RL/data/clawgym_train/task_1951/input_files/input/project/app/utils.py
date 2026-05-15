import os
import json

# TODO: consolidate env parsing

def get_env(name, default=None):
    value = os.getenv(name)
    return value if value is not None else default

def to_json(data):
    return json.dumps(data, separators=(",", ":"), sort_keys=True)