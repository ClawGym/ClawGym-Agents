# Analytics Events — Onboarding and Progressive Profiling

Event schema
- All events include: user_id, session_id, timestamp, device, locale.
- Include experiment variants when tests are active (experiment_key, variant).

Core onboarding events
- onboarding_started: triggered when signup form is viewed.
- signup_submitted: includes fields_count, sso_used, errors_count.
- onboarding_completed: time_to_complete, steps_count.

Progressive profiling events
- profile_prompt_shown: attribute_key, ui_surface, reason, attempt_number.
- profile_prompt_accepted: attribute_key, input_type, time_to_complete.
- profile_prompt_declined: attribute_key, decline_reason_if_provided.
- profile_field_completed: attribute_key, source (prompt, settings, inference).
- profile_completeness_updated: old_score, new_score, changed_keys.

Value and milestones
- value_moment_achieved: milestone_key, context (e.g., first_report, first_project).
- feature_adopted: feature_key, time_from_signup.

Friction diagnostics
- form_error: field_key, error_code, validation_stage.
- form_abandon: step_key, time_spent, last_field_focused.
- latency_metric: surface_key, ttfb_ms, render_ms.

Best practices
- Track both ‘shown’ and ‘completed’ to understand prompt effectiveness.
- Emit profile_prompt_declined when the user explicitly skips.
- Join analytics with consent scopes and honor user tracking preferences.
- Use server-side event forwarding to reduce dropped client events.
- Redact or hash PII in payloads where full data is not needed for analysis.