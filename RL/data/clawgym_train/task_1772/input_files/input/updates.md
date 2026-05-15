Notes for this period (Northstar Customer Portal Revamp) — rough cut, not cleaned up

milestones + status (some dates need client confirm)
- Dashboard redesign (web): finished 2026-04-15; stakeholder demo held 4/16, minor styling nits captured
- API Gateway integration: ~80% complete; auth passthrough OK; rate-limits TBD; target 4/22; 1-day slip caused by sandbox throttling last Tue
- SSO with Azure AD (B2C): blocked — requires tenant admin consent from client IT; request submitted 4/12; reminder sent 4/17; target now 4/24 if consent by 4/20
- Data migration trial (v0 dry run): completed 4/13; 2% records flagged with address schema mismatches (legacy “addr2” vs “address_line_2”); mapping fix drafted
- Email service vendor selection: pending decision; compared SendGrid vs Postmark; see quick summary below; need call by 4/22 for integration runway
- UAT readiness gate: planned 4/29; pre-UAT checklist at 70% (test cases drafted, fixtures pending)

quick wins
- No P1 defects in dashboard after redesign handoff; lighthouse perf +12 points desktop, +9 mobile
- Support center link now context-aware (role-based surfacing) — requested by CX

blockers / constraints
- External dependency: Azure tenant admin consent (client IT). This blocks SSO end-to-end tests and UAT entry for auth scenarios
- API Gateway sandbox throttling intermittently; mitigated by off-peak runs and local mocks for retries

budget + resources (rounded)
- Approved budget: $240,000
- Actuals to date: $132,400 (~55% of total) with ~58% time elapsed → roughly 3–5% under burn plan (good)
- Commitments (P.O./in-flight): $28,000 (mostly QA vendor and design polish)
- Forecast EAC (estimate at completion): $238,500 (assuming Postmark; add +$2–3k if SendGrid due to premium plan)
- Team capacity: 6 FTE equivalents this sprint (2 FE, 2 BE, 1 PM, 1 design fractional); QA vendor onboarding 2 testers starting 4/22

risk register (messy, clean up later)
1) Azure consent delay
   - Likelihood: Med→High if not approved by 4/20
   - Impact: High (UAT gate on auth scenarios)
   - Mitigation: Escalation path identified; offer screenshare with client IT; enable temporary test tenant if slip > 2 days
2) Data migration mismatches (2% rows)
   - Likelihood: Medium
   - Impact: Medium (data quality in profiles/address forms)
   - Mitigation: Apply mapping patch; second dry run 4/23; add validation script to flag orphan values before cutover
3) Email vendor SLA/throughput uncertainty
   - Likelihood: Medium
   - Impact: Low→Med (verification emails during peak sign-ups)
   - Mitigation: Choose vendor by 4/22; run load test on sandbox keys; keep fallback SMTP for non-critical flows

decisions needed (client)
- Email vendor: SendGrid vs Postmark by 4/22
  • Postmark: simpler API, strong deliverability for transactional, slightly cheaper at projected volume
  • SendGrid: broader features, may require more setup for templates/partials our team uses
- SSO scope: confirm whether guest accounts (non-customer contractors) must authenticate via Azure AD too; need by 4/21 for policy config
- Dashboard Design v2 microcopy: approve string set for tooltips and empty-state text by 4/20 (affects localization prep)
- UAT start date: confirm 4/29 still holds given consent dependency; backup date 5/01

other notes / assumptions
- If consent is granted by 4/20, we can finish SSO wiring + regression by 4/24 (2 working days)
- If consent slips past 4/22, we’ll proceed with UAT on non-auth features, then patch in auth cases as a sub-cycle
- No external API pricing changes observed this sprint

next period focus (tentative)
- Finish API Gateway (rate limits + 429 retry policy), target 4/22
- Complete SSO integration once consent lands; run end-to-end auth tests; finalize error copy for edge cases
- Data migration dry run #2 on 4/23 with mapping fix; produce comparison report
- Lock email vendor and integrate verification + password reset flows
- Prep UAT checklist to 100% and smoke tests for dashboard modules
- Draft release notes and client-facing change log (first pass)

tiny table: vendor comparison (at-a-glance)
- Deliverability: Postmark strong for transactional; SendGrid strong but needs tuning
- Template tooling: Postmark (simple), SendGrid (powerful but more setup)
- Cost @ 100k/mo emails: Postmark ~$120, SendGrid ~$150 (plan-dependent)
- Recommendation (team): Postmark unless client prefers SendGrid ecosystem alignment

open questions
- Is guest account SSO in scope now or v1.1?
- Are we localizing dashboard microcopy for v1 or post-UAT? (affects timing)
- Any legal review needed for updated Terms link in footer? (new privacy link added)