"""
Analysis notes for social content:
- Use units 'ppb' for lead results in this dataset.
- Round all reported statistics to 1 decimal place for public-facing posts.
- Include the following disclaimer at the end of the thread.
- Keep tone: concise, non-alarmist, actionable.
"""

UNITS = "ppb"
ROUNDING_DECIMALS = 1
DISCLAIMER = (
    "These are simulated demonstration data. The 15 ppb action level is a regulatory trigger, "
    "not a health-based threshold. Always interpret results in local context."
)
THREAD_TONE = "concise, non-alarmist, actionable"
RECOMMENDED_HASHTAGS = ["#Lead", "#WaterQuality", "#PublicHealth"]
