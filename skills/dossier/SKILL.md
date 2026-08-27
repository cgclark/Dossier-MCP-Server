---
name: dossier
description: On-device document intake, indexing & retrieval for a matter — builds a provenance-tagged chronology, organized store, and exhibit deliverables while keeping page images and full text OUT of the main context. Use whenever the user attaches, drops, or points at document/data files — PDF, images (PNG/JPG/JPEG/TIFF/HEIC), .eml, .xlsx, .docx/.doc/.rtf, .pptx, .txt (incl. WhatsApp/iMessage chat exports), or public URLs — instead of reading them raw; and when they want to OCR/index/ingest/chronologize/organize a document set, find facts across it, verify dates/values against sources, generate on-device summaries, or produce an exhibit list / digest / assembled bundle. Ingest through Dossier, then pull only find-hits and slices into context. Runs from Claude Code (full filesystem access; no Claude Desktop MCP or Full Disk Access needed).
---

# Dossier — on-device document chronology & deliverables

Drive everything through the `dossier` CLI (on PATH; or `~/dossier/dossier`).
All heavy work happens on disk; only compact results enter the conversation. Do NOT read
the source PDFs/images directly — let the tools reduce them.

## Pipeline
1. **Ingest** (OCR + band-1/1.5/2 extraction + dedup + manifest):
   `dossier ingest "<matter_dir>" --work "<work_dir>"`
   - `<matter_dir>` must contain a `sources/` subfolder (a flat folder of files also works). Quote paths with spaces.
   - **Web pages (public URLs):** put a `urls.txt` (one URL per line, `#` comments ok) in the
     folder — each is captured to an immutable PDF snapshot (WKWebView) and ingested as
     `kind=webpage` with the URL + a `retrieved` UTC timestamp + any page-declared published/
     modified dates. Needs network (opt-in); content is "as-of retrieval" (live page may change);
     public/unauthenticated pages only.
   - Idempotent and **resumable**: re-running skips files already in the manifest.
   - **Async over MCP (unsupervised-safe):** the `ingest` MCP tool OCRs in a detached
     background process and returns immediately (no MCP request timeout). Poll
     `ingest_status "<work_dir>"` until it reports `done` (it then prints the full
     summary), then proceed. If status says `stalled`, just call `ingest` again to resume.
     The `dossier` CLI runs ingest synchronously (no timeout) and prints the summary directly.
2. **Chronology**: `dossier chronology "<work_dir>"` → merged UTC ledger + cross-doc coincidences (writes chronology.json).
3. **Organize**: `dossier organize "<work_dir>" [--apply]` → dedup, misfile flags, provenance naming, symlink tree.
4. **Query** (token-cheap; never dumps docs):
   - `dossier query "<work_dir>" find "<text>"`
   - `dossier query "<work_dir>" get <artifact_id> <start> <end>`
   - `dossier query "<work_dir>" verify "<value>" <artifact_id>`
5. **Deliverables**:
   - `dossier exhibit_list "<work_dir>" [--order chrono|type]`
   - `dossier digest "<work_dir>"` → fact skeleton with one-line `{{relevance}}` placeholders to fill
   - `dossier assemble "<spec.json>" "<out.pdf>"` → exhibit bundle from ORIGINALS (cover + pages)
6. **Savings**: `dossier savings "<work_dir>"` → dual-baseline token report.

## Rules (context discipline)
- Reduce on disk; pull only slices (`get`) or search hits (`find`) into context on demand.
- Dates: form-field & DocuSign dates are typed (effective/expires/signed); zone-unknown is
  flagged honestly; ranges kept whole; locale inferred per-document. Confirm operative
  meaning yourself, but treat extracted values as document-backed unless flagged.
- For digest relevance lines, prefer the manifest facts; read a slice only if needed.
- Originals are never modified; organization is symlink-based and reversible.

## Notes
- macOS only (Apple Vision). No Full Disk Access / Desktop MCP required when run from Claude Code.
- Engines reused from `~/dossier/engines/` (`ocr`, `screenreduce`).
