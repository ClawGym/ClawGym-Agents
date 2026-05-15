# Onboarding — Progressive Profiling

Progressive profiling is the practice of collecting additional user attributes over time, sequenced to moments of value, instead of front-loading every question at signup.

Principles
- Start with the smallest viable form to create an account and unlock a first value moment.
- Defer non-essential questions until the user reaches a clear value moment.
- Ask at most one optional question per step; never block activation on optional data.
- Use progressive disclosure to reveal fields only when they are relevant to the current task.
- Explain why each optional field is requested and how it will be used.
- Respect user intent signals: if a user skips once, back off and retry later with better timing.

Minimum viable signup (Step 0)
- Start with the minimum to create an account: email (or phone) and password (or SSO).
- Support social/SSO to reduce friction and autofill verified identifiers.
- Avoid marketing questions at signup; keep the focus on account creation and first run.

Early activation (Step 1)
- Trigger: first login or first project created.
- Ask one helpful, low-friction question tied to immediate value (e.g., role, use case).
- Use clear microcopy like “This helps tailor your dashboard.”

Mid activation (Step 2)
- Trigger: first success event (e.g., first file uploaded, first report generated).
- Present contextual, skippable prompts (e.g., team size, industry) in-line or as a non-modal banner.
- Persist a profile_completeness score to drive later prompts.

Late activation (Step 3)
- Trigger: repeat usage (N sessions or features unlocked).
- Offer richer questions that unlock personalization (e.g., budget range, integration preferences).
- Offer immediate benefit for providing data (e.g., recommended templates, saved defaults).

UI patterns
- Inline micro-forms that do not block core flows.
- Small, focused modals with a single optional question and a Skip action.
- Non-intrusive banners or side panels with one-click responses (chips, toggles).
- Chip-pickers for categorical fields; avoid open text if a taxonomy exists.
- Autocomplete and sensible defaults to minimize typing.
- Save-on-blur and optimistic persistence to avoid losing progress.

Copy guidelines
- Lead with value: “Help us personalize your setup.”
- Be transparent: “We use your role to recommend the right templates.”
- Mark optional fields clearly and keep the Skip control equally prominent.
- Avoid guilt phrasing; honor user agency.

Data model
- profile_completeness: integer 0–100, derived from weighted attributes.
- profile_version: schema version for attributes and weights.
- last_prompted_at and prompt_history: timestamps and outcomes for each attribute.
- attribute source: signup, prompt, inference, import; track confidence scores.
- consent scopes: marketing_emails, personalization, product_analytics.

Technical implementation
- Maintain a prompt scheduler that selects the next best attribute to ask based on value, recency, and consent.
- Rate-limit prompts (e.g., no more than one per session, cooldown after skip).
- Store prompt outcomes: accepted, declined, dismissed, timed_out.
- Use feature flags to roll out new questions and measure impact.
- Localize questions and answer options; avoid jargon in labels.

Data handling
- Collect only what you need for the stated purpose and document retention.
- Annotate each attribute with purpose and lawful basis where applicable.
- Allow users to review and edit profile data in a preferences center.
- Respect regional rules (e.g., do not infer sensitive categories without explicit consent).

First vs later fields (examples)
- First: role, use case, company name (if B2B), team size bucket.
- Later: budget range, industry, advanced preferences, integrations of interest.
- Never first: demographics unrelated to product value, sensitive attributes, marketing qualifiers that do not change onboarding logic.

Triggers and timing
- Prompt on milestone events (value_moment_achieved) rather than random timeouts.
- Prefer after-success prompts; avoid during-task interruptions.
- On mobile, defer prompts until after navigation completes to avoid jank.

Validation and performance
- Inline, real-time validation for any required fields.
- Pre-fill when you can; never ask for the same data twice.
- Cache taxonomies and options client-side to prevent fetch delays.

Analytics
- Track both ‘shown’ and ‘completed’ for every prompt to measure effectiveness.
- Capture reasons for decline when voluntarily provided (free text optional).
- Correlate prompts with conversion outcomes (activation, retention).

Governance
- Review questions quarterly with product, marketing, and privacy stakeholders.
- Remove or re-weight low-signal attributes that do not improve outcomes.
- Keep an audit log of attribute changes (what changed, when, by whom, why).

Quality bar
- One question per step unless a strong value case is proven by data.
- Skippable, fast, accessible, and clearly beneficial to the user.