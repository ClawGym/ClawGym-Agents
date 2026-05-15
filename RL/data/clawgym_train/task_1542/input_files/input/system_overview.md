# FreshCart — System Overview

## Product Summary
FreshCart is a B2C web application for ordering everyday goods (household, pantry, and personal care) with home delivery. Users browse a catalog, add items to a cart, and check out using Stripe for payment processing. The product is web-first with future plans for a mobile app.

- Primary domains:
  - Web app: https://app.freshcart.com (React SPA)
  - API: https://api.freshcart.com (REST JSON)
  - Assets: https://assets.freshcart.com (images, static)

## Users and Scale (initial)
- Target launch cohort: ~20k registered users in first 6 months
- Peak concurrent users: ~300
- Checkout volume: ~200 orders/day average, peak ~800 on promotions

## Data Types Processed
- PII (basic):
  - Name
  - Email address
  - Hashed password
  - Shipping address(es)
  - Phone (optional, for delivery contact/2FA)
- Transactional:
  - Order history (items, totals, timestamps)
  - Stripe payment metadata (customer ID, PaymentIntent ID, last4, brand; no raw PAN)
  - Delivery instructions
- Technical/Telemetry:
  - IP addresses and user-agent
  - Application logs and error traces (scrubbed)
  - Product analytics events (consent-gated)
- Optional user content:
  - Profile photo (if uploaded)

## Sensitive Operations
- User authentication (login, password reset)
- Payment creation via Stripe Elements (PaymentIntent/Create, Confirm)
- Address management
- Order placement and refunds
- Admin functions (catalog management, pricing, fulfillment statuses) — restricted

## Data Retention and Privacy
- Retention:
  - Order and account data retained for 24 months by default (legal/accounting review pending)
  - Logs retained 30 days (application), 90 days (security events)
- Deletion:
  - Users can request account deletion; orders retained as legally required while PII minimized/anonymized
- Consent:
  - Analytics collection requires explicit opt-in for EU users
- Data subjects:
  - US and EU residents; GDPR and CCPA apply

## User Flows
1) Sign-up
   - Email/password creation
   - Optional phone for delivery notifications
   - Email verification link
2) Login
   - Email + password; optional 2FA via SMS (pilot) for admin/internal only
3) Browse & Cart
   - Search and browse catalog
   - Add/update/remove items in cart
4) Checkout
   - Address selection or creation
   - Payment via Stripe Elements (card details handled by Stripe)
   - Order confirmation and email receipt
5) Account Management
   - View orders, update addresses, change password
6) Support
   - Contact form (ticket submitted via email system)

## Current Security Posture (Highlights)
- Passwords hashed with bcrypt (cost 12)
- TLS enforced end-to-end (Cloudflare edge and AWS ALB)
- JWT access tokens (15 min) + refresh tokens (7 days) in HttpOnly cookies; token rotation not yet implemented (planned)
- Rate limiting at edge (Cloudflare) and app layer
- CSRF protection on state-changing endpoints (SameSite=Lax + CSRF token for web forms)
- Error monitoring with Sentry (PII scrubbing on)
- WAF rules active at Cloudflare; no HSTS preload yet

---

This overview should guide security assessment, threat modeling, and prioritization for launch-readiness.