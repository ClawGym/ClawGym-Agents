# Utility for normalising team names in North London derby data.

TEAM_ALIASES = {
    "Spurs": "Tottenham Hotspur",
    "Tottenham": "Tottenham Hotspur",
    "Tottenham Hotspur": "Tottenham Hotspur",
    "Gunners": "Arsenal",
    "Arsenal": "Arsenal"
}

def normalize_team(name: str) -> str:
    """Return canonical team name using TEAM_ALIASES; defaults to input if unknown."""
    return TEAM_ALIASES.get(name.strip(), name.strip())

if __name__ == "__main__":
    # Example usage
    for n in ["Spurs", "Tottenham", "Arsenal", "Gunners", "Unknown"]:
        print(n, "->", normalize_team(n))
