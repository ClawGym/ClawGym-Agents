# PSD2 / PSD3 working notes (EU/AT)

These are my internal notes to distill key items relevant to our product scope in Austria (EEA context).

- Strong Customer Authentication (SCA) under PSD2 generally requires two independent factors. Exemptions can apply based on "transaction risk analysis (TRA)" when predefined risk thresholds are met.
- Low-value contactless exemption: up to 50 EUR per transaction, with a cumulative limit (e.g., "150 EUR cumulative threshold") before SCA becomes mandatory.
- Surcharging is prohibited for consumer cards within the EEA; merchants cannot add extra fees for most consumer card transactions.
- Dedicated interfaces (APIs) for account access: proposals toward PSD3/PSR strengthen obligations for "reliable and well-performing" interfaces and reduce friction for third-party providers.
- Dispute handling and fraud reporting requirements are being clarified; expect more consistent "fraud data sharing" and stronger incident reporting.
- Austria’s FMA aligns with EBA guidelines; local supervisory expectations emphasize proper application of SCA exemptions and transparent customer communication.

Notes to self:
- Confirm applicability of TRA exemptions to specific in-app use cases with the acquiring bank.
- Watch for final PSD3/PSR text regarding API performance metrics and fallback mechanisms.