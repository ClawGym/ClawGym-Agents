"""Scheduling policy for Sunset Ridge Apiary marketing content.

- Honor DAYS_OFF (no posts on these weekdays).
- Do not publish items that include any BANNED_KEYWORDS.
- Enforce MAX_POSTS_PER_DAY per channel.
"""

DAYS_OFF = ["Sunday"]

MAX_POSTS_PER_DAY = {
    "blog": 1,
    "instagram": 1,
    "facebook": 1,
    "newsletter": 1,
}

BANNED_KEYWORDS = [
    "giveaway",
    "contest",
]
