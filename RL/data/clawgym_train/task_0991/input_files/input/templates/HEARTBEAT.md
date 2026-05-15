# Heartbeat Instructions

Every 30 minutes, perform these checks:

## 1. Active Sessions
- Check today's daily note for any open coding sessions or tasks
- If a session should be running but isn't: check if it died and restart it
- If a session finished: update daily note and notify Kalin
- Do NOT report if everything is normal

## 2. Communication
- Check for unread messages in authenticated channels that haven't been addressed
- Handle anything urgent that was missed

## 3. Proactive Monitoring
- Is anything from today's plan stalled or needs attention?
- Are there any scheduled tasks coming up in the next 30 minutes?
- Are any deployed services down or erroring?

## Rules
- If nothing needs attention: reply HEARTBEAT_OK (suppresses notification)
- NEVER start new major work from a heartbeat — only monitor and maintain
- NEVER re-run tasks from old conversations based on heartbeat context
- Keep heartbeat actions minimal: check, report, move on