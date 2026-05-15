# Stakeholder Brief — Unified List Layout System (v1)

Owner: Web Platform Team
Date: 2026-04-19
Audience: Design + Front-End

## Goals
- Unify list presentation across two key surfaces: Blog Index and Site Search Results.
- Improve scanning speed, readability, and consistency using a list-first system optimized for F-pattern reading.
- Preserve SEO: infinite scroll is allowed only with a robust, crawlable pagination fallback.
- Ship a spec plus a lightweight prototype driven by input/content.json.

## Surfaces and Intent
1) Blog Index
- Intent: Discovery and browsing. Readers scan titles, then glance at metadata and excerpts.
- Primary KPI: CTR on posts and time-on-page.
- Secondary: Per-author navigation and category discovery.

2) Search Results
- Intent: Decision speed. Users quickly assess relevance based on title and snippet.
- Primary KPI: CTR on most relevant results.
- Secondary: Low pogo-sticking (back/forth between results and detail pages).

## Variant, Density, and Structure
- Blog Index:
  - Variant: Rich list (title, excerpt, date, author, category). Thumbnails optional.
  - Density: Relaxed (more breathing room to encourage exploration).
  - Metadata order: date • author • category.
  - Clickable area: Prefer full-row for higher CTR and easier touch interaction.
  - Dividers: None (use whitespace rhythm) or subtle zebra as a fallback if readability suffers. Preference: none.
  - Item spacing (gap): 24 px target.
  - Thumbnail guidance: Optional 80–96 px square on tablet/desktop; hide on mobile.

- Search Results:
  - Variant: Rich list (title + snippet + type/date). No thumbnails.
  - Density: Compact (maximize above-the-fold results).
  - Metadata order: type • date.
  - Clickable area: Title-only (reduces accidental clicks, better precision).
  - Dividers: Use single-pixel divider between items.
  - Item spacing (gap): 12 px target.

## F-Pattern and Hierarchy
- Titles must be left-aligned and visually dominant for both surfaces.
- Metadata is secondary (reduced contrast).
- Blog Index per-item hierarchy:
  1) Title (link)
  2) Metadata row: date • author • category
  3) Excerpt (2–3 lines)
  4) Optional thumbnail (tablet/desktop)
- Search Results per-item hierarchy:
  1) Title (link)
  2) Snippet (1–2 lines)
  3) Metadata row: type • date

## Responsive
- Mobile: Single column for both surfaces (mandatory), minimum touch target size 44 px.
- Breakpoints (reference):
  - Mobile: 0–599 px (1 column)
  - Tablet: 600–1023 px (1 column, optional thumbnail on blog index)
  - Desktop: ≥1024 px (1 column lists; more generous spacing on blog index)
- Truncation:
  - Blog Index: Titles clamp to 2 lines on mobile, 3 lines on desktop; excerpts 2 lines mobile, 3 lines desktop.
  - Search Results: Titles clamp to 2 lines; snippets 2 lines max.

## Accessibility
- Use list semantics (ul/li) and ARIA labels for each list region.
- Keyboard focus order: moves to each item title (anchor) in logical reading order; for Blog Index full-row click behavior, ensure the title link receives primary focus, with the row container not stealing focus.
- Touch targets: All interactive targets must be ≥ 44 px in height and width.
- ARIA labeling:
  - Blog index list container: aria-label="Blog index list"
  - Search results list container: aria-label="Search results list"
- Ensure visible focus states on titles and adequate color contrast for metadata.

## Infinite Scroll and SEO
- Infinite scroll is allowed; however, we must provide a crawlable pagination fallback with stable URLs.
- Pagination (fallback) must include:
  - Blog index:
    - page_param: "page"
    - page_size: 12
    - page_url_template: "/blog?page={page}"
  - Search results:
    - page_param: "page"
    - page_size: 10
    - page_url_template: "/search?q={query}&page={page}"
- The fallback pagination must be visible and usable without JavaScript so crawlers can fully access the content.

## Clickable Area Strategy and Analytics
- Blog Index: Full-row is clickable; also wrap the title in an anchor for accessibility. Add data-click-target="row" on the li container (or the immediate item wrapper) to enable analytics.
- Search Results: Title-only clickable for precision. Add data-click-target="title" for analytics.
- Ensure event delegation is possible for both patterns.

## Content and Metadata Requirements
- Blog Index item fields (from content.json): title, date, author, category, excerpt, url, optional thumbnail_url.
- Search Results item fields: title, snippet, type (Article/Doc/Page), date, url.

## Spacing and Type
- Base font size: 16 px body.
- Blog Index:
  - Title: 20–24 px, left-aligned; line-height ~1.3–1.4; gap 8–12 px below title.
  - Metadata: 14–15 px, secondary color; gap 8 px above excerpt.
  - Excerpt: 15–16 px; clamp as above.
  - Item gap: 24 px; no divider.
- Search Results:
  - Title: 18–20 px, left-aligned; gap 6–8 px below.
  - Snippet: 14–15 px; clamp as above.
  - Metadata: 13–14 px; single-pixel divider between items.
  - Item gap: 12 px.

## Constraints
- Implementation must be fast and lightweight (no frameworks required in the prototype).
- Use the provided input/content.json as the data source for rendering.
- Avoid large images; defer or omit thumbnails on mobile.
- Do not rely on external libraries beyond what a static HTML/JS page can do.

## Out of Scope (for v1)
- Advanced image cropping or responsive art direction.
- Server-rendered filtering or sorting.
- Query highlighting (may be considered later).

## Summary of Hard Requirements
- Blog Index: variant=rich, density=relaxed, left-aligned titles, row is clickable.
- Search Results: variant=rich, density=compact, left-aligned titles, title-only clickable.
- Mobile: single column for both.
- Infinite scroll: must include SEO-friendly pagination fallback with defined page_param and page_url_template.
- Touch target minimum: 44 px.

---