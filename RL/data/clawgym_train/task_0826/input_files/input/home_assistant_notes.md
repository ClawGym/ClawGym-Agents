Goals
- Surface current relocation status (phase, target date, key upcoming deadlines) in Home Assistant.
- Provide a service that returns data (not fire-and-forget), e.g., expat_helper.get_status, to retrieve JSON-like status.
- Expose an authenticated HTTP endpoint returning JSON configuration/status for dashboards.
- Store a small status snapshot locally using public storage helpers appropriate for small data (Store) so state persists across restarts.

Constraints & Requirements
- Use only public Home Assistant APIs.
- Do not reference underscore-prefixed or private/internal APIs (e.g., no hass.data['_something']).
- Implement services with supports_response=SupportsResponse.ONLY so they can return data (HA 2023.7+).
- HTTP view must require authentication (requires_auth=True).
- Minimal config_flow to set basic options (e.g., reminders_enabled, check_in_frequency).
- Avoid external services and secrets; store only non-sensitive relocation data.

Service: expat_helper.get_status
- Input: none
- Output: A dict with keys like:
  - phase: one of research | planning | pre-move | moving | settling
  - target_date: YYYY-MM
  - next_deadlines: list of {name, date}
  - last_updated: ISO timestamp
- Should return data when called with ?return_response flag.

HTTP Endpoint
- Path: /api/expat_helper/config
- Auth: required
- Response: JSON with config and current status snapshot.

Storage
- Use homeassistant.helpers.storage.Store to persist a dict:
  {
    "phase": "planning",
    "target_date": "2026-10",
    "next_deadlines": [...],
    "last_updated": "ISO8601"
  }
- Keep it small; no sensitive identifiers.

Testing Checklist (for later)
- Service call returns data (non-empty) when called with return_response.
- HTTP endpoint requires auth and returns JSON.
- Storage persists status across restart (Store helper).
- No underscore-prefixed internal API usage found.
- Config flow creates an entry and options are saved.