# Reliability scoring reference (do not run; read and apply formula):
# normalized_experience = min(years_experience / 20.0, 1.0)
# cert_points = 1.0 if 'InterNACHI' in certifications else 0.7 if 'ASHI' in certifications else 0.0
# normalized_complaints = min(complaint_count / 5.0, 1.0)
# normalized_price = min(base_price / 500.0, 1.0)
# reliability = (weights['experience'] * normalized_experience)
#             + (weights['certifications'] * cert_points)
#             - (weights['complaints'] * normalized_complaints)
#             - (weights['price'] * normalized_price)
# Weights must be read from config/preferences.yaml.
# Note: If multiple certifications are present, cert_points should reflect the best applicable value (e.g., InterNACHI takes precedence).
