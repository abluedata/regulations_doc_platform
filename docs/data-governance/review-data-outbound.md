# Review Data Governance

This W1 note documents the minimum offline data-governance contract for review evaluation and .review_data operations.

- .review_data backups are created and restored with scripts/backup_review.py; each archive contains backup_manifest.json with SHA-256 hashes for every file.
- The current migration marker is backend/migrations/0001_review_data_governance.json; later schema changes must add a new immutable migration file instead of editing historical markers.
- Evaluation gold data is locked through backend/eval/gold/manifest.json; reports must carry the gold dataset_sha256.
- Potential outbound data includes document text, review findings, retrieval snippets, prompts, and embeddings sent to configured LLM or embedding providers; operators must document provider, region, retention, and masking policy before enabling external providers.
- Deleting a review task must include verifiable cleanup of associated jobs, reports, exported artifacts, and audit references according to the active migration contract.

