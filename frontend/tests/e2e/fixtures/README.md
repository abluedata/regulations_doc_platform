# Browser Review Fixture Metadata

This directory is reserved for legally safe browser-test fixtures and their expected evidence metadata. Do not place real regulatory submissions, client files, personal data, or third-party source documents here.

No PDF or DOCX binary is added in this setup task. Each future fixture must include a compact JSON sidecar that records `fixture_id`, `source_format`, `document_version_id`, `content_sha256`, `finding_id`, `quote`, `quote_sha256`, and an exact locator.

Required fixture scenarios:

- A PDF repeats one invented sentence on two pages; the sidecar identifies the intended page and normalized rectangle list.
- A rotated PDF verifies the same locator at zoom and device-pixel-ratio variants.
- A DOCX repeats an invented paragraph and table-cell text; the sidecar identifies the exact paragraph/run or table-cell locator.
- A mismatch case intentionally changes the document version or quote hash and asserts that the viewer refuses to highlight any alternate occurrence.

Use stable invented identifiers such as `fixture-version-001` and `finding-repeated-text-page-2`. Assertions must consume these sidecars so repeated text never permits a quote-first match.
