# Dossier — how to use it from ANY project

On-device document intake / index / retrieval. It lives OUTSIDE every Claude project
directory. **Always use absolute paths — nothing here is relative to your project.**

## CLI
- On PATH as `dossier` (symlink `/opt/homebrew/bin/dossier` → `/Users/cgclark/dossier/dossier`).
- If you get `dossier: command not found`, your shell's PATH lacks `/opt/homebrew/bin` —
  call the full path instead: `/Users/cgclark/dossier/dossier`
- `dossier --help` lists every subcommand.

## Key locations
| What | Absolute path |
|------|---------------|
| Toolchain root | `/Users/cgclark/dossier` |
| Results / manifests (the "work dir") | `/Users/cgclark/dossier/work/<matter>` |
| Matter originals | `/Users/cgclark/Documents/Claude/<matter>/sources/` |
| Drop / staging folder | `/Users/cgclark/Documents/Claude/ingest` |
| Trash (recoverable) | `/Users/cgclark/Documents/Claude/_trash` |

## Current matters (list live with `ls /Users/cgclark/dossier/work`)
- **West_826** → work `/Users/cgclark/dossier/work/West_826` · originals `/Users/cgclark/Documents/Claude/West_826/sources`
- **singapore** → work `/Users/cgclark/dossier/work/singapore` · originals `/Users/cgclark/Documents/Claude/Singapore_divorce/sources`

(Note the exact name/casing: it is `West_826`, not `west826`.)

## Common commands (absolute paths)
Ingest (idempotent — re-run to add new files):
```
dossier ingest "/Users/cgclark/Documents/Claude/West_826" --work "/Users/cgclark/dossier/work/West_826"
```
Query (never dumps whole docs):
```
dossier query "/Users/cgclark/dossier/work/West_826" find "rental cap"        # hits + one-line gists
dossier query "/Users/cgclark/dossier/work/West_826" get <id> <start> <end>   # slice by LINE number
dossier query "/Users/cgclark/dossier/work/West_826" get <id> 6 9 --pages     # slice by PAGE number
# NB `get` defaults to lines 0..40 (≈ page 1) when no range is given — that is NOT a bug, it means
# no range was passed. Use `--pages` (CLI) or the MCP `pages="6-9"` arg to read by page and avoid
# the line/page mix-up. MCP: get(work, artifact_id, pages="6-9").
dossier query "/Users/cgclark/dossier/work/West_826" verify "<value>" <id>    # confirm a value is present
```
On-device summaries (Apple Foundation Models; REDUCTION ONLY — verify before relying):
```
dossier summarize "/Users/cgclark/dossier/work/West_826" [<id>|missing|all]
```
Chronology / status:
```
dossier chronology   "/Users/cgclark/dossier/work/<matter>"
dossier ingest_status "/Users/cgclark/dossier/work/<matter>"
```

## Rules
- **Do NOT read source PDFs/images directly** — let the tools reduce them (keeps context small).
- Supported types: PDF, PNG/JPG/JPEG/TIFF/HEIC, `.eml`, `.xlsx`, `.docx/.doc/.rtf`, `.pptx`,
  `.txt` (incl. WhatsApp/iMessage exports), and public URLs (drop a `urls.txt` in the folder).
- **Drop-folder ingests take TOP-LEVEL files only — never recurse into subdirectories.**
  (A real matter's own `sources/legal`, `sources/property` etc. DO ingest recursively.)
- Extracted dates / SHAs / form-fields are document-backed; on-device summaries are reduction-only.
- If your project is sandboxed, `/Users/cgclark/dossier` and `/Users/cgclark/Documents/Claude`
  must be readable/writable, or every call fails regardless of correct paths.
