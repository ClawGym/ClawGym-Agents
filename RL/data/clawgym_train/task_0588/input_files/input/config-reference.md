AEGIS Configuration Reference (Dubai, UAE task)

Config file location at runtime: ~/.openclaw/aegis-config.json

Minimal configuration fields required for this task:
- location.country: ISO 3166-1 alpha-2 (e.g., "AE")
- location.city: city name (e.g., "Dubai")
- location.timezone: IANA timezone (e.g., "Asia/Dubai")
- language: BCP 47 language code (e.g., "en")
- alerts.critical_instant: boolean
- briefings.enabled: boolean
- briefings.morning: "HH:MM" local time
- briefings.evening: "HH:MM" local time
- scan_interval_minutes: integer (recommended 15)
- llm.enabled: boolean (false for this task)
- llm.provider: "none" (or omitted when llm.enabled is false)
- filters.require_location_match: boolean
- tone: "factual" | "detailed" | "minimal"
- include_preparedness: boolean
- api_keys.newsapi: null (no API key)
- sources.disabled: array (can be empty)

Full schema example
{
  "version": "1.0.0",

  "location": {
    "country": "AE",
    "city": "Dubai",
    "timezone": "Asia/Dubai"
  },

  "language": "en",

  "alerts": {
    "critical_instant": true,
    "high_batch_minutes": 30,
    "medium_digest_hours": 6,
    "quiet_hours": {
      "enabled": false,
      "start": "23:00",
      "end": "07:00"
    }
  },

  "briefings": {
    "enabled": true,
    "morning": "08:00",
    "evening": "20:00"
  },

  "scan_interval_minutes": 15,

  "llm": {
    "enabled": false,
    "provider": "none"
  },

  "api_keys": {
    "newsapi": null
  },

  "sources": {
    "disabled": [],
    "custom": []
  },

  "filters": {
    "min_tier": 0,
    "require_location_match": true
  },

  "tone": "factual",
  "include_preparedness": true
}

Notes
- When llm.enabled is false, the system relies on regex and negative pattern filters; semantic checks are disabled.
- Setting filters.require_location_match to true reduces noise by requiring explicit mention of the user’s country/city.
- All times in briefings are interpreted in the configured timezone.
- api_keys.newsapi must be null (no non-empty key) for this task.