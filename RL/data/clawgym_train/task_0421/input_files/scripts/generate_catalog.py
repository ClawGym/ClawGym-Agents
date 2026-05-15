#!/usr/bin/env python3
"""
Generate catalog HTML and JSON from products CSV and site config.
Usage:
  python3 scripts/generate_catalog.py --products input/products.csv --config config/site_config.yaml --template templates/catalog_template.html --out-html output/catalog.html --out-json output/catalog.json

Requirements to implement:
- Read CSV and filter active products
- Read YAML config and use tax_rate, currency, shop_name, city, featured_category
- Read HTML template and replace placeholders
- Compute price_with_tax and availability
- Sort by category then name
- Write output HTML and JSON to specified paths
"""

import argparse
import sys

# TODO: Implement argument parsing, file IO, CSV/YAML parsing, computations, and writing outputs.

def main():
    parser = argparse.ArgumentParser(description="Generate catalog HTML and JSON from products CSV and config")
    parser.add_argument("--products", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--out-html", required=True)
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args()
    
    # TODO: implement the full pipeline described in the module docstring.
    print("TODO: implement generate_catalog.py", file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    main()
