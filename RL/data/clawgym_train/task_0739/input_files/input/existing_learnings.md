# Learnings Log

Captured learnings, corrections, and discoveries. Review before major tasks.

---

## [LRN-20260101-001] best_practice

**Logged**: 2026-01-01T09:00:00Z
**Priority**: high
**Status**: pending
**Area**: backend

### Summary
Validate request payloads at API boundaries to prevent 500s

### Details
During December and January we saw multiple 500 errors caused by missing or wrongly-typed fields reaching service handlers. The lack of input schema validation allowed invalid data through, leading to crashes deeper in the stack.

### Suggested Action
Introduce strict input validation on all public endpoints (e.g., Zod for TypeScript services). Return 400 with a helpful error message when validation fails. Add tests for edge cases.

### Metadata
- Source: error
- Related Files: services/api/routes/users.ts
- Tags: validation, api, reliability
- Pattern-Key: harden.input_validation
- Recurrence-Count: 2
- First-Seen: 2025-12-20
- Last-Seen: 2026-04-01

---