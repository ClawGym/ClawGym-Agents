SCHEMA = {
    "incident": {
        "date": "YYYY-MM-DD",
        "time": "HH:MM or descriptive",
        "location": "string",
        "dog_name": "string",
        "neighbor_name": "string",
        "owner_name": "string"
    },
    "damages": [
        {"provider": "string", "date": "YYYY-MM-DD", "description": "string", "amount_usd": "number as float"}
    ],
    "damages_total": "number as float",
    "laws": {
        "city": "string",
        "code_section": "string",
        "requirement": "string",
        "penalty": "string"
    },
    "consistency_checks": [
        {"field": "string", "sources": ["path1", "path2"], "status": "ok|mismatch|missing", "details": "string"}
    ],
    "sources": [
        "relative file paths used to build this summary"
    ]
}
