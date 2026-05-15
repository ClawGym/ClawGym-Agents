# Reference only: cross-check this against monitor.yaml; use monitor.yaml as the source of truth.
KEYWORDS = {
    "Nassau & Paradise Island": ["cruise", "museum", "food tour"],
    "Exuma": ["swimming pigs", "snorkeling", "boat tour"],
    "Andros": ["blue hole", "bonefishing", "eco-tour"],
    # Note: 'pink sands beach' differs from monitor.yaml's 'pink sand beach'
    "Eleuthera": ["pink sands beach", "surfing", "boutique hotel"],
    "Abaco": ["boating", "sailing", "national park"],
    # Note: 'wreck' differs from monitor.yaml's 'shipwreck'
    "Bimini": ["dolphin", "shark", "wreck"],
}

if __name__ == "__main__":
    for island, topics in KEYWORDS.items():
        print(f"{island}: {', '.join(topics)}")
