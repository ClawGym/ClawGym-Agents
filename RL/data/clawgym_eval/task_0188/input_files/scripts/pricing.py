# Pricing rules used for yoga + massage bundles.
# Inspect this file to apply the correct tax and discounts.

TAX_RATE = 0.0725  # 7.25% sales tax

# Percentage discounts by package_id for bundles.
BUNDLE_DISCOUNT = {
    "ZEN_DUO": 0.05,        # 5% off
    "DEEP_RESTORE": 0.10    # 10% off
    # Any package_id not listed here has 0% discount.
}

def included_add_on_cost(included_add_ons, add_on_pricing):
    """Return the total cost of included add-ons based on pricing map."""
    return sum(add_on_pricing.get(name, 0) for name in included_add_ons)

# Example calculation outline (for reference):
# subtotal = base_price + included_add_on_cost(...)
# after_discount = subtotal * (1 - BUNDLE_DISCOUNT.get(package_id, 0.0))
# final_with_tax = after_discount * (1 + TAX_RATE)
