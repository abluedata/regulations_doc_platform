# Review Fixture Metadata

This directory will hold deterministic, legally safe review fixtures. Do not add customer documents, contracts, names, addresses, account numbers, or copyrighted source material.

No binary fixture is committed in this setup task. When a PDF/DOCX fixture is added, commit its sidecar metadata with the following fields:

```json
{
  "fixture_id": "repeated-text-pdf-v1",
  "source_format": "pdf",
  "document_version_id": "fixture-version-001",
  "content_sha256": "<sha256 of fixture bytes>",
  "findings": [
    {
      "finding_id": "finding-repeated-text-page-2",
      "quote": "The supplier shall provide written notice within 30 days.",
      "quote_sha256": "<sha256 of UTF-8 quote>",
      "locator": { "page": 2, "rectangles_normalized": [[0.12, 0.34, 0.68, 0.37]] }
    }
  ]
}
```

The PDF case must repeat the exact sentence on at least two pages and identify the annotated occurrence with page and normalized rectangles. The DOCX case must repeat a paragraph and a table-cell value and use stable block, paragraph, run, and table-cell locators. Use invented neutral business text only.
