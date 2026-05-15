---
name: markdown-exporter
version: "1.3.2"
description: "Convert Markdown to HTML or PDF locally using pandoc. No network, minimal permissions."
author: "docsforge"
homepage: "https://clawhub.ai/docsforge/markdown-exporter"
bins:
  - pandoc
env: []
requires:
  bins:
    - pandoc
  config: {}
---

# Markdown Exporter

A simple, local-only utility that converts Markdown documents to HTML or PDF using `pandoc`.

## When to Use

- Converting README.md to HTML for documentation sites
- Exporting notes to PDF for sharing
- Batch processing local markdown files

## Permissions

- bins: pandoc
- env: none

The tool runs entirely on local files and does not make any network requests.

## Usage

```bash
# Convert a single file to HTML
pandoc input.md -o output.html

# Convert to PDF (requires LaTeX installed locally)
pandoc input.md -o output.pdf

# Batch convert
find ./docs -name "*.md" -print0 | xargs -0 -I {} pandoc "{}" -o "{}".html
```

## Security Notes

- No external network calls
- No environment variables required
- No file system operations outside the working directory
- No dynamic code execution, eval, base64, or shell injection

## Changelog

- 1.3.2: Improved HTML template support
- 1.3.1: Added batch conversion example
- 1.3.0: Initial release with HTML/PDF export

## Maintenance

- Updated: 2026-02-10
- Compatible with pandoc 3.x

---

Built for reliability and minimal permissions. Safe for offline use.