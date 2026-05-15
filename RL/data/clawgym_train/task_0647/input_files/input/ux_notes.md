Overview
- Storefront: Shopify, Dawn-based theme with native cart drawer (AJAX).
- Markets: US (USD), CA (CAD), UK (GBP) with localized pricing; free-shipping threshold shown only on cart page today.
- Brand tone: playful-premium — fun and cheeky but visually clean.

Cart Drawer (current)
- Opens from the right; shows line items with thumbnail, title, variant, qty stepper, price, and remove.
- Subtotal shown above primary buttons: [Checkout], [View cart]; dynamic checkout options (Shop Pay, Apple Pay) appear below.
- There is a “message” slot just above the buttons used for a generic note (“Free shipping on orders $39+”); it does not update based on cart subtotal.
- AJAX add/remove updates subtotal in real time; adding from product pages uses one-click add and updates the drawer without reload.
- Space available for a compact module below the line items and above the buttons (approx. 2 product cards wide on desktop; 1 on mobile).
- Mobile constraints: viewport ~375px; carousels feel cramped; ideally show up to 3 items total, stacked vertically with small thumbnails and short titles.

Cart Page (current)
- Displays a “You may also like” product grid with 4 cards (full-width desktop, 2-up on mobile) between cart items and the checkout button.
- The grid is not margin-aware and rotates seasonal products; not tuned for price gaps vs free-shipping threshold.
- No progress bar; only a static line “Free shipping over $39” (localized per market via translation strings but not dynamic with subtotal).

Checkout / Pre-Checkout
- Shopify Checkout (one-page). No custom extension currently installed for upsells.
- Attempting to inject large content risks drop-offs; safe space is limited callouts in the order summary area (if any).

Known Issues / Opportunities
- Customers near threshold aren’t nudged with a dynamic “You’re $Y away” message; there’s no gap-aware logic.
- The “You may also like” grid sometimes features low-margin or out-of-stock items; no filter by margin or return rate.
- Drawer supports one-click add from a small card component (used in PDP recommendations); can be reused for top-up items.
- Success state (after crossing threshold) is not highlighted; no “You unlocked free shipping” event or loyalty tie-in yet.
- We can add a slim progress bar and up to 3 compact recommendations in the drawer without pushing the primary buttons below the fold on mobile.