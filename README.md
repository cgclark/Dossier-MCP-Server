# Dossier

On-device document intake, indexing, and retrieval for case files — OCR, chronology,
dedup, and token-cheap search, exposed to Claude as an MCP server. Bulk content (raw
images, full text) never leaves disk; only compact, distilled results cross into the
conversation. See [SPEC.md](SPEC.md) for the full design and [DESIGN-NOTES.md](DESIGN-NOTES.md)
for running notes (e.g. the Windows port plan).

## Purpose

A local MCP server that turns a folder of source documents/messages into a
provenance-tagged **chronology**, an **organized + retrievable** file store, and
legal-ready **deliverables** (exhibit list, digest, assembled exhibits) — while
spending as few Claude context tokens as possible.

**Target 1 (primary): minimize Claude main-context tokens.** Bulk content (images,
full text) stays on disk; only compact, distilled results cross the MCP boundary into
the conversation. The MCP tool-call boundary plays the role subagents play in Claude
Code — the isolation layer Desktop otherwise lacks.

**Target 2 (secondary): organize the master/original files for easy later retrieval.**
Non-destructive; the manifest *is* the retrieval index (find without reading).

**Non-goals (v1):**
- Not legal advice — outputs are drafting aids for a human (lawyer) to review.
- No remote/hosted deployment — kills the on-device/private property; local-only.
- No automatic contact with third parties — the server *suggests*, the user acts.

## Status

| Platform | Ingest / OCR / summarize | Query / chronology / organize |
|---|---|---|
| **macOS** | ✅ native (Apple Vision + Foundation Models) | ✅ |
| **Windows** | ❌ not yet ported (needs a Windows OCR/date-detect swap-in — see DESIGN-NOTES.md) | ✅ |

The Python layer (`server/`, `parsers/`) is portable and identical on both platforms.
Only `engines/` and `helpers/` are native, macOS-only Swift binaries today.

## Layout

```
server/     MCP server (server.py) + the pipeline modules it shells out to
parsers/    Format-specific extractors (.eml, chat exports)
engines/    OCR / vision (Swift, macOS-only compiled binaries — sources tracked, binaries gitignored)
helpers/    Date detection, meta extraction, assembly, web capture (same deal as engines/)
skills/     Claude skill definition for driving Dossier from a conversation
schema.sql  Manifest DB schema
```

`matters/`, `work/`, and `captures/` are gitignored — they hold real case documents
(PII, financial, legal) and per-machine ingest state, and should never enter git history.

## Setup

### macOS
```bash
./build.sh                       # compiles engines/*.swift + helpers/*.swift (needs Xcode CLT)
python3 -m venv .venv
.venv/bin/pip install mcp
```
Register in Claude Desktop via `claude_desktop_config.snippet.json` (merge the `dossier`
entry into `claude_desktop_config.json`, then restart Desktop).

### Windows
```powershell
python -m venv .venv-win
.venv-win\Scripts\pip install --prefer-binary "mcp<2"
```
`mcp<2` is required — `server.py` uses the v1 `FastMCP` API, which mcp 2.x renamed.
Register as a project or user-scoped MCP server pointing at `.venv-win\Scripts\python.exe server\server.py`.
Ingest/summarize/assemble tool calls will fail here until a Windows engine port exists;
query-side tools work against any matter already ingested on macOS.

## CLI

The `dossier` script is a thin bash dispatcher over the same modules the MCP server calls
— useful from a shell with full filesystem access (no MCP round-trip needed):

```bash
dossier ingest "<matter_dir>" --work "<work_dir>"        # OCR + extract (idempotent, resumable)
dossier query "<work_dir>" find "rental cap"             # hits + one-line gists
dossier query "<work_dir>" get <id> --pages "6-9"         # read by page, never dumps the whole doc
dossier query "<work_dir>" verify "<value>" <id>          # confirm a value is document-backed
dossier chronology "<work_dir>"
dossier summarize "<work_dir>" [<id>|missing|all]         # on-device, reduction-only — verify before relying
```

**Rules:** never read source PDFs/images directly — let the tools reduce them. Drop-folder
ingests take top-level files only (no recursion); a matter's own `sources/` subfolders do
recurse.
