# Labeling logic used by our site to classify shows for the tour archive.
# Keep these rules in sync with any data analysis so the public tags match internal logic.

diy_keywords = [
    "community center",
    "house show",
    "warehouse",
    "co-op",
    "all-ages",
    "all ages",
    "zine library",
    "fundraiser",
    "collective",
]

corporate_keywords = [
    "sponsored",
    "brand stage",
    "arena",
    "ticketmaster",
    "corporate festival",
    "corporate",
]

DIY_TICKETING = {"at-door", "sliding-scale"}
CORP_TICKETING = {"ticketmaster"}


def categorize_show(notes: str, tickets_platform: str) -> str:
    """
    Classify a show as 'DIY', 'Corporate', or 'Mixed'.
    Rules:
      - If notes contain any diy_keywords OR tickets_platform in DIY_TICKETING -> DIY bias.
      - If notes contain any corporate_keywords OR tickets_platform in CORP_TICKETING -> Corporate bias.
      - If both biases present, return 'Mixed'.
      - If only DIY bias present, return 'DIY'. If only Corporate bias present, return 'Corporate'.
      - If neither present, return 'Mixed'.
    Matching is case-insensitive substring search.
    """
    n = (notes or "").lower()
    t = (tickets_platform or "").strip().lower()

    diy_bias = any(k in n for k in diy_keywords) or (t in DIY_TICKETING)
    corp_bias = any(k in n for k in corporate_keywords) or (t in CORP_TICKETING)

    if diy_bias and corp_bias:
        return "Mixed"
    if diy_bias:
        return "DIY"
    if corp_bias:
        return "Corporate"
    return "Mixed"
