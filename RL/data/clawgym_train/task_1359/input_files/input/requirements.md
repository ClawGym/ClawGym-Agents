# Discount Module — Requirements

Scope
- Implement a small, production-ready discount module with clean architecture.
- Provide a CLI entry point for calculating discounts on an order JSON.
- Use only the Python standard library. No external dependencies.
- Keep all reads relative to input/, and place your code under output/.

Layer Boundaries
- Handler (CLI):
  - Parses command-line args and reads the order JSON file
  - Loads prices via repository helpers
  - Calls the service function
  - Prints JSON result to stdout
  - On error: print a clear message to stderr and exit non-zero
  - No business logic or CSV parsing in this layer
- Service (Business logic):
  - Implements calculate_discount(order, get_price)
  - Pure business logic: no I/O, no filesystem, no CLI parsing
  - Uses named constants (no magic numbers) and small functions with early returns
  - Raises typed errors for invalid input or unknown products
- Repository (Data access):
  - Loads the products catalog from CSV at a default relative path 'input/products.csv'
  - Exposes load_prices(path='input/products.csv') and get_price(product_id, prices)
  - No business rules here

Typed Errors
- Define in errors.py:
  - class DomainError(Exception) as base
  - class ValidationError(DomainError)
  - class NotFoundError(DomainError)
- Service should raise:
  - ValidationError for invalid order shapes (missing fields, wrong types, non-positive quantities)
  - NotFoundError for unknown product IDs
- Handler should:
  - Catch DomainError (and subclasses), print a clear error message to stderr, and exit with non-zero status
  - Avoid printing stack traces in normal operation

Business Rules
1) Order structure (JSON)
   - Required: "items": a non-empty list of objects { "product_id": string, "quantity": integer > 0 }
   - Optional: "customer": { "vip": boolean }. If missing or missing "vip", treat as non-VIP (False)
   - Optional: "order_id": string (only for traceability in output)
2) Prices
   - Load unit prices from input/products.csv via repository.load_prices()
   - Unknown product_id must raise NotFoundError
3) Subtotal
   - subtotal = sum(price(product_id) * quantity) across items
4) Discount rules (use named constants; values below)
   - If subtotal < ORDER_DISCOUNT_THRESHOLD: discount = 0
   - If subtotal >= ORDER_DISCOUNT_THRESHOLD: apply BASE_DISCOUNT_RATE to subtotal
   - If customer.vip is True: add VIP_EXTRA_RATE to the discount rate (i.e., total_rate = BASE_DISCOUNT_RATE + VIP_EXTRA_RATE)
   - Cap the absolute discount amount at MAX_DISCOUNT
5) Totals
   - total = subtotal - discount
   - Do not produce negative totals (should not happen with the above rules)

Constants (define in service.py)
- ORDER_DISCOUNT_THRESHOLD = 100.00
- BASE_DISCOUNT_RATE = 0.10
- VIP_EXTRA_RATE = 0.05
- MAX_DISCOUNT = 50.00

I/O Expectations
- Repository CSV input (relative only): input/products.csv
  - CSV headers: product_id,name,price
  - price is a decimal number in standard dot notation (e.g., 60.00)
- Handler CLI:
  - Entry: handle_cli(args=None)
  - Argument: --order <path> (JSON file path relative or absolute; prefer relative)
  - Prints a JSON object to stdout with at least:
    - subtotal (number)
    - discount (number)
    - total (number)
    - It’s acceptable (and encouraged) to include helpful metadata like vip, applied_rate, capped, order_id
  - On error:
    - Print a single-line message to stderr of the form: "ERROR: <ErrorType>: <message>"
    - Exit with code 1 (non-zero)
- Numerical precision:
  - You may use float or decimal.Decimal from the standard library
  - Round monetary outputs to 2 decimal places in the CLI output for readability

Validation Rules (Service)
- items must be a non-empty list
- Each item must contain a non-empty string product_id and an integer quantity > 0
- Any invalid order shape or invalid types → raise ValidationError
- Unknown product_id through get_price → raise NotFoundError

Testing Expectations (for your tests in output/tests/test_service.py)
- Use only the standard library unittest
- Cover:
  - Boundary: no discount below threshold
  - Boundary: discount at threshold
  - VIP extra rate increases discount
  - Discount cap applied at MAX_DISCOUNT
  - Unknown product raises NotFoundError
  - Invalid order raises ValidationError

Examples

Example products CSV (already provided in input/products.csv):
product_id,name,price
P200,Advanced Widget,60.00
P300,Service Plan,15.00
...

Example order JSON (already provided in input/order_example.json):
{
  "order_id": "ORD-001",
  "customer": { "vip": true },
  "items": [
    { "product_id": "P200", "quantity": 2 },
    { "product_id": "P300", "quantity": 1 }
  ]
}

Expected calculation for the example:
- Prices: P200 = 60.00, P300 = 15.00
- Subtotal = (2 * 60.00) + (1 * 15.00) = 135.00
- Threshold reached (>= 100.00)
- Base rate = 0.10; VIP extra = 0.05 → total_rate = 0.15
- Discount = 135.00 * 0.15 = 20.25 (below MAX_DISCOUNT)
- Total = 135.00 - 20.25 = 114.75

Non-Functional Constraints
- Functions should be kept under ~30 lines, use early returns, and avoid deeply nested conditionals
- No magic numbers in business logic — use named constants
- Only standard library modules
- All file paths must be relative (no absolute paths in repository defaults)

When in doubt, follow clean architecture: handler → service → repository, with typed errors and explicit constants.