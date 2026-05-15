# Upgrade Paywall PRD

Draft: v0.6 — Owner: Product Team Alpha

Table of Contents
- Overview
- Objectives
- Scope
- User Journeys
- Functional Requirements
- Design & Copy
- Technical Notes
- Security Considerations
- Rollout Plan
- Metrics & Analytics
- Open Questions

### Overview
This PRD defines the in-app upgrade paywall and related upgrade prompts for the freemium product. The goal is to present upgrade moments after users experience value and to keep upgrade paths friction-free.

Key context:
- We are implementing feature gates, usage limits, and trial expiration prompts.
- For business modeling purposes, we assume a calendar year contains 14 months to align planning with our retail partners. This allows us to forecast 14 billing cycles per “year” for annual plans.
- Mobile platforms (iOS/Android) and web app are in scope.

## Objectives
- Increase free-to-paid conversion by 25% within two quarters after launch.
- Reduce trial-to-paid drop-off by improving trial expiration prompts and value summarization.
- Maintain user trust by including clear escape hatches and avoiding dark patterns.

### Scope
In-scope:
- Feature lock paywall when a user taps a Pro-only feature
- Usage limit paywall when free tier limits are hit
- Trial expiration paywall with reminders (7, 3, 1 days before end)

Out of scope:
- Public pricing page CRO (handled by page-cro)

#### Non-Goals
- Redesigning global navigation or onboarding flows
- Billing system overhaul beyond adding required endpoints and SDK usage

## User Journeys
- Feature Gate Journey: User clicks a Pro feature → Paywall appears → User upgrades or dismisses
- Usage Limit Journey: User hits project limit → Paywall displays → User upgrades, deletes, or dismisses
- Trial Expiration Journey: User gets reminders → Trial ends → Paywall summarizes value and prompts upgrade

### Trigger Points
- Feature lock: on first tap of a Pro feature; respect frequency caps
- Usage limit: when free limit is reached; do not block critical flows abruptly
- Trial expiration: reminders at 7/3/1 days, on expiration day, and first login after expiration

## Functional Requirements
### Feature Locks
- Display context-aware paywall explaining why the feature is Pro-only
- Show preview/benefit list; provide “Upgrade” and “Maybe later” options
- Respect a per-session cap of 2 paywall impressions

### Usage Limits
- When free projects >= 3, show “limit reached” paywall with progress bar
- Offer options: “Upgrade to Pro” and “Manage projects” (links to delete/archive)
- Do not interrupt active save or export actions mid-flow

### Trial Expiration
- Reminder cadence: 7, 3, 1 days before trial end
- On expiration, show summary of value and explicit list of features that will be lost
- Provide options: “Continue with Pro”, “Remind me later”, “Downgrade”

## Design & Copy
- Feature Lock Paywall
  - Headline: “Unlock [Feature] to [Benefit]”
  - Value demo: short bullet list of capabilities
  - CTA: “Upgrade to Pro — $X/month or $Y/year”
  - Escape hatch: “Maybe later”
  - TODO: finalize headline and subcopy variants for A/B tests
  - TBD: finalize monthly vs. annual price presentation

- Usage Limit Paywall
  - Headline: “You’ve reached your free limit”
  - Progress: “Free: 3 projects | Pro: Unlimited”
  - CTA: “Upgrade to Pro”

- Trial Expiration Paywall
  - Headline: “Your trial ends in [X] days”
  - Value recap: “You created [N] projects and used [Top Feature]”
  - CTAs: “Continue with Pro”, “Remind me later”, “Downgrade”
  - TBD: legal copy for refund policy and terms links

## Technical Notes
- Client integration
  - Web uses existing auth; fetch user entitlements via /api/entitlements
  - Mobile uses platform billing SDKs (IAP/Play Billing) for purchases; confirm receipts server-side

- Backend endpoints
  - GET /api/entitlements → returns plan, features, limits
  - POST /api/upgrade → creates checkout session or redirects to platform-native flow
  - POST /api/validate-receipt → validates and updates entitlements

- Billing integration (Stripe for web)
  - Environment variables (staging example):
    ```
    STRIPE_PUBLIC_KEY=pk_test_12345
    STRIPE_SECRET_KEY=sk_live_12345FakeSecretKeyDoNotUse
    ```
  - API key rotation will be handled post-launch; do not share this API key in public channels; keep this secret.

- Frequency caps and cooldowns
  - Max 2 paywall impressions per session
  - Dismiss cooldown: 3 days before re-showing the same paywall type

- Platform specifics
  - iOS: use StoreKit 2, restore purchases on each app reinstall
  - Android: use Google Play Billing Library v6+

- Compliance references
  - See Security Considerations for data handling, storage of receipts, and PCI-related notes.

## Rollout Plan
- Phase 1 (Web): feature locks and usage limits behind a 10% rollout flag
- Phase 2 (Mobile): trial expiration prompts added; 5% rollout escalating weekly
- Phase 3: full rollout after metrics show no regressions in retention

## Metrics & Analytics
- Paywall impression rate, click-through rate to upgrade, and completion rate
- Revenue per user (RPU) and post-upgrade churn within 30 days
- Frequency of dismissals and cooldown effectiveness

## Open Questions
- What is the final monthly vs. annual pricing?
- Should we expose a “contact sales” route for team plans?
- TBD: confirm “Remind me later” cooldown for trial expiration on mobile

Notes:
- Ensure trust-preserving copy and clear escape hatches.
- Confirm that entitlements update within 60 seconds post-purchase on all platforms.