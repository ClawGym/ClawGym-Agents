def normalize_country(name: str) -> str:
    # Utility potentially useful but not wired into analyze_trade.py
    return (name or '').strip().title()
