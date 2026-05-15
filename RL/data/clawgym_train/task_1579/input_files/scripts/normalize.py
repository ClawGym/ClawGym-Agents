EARLY_PERIOD = (1900, 1939)  # inclusive

ALLOWED_COUNTRIES = [
    "United States",
    "United Kingdom",
    "Germany",
    "Austria",
    "Spain",
    "Belgium",
    "France",
    "Switzerland"
]

COUNTRY_SYNONYMS = {
    "USA": "United States",
    "U.S.A.": "United States",
    "United States of America": "United States",
    "America": "United States",
    "UK": "United Kingdom",
    "U.K.": "United Kingdom",
    "England": "United Kingdom",
    "Scotland": "United Kingdom",
    "Wales": "United Kingdom",
    "Great Britain": "United Kingdom",
    "Deutschland": "Germany",
    "German Empire": "Germany",
    "Österreich": "Austria",
    "Austria-Hungary": "Austria",
    "España": "Spain",
    "Catalonia": "Spain",
    "Belgique": "Belgium",
    "België": "Belgium",
    "République française": "France",
    "Suisse": "Switzerland",
    "Schweiz": "Switzerland"
}

def normalize_country(name: str) -> str:
    if not name:
        return ""
    n = name.strip()
    return COUNTRY_SYNONYMS.get(n, n)

def in_early_period(year: int) -> bool:
    try:
        y = int(year)
    except Exception:
        return False
    return EARLY_PERIOD[0] <= y <= EARLY_PERIOD[1]
