# Reward and fee configuration for card
SURCHARGE_RATE = 0.01  # 1% surcharge on International category
CASHBACK_RATES = {
    "ScienceMag": 0.02,           # 2% cashback
    "StringTheoryBooks": 0.05,    # 5% cashback
    "PhysicsWorld": 0.03          # 3% cashback
}
APPLY_CASHBACK_TO_SCIENCE_ONLY = True
# When True, apply cashback only to transactions classified as 'science' by category_rules.yaml
