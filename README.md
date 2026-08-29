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

**Background.** Hand a document with embedded images (a scanned PDF, a photographed
letter) to Claude directly and each image gets read in as real tokens (~1,600/page
after resize) — and because a conversation is stateful, that cost doesn't go away once
the image has been looked at. It's carried in every subsequent turn for the rest of the
session, quietly subsuming context that has nothing to do with it. Across a real case
corpus this adds up fast: a 250-page pile can cost ~175k tokens read this way, against
~10k for what Dossier actually needs to answer a question — and a large enough corpus
exceeds the context window outright before any real work gets done in it.

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

**Prerequisites:** Xcode Command Line Tools (`xcode-select --install`, for `swiftc`) and
Python 3.11+. On-device summaries (`summarize`) additionally need **macOS 26+ on Apple
Silicon with Apple Intelligence enabled** — they use Foundation Models. OCR (Apple Vision)
and everything else work on any current macOS.

```bash
# 1. Build the native Swift engines + helpers (re-run after editing any .swift)
./build.sh                       # swiftc -O over engines/*.swift + helpers/*.swift → gitignored binaries

# 2. Python env for the MCP server
python3 -m venv .venv
.venv/bin/pip install mcp

# 3. (optional) put the CLI on PATH so `dossier …` works from anywhere
ln -s "$PWD/dossier" /opt/homebrew/bin/dossier
```

Then either:
- **MCP** — merge the `dossier` entry from `claude_desktop_config.snippet.json` into
  `claude_desktop_config.json` (it points Desktop at `.venv/bin/python server/server.py`),
  then restart Claude Desktop; or
- **CLI / Claude Code** — skip the MCP and drive it straight from a shell with the `dossier`
  commands below (no MCP round-trip, full filesystem access).

Quick check the build worked: `ls helpers/meta helpers/summarize engines/ocr` should list
the compiled binaries.

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
