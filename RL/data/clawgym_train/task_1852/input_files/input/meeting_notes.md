# Offline Mode Alignment Meeting — Notes

Date: 2026-04-10
Facilitator: PM
Attendees: PM, Eng Lead, iOS Lead, Android Lead, Design, QA

## Context
- Users frequently report inability to create and edit notes without connectivity.
- Business goals tie this MVP to retention and mobile WAU improvements in H2 2026.
- We need a pragmatic MVP by end of Q2 to validate value and de-risk sync conflicts.

## Decisions
- MVP scope: offline create/edit text notes, local cache, conflict resolution: "last-writer-wins" with manual merge.
- Platforms: iOS and Android only for MVP.
- Storage: use SQLite with encryption.

## Open Questions
- How to handle large attachments offline?
- What is the acceptable sync delay threshold after reconnection?
- Do we block sharing for offline-created notes until first sync?

## Notes
- Design will deliver minimal offline UI indicators (status chip, conflict banner).
- QA to define test matrix for airplane mode, tunnel, and crash-recovery scenarios.
- Security sign-off required for key management before beta.