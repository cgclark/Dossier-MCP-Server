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

| Platform | Ingest / OCR | Summarize | Assemble / webcapture | Query / chronology / organize |
|---|---|---|---|---|
| **macOS** | ✅ Apple Vision (on-device) | ✅ Apple Foundation Models (on-device) | ✅ | ✅ |
| **Windows** | ✅ Windows AI OCR (on-device, NPU) | ✅ **Claude Haiku over the network** | ✅ | ✅ |

> **Windows arch note:** built and verified on **Windows 11 ARM64** (Copilot+ PC) only.
> The code has no hardcoded architecture and every dependency ships x64 wheels too, so
> it should work unmodified on x64 Windows — but that has **not been tested**. `.venv-win`
> itself isn't portable between architectures either way; each machine needs its own
> `python -m venv` + pip install, which will just resolve the matching wheels for
> whatever CPU it's running on.

The Python layer (`server/`, `parsers/`) is portable and identical on both platforms.
`engines/`/`helpers/` are native on macOS (compiled Swift binaries); on Windows the
`*_win.py` scripts next to each one are pure-Python equivalents — see Setup below.

**Privacy note:** every step is fully on-device on both platforms, with exactly one
exception — **Windows `summarize` sends document text to Anthropic's API** (Claude
Haiku) for its optional on-device-style gist, since Apple's Foundation Models has no
Windows equivalent. `ingest`/OCR/dates/search/`assemble`/`webcapture` stay 100% local
on Windows too. `summarize` is opt-in (`--summarize` on ingest, or an explicit
`summarize` tool call) and requires `ANTHROPIC_API_KEY` — without it, it degrades
gracefully to `{"available": false}` rather than failing.

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
.venv-win\Scripts\pip install --prefer-binary "mcp<2" PyMuPDF Pillow pillow-heif dateparser `
  python-docx striprtf pypdf reportlab playwright anthropic `
  winsdk
```
`mcp<2` is required — `server.py` uses the v1 `FastMCP` API, which mcp 2.x renamed.
Register as a project or user-scoped MCP server pointing at `.venv-win\Scripts\python.exe server\server.py`.

Windows engines, and what they need:
- **OCR** (`engines/ocr_win.py`) — Windows AI OCR via `winsdk`. On-device, NPU-accelerated
  on Copilot+ PCs. Needs an OCR language installed (Settings → Time & Language → Language
  & region → add a language with the "Optical character recognition" component; usually
  already present).
- **meta / datedetect** — PyMuPDF + Pillow / `dateparser`. No setup needed.
- **assemble** — `pypdf` + `reportlab`. No setup needed.
- **webcapture** — Playwright driving your already-installed Edge (falling back to Chrome).
  No browser download needed.
- **summarize** — calls Claude Haiku over the network (see the privacy note above). Set
  `ANTHROPIC_API_KEY` in the environment to enable it; without it, `summarize` degrades
  to `{"available": false}` rather than failing.

`opencv-python`/`pyclipper`/`Shapely` (RapidOCR's dependencies) have **no ARM64 Windows
wheels** and need a full C++ build toolchain to compile from source — that's why OCR uses
Windows AI OCR instead. `.doc` (legacy binary format, not `.docx`) has no lightweight
Windows reader; ingest notes this per-file rather than failing silently — convert to
`.docx` first if you need one indexed.

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
