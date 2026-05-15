Business: Fresh Fork Meals (solo operator)

Operating model
- Weekly rotating menu for ready-to-eat meals (poultry, beef, vegetarian, gluten-free options).
- Orders open Mon–Fri (cutoff Fri 6:00pm). Production Sat–Sun. Pickup/delivery Sun–Mon.
- Average volume: ~50 orders/week (~200 orders/month), average 3–5 items per order.

Current process (end to end)

1) Order intake
- Platform: Shopify storefront with Stripe payments.
- Customer enters contact details, pickup/delivery selection, dietary notes.
- Pain points:
  - Confirmation and pickup/delivery instructions are sent manually via Gmail using canned responses (2 min/order).
  - Shopify order export is manual.

2) Daily order management (Mon–Fri evenings)
- Export orders CSV from Shopify → paste into Google Sheets “Orders Master”.
- Create a pivot tab for counts per SKU; copy totals to “Grocery List” tab.
- Time: ~25 min/day, 5 days/week (~20 times/month).
- Pain points: repetitive copying/pasting, occasional mismatches between pivot and grocery list.

3) Customer communications
- Send order confirmation and pickup/delivery guidance from Gmail. Attach PDF instructions for pickup windows or delivery windows.
- Add customer to Mailchimp audience (manual add to list).
- Time: ~2 min/order (200/month).
- Pain points: easy to miss sending; duplicate data entry to Mailchimp.

4) Label and paperwork prep (Fri)
- Labels: Copy product names, ingredients, and allergens from Sheets into an Avery template in Google Docs; print sheets.
- Prep sheets: Print per-SKU batch sheets from Sheets.
- Time: Labels ~20 min/run, 2 runs/week (8 times/month); prep sheets included in the same session.
- Pain points: repetitive formatting and occasional typos in allergen statements.

5) Receiving (Sat morning)
- Receive produce, meats, dairy. Manually check and record temperatures of TCS items on paper receiving log.
- Verify supplier invoices and update a paper binder with COAs when provided.
- Pain points: handwritten logs; later scanning to Drive is sporadic.

6) Production (Sat–Sun)
- Prep: Weigh, chop, portion.
- Cook: Batch cook proteins and sides.
- Cooling: Shallow pans, ice bath/blast chiller substitute; track time/temperatures on paper cooling log.
- Sanitation: Verify sanitizer concentration with test strips; record on paper.
- Time logging: Cooking temps and cooling steps take ~15 min/log entry across batches; ~60 entries/month.
- Pain points: paper forms get smudged; manual transcription to Sheets at month-end is error-prone.

7) Packaging and storage (Sun)
- Package into tamper-evident containers; apply printed labels.
- Cold hold: Items stored at ≤41°F in reach-in coolers; occasional spot-check temps recorded on paper.
- Pain points: label generation is manual; allergen labeling inconsistencies risk.

8) Delivery/Pickup (Sun–Mon)
- Create a simple route in Google Maps for local deliveries; print addresses from Sheets.
- Record product temperatures at dispatch and (spot) at first delivery; paper log.
- Mark orders “fulfilled” in Shopify manually.
- Time: Route planning ~30 min, 3 times/month (delivery runs vary by week).
- Pain points: manual routing; no automated reminder for customers; fulfillment status updates are easy to forget.

9) Admin & compliance (Weekly/Monthly)
- Reconcile Stripe payouts in QuickBooks Online weekly (~45 min/week).
- Create HACCP packet (scan paper logs to a Drive folder; export Sheets as PDFs) monthly and email to a compliance folder address (30 min/week for prep, ~2 hr/month total but performed as weekly 30-min sessions).
- Post on Instagram manually (write, upload, caption) ~12 posts/month (~20 min/post).
- Pain points: manual reconciliation clicks; scattered HACCP docs; social posts not batched.

Key pain points summarized
- Duplicate data entry between Shopify → Google Sheets → labels → Mailchimp.
- Manual, repetitive email confirmations.
- Paper HACCP logs (receiving, cooking, cooling, sanitizer, cold holding) require manual entry and scanning.
- Label generation is repetitive and error-prone.
- Delivery routing is manual and time-consuming for small drops.
- Reconciliation and fulfillment status changes are easy to miss.

Available tools in use
- Shopify + Stripe, Gmail, Google Sheets/Drive, QuickBooks Online, Mailchimp, Google Calendar, Slack (light use).