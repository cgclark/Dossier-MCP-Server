# Dossier — on-device document/chronology MCP server for Claude Desktop

**Status:** signed off 2026-06-27 — v1 build in progress
**Name:** Dossier
**Home:** `~/Documents/Claude/dossier/` (references `ocr-tool/scripts` engines)
**Platform:** macOS only (Apple Vision); local MCP server for Claude Desktop
**Date:** 2026-06-27

---

## 1. Purpose & targets

A local MCP server that turns a folder of source documents/messages into a
provenance-tagged **chronology**, an **organized + retrievable** file store, and
legal-ready **deliverables (exhibit list, digest, assembled exhibits)** — while
spending as few Claude context tokens as possible.

**Target 1 (primary): minimize Claude main-context tokens.**
Bulk (images, full text) stays on disk; only compact, distilled results cross the
MCP boundary into the conversation. The MCP tool-call boundary plays the role that
subagents played in Claude Code — the isolation layer Desktop otherwise lacks.

**Target 2 (secondary): organize the master/original files for easy later retrieval.**
Non-destructive; the manifest *is* the retrieval index (find without reading).

### Non-goals (v1)
- Not legal advice; outputs are drafting aids for a human (lawyer) to review.
- No remote/hosted deployment (kills the on-device/private property); Desktop-local only.
- No automatic contact with third parties — the server *suggests*, the user acts.

---

## 2. Architecture

```
sources/ (originals, untouched)
   │  ingest()
   ▼
on-device engines ──► ocr/  (text)          manifest.db  (facts, events, hashes,
   • ocr (Apple Vision, docs)                            provenance, flags)
   • screenreduce (Vision + boxes; capture/ax)
   • metadata extractors (fs/EXIF/PDF/eml/exports)
   • NSDataDetector (in-content dates)
   │
   ▼  (only compact results cross into context)
Claude (Desktop, in-conversation tool calls)
   • semantics: operative meaning, zone resolution, conflict/dedup adjudication,
     one-line relevance, narrative
   │  assemble()
   ▼
outputs/ (CHRONOLOGY.md, exhibit bundle, digests)  + STATUS.md
```

- **Folder convention** (the user's existing one): `sources/ → ocr/ → outputs/ + STATUS.md`, plus `manifest.db`.
- **Lean tool surface** — tool schemas have a fixed context cost, so keep tools few and descriptions tight.
- **Reuses existing engines** in `ocr-tool/scripts/`: `ocr`, `screenreduce`.
- **Server language:** Python (email/regex parsing, NSDataDetector via a small Swift
  helper, mlx for the v1.1 VLM rung, doc-generation libs, MCP SDK), shelling to the
  Swift Vision binaries. Manifest in **SQLite** (queryable) with JSON export.

---

## 3. Data model

### 3.1 Three-band indexing (extraction vs interpretation)
| Band | What | Who | Trust |
|------|------|-----|-------|
| **1 Structured-source metadata** | fs dates; image EXIF/GPS (png/jpg/tiff/heic, one CGImageSource path); PDF `/Info`; `.eml` headers + `Received` chain + threading; iMessage/WhatsApp **exports** | Server, deterministic | full (zone explicit/derivable) |
| **2 In-content dates** | dates/times in the text, via NSDataDetector | Server, deterministic (**v1, for tokens**) | candidate; flagged |
| **3 Operative meaning** | which date is operative, zone-from-context, conflict/dedup adjudication, relevance | Claude | interpretation |

> Band 2 is server-side in v1 specifically to protect Target 1: "Claude does band 2"
> means "Claude reads every document," the largest token cost in the system
> (est. ~175k vs ~10k for a 250-page corpus).

### 3.2 Four extraction rules (non-negotiable)
1. Preserve the **raw span + source label** for every datum.
2. **Never invent a timezone** — flag `zone: unknown`; derive from GPS when present.
3. **Keep date ranges whole** ("X to Y" → both X and Y).
4. **Never conflate** multiple timestamps (`fs.mtime` ≠ EXIF ≠ content ≠ sent/received).

### 3.3 Event record
```json
{
  "kind": "sent|received|created|captured|content|signed|effective|expires|…",
  "value_raw": "31 May 2026",
  "value_utc": "2026-05-31T00:00:00Z | null",
  "granularity": "year|month|day|second",
  "zone_status": "explicit|derived-gps|unknown",
  "source": "email.Date | email.Received | exif.DateTimeOriginal | pdf./Info | fs.birthtime | content@<offset> | export.line",
  "location": "page/offset/line",
  "resolution_method": "parsed|reinspect|corroborated|human-attested|model-inferred",
  "confidence": 0.0
}
```

### 3.4 Provenance tiers (ranked, for the document-backed-vs-asserted discipline)
`document-backed (machine-parsed)` > `human-attested` > `model-inferred` > `asserted`.

Email specifics: record `Date` (sender-claimed) **and** `Received` (server-stamped)
**separately**; agreement = corroboration, divergence = flag.
Exports (iMessage/WhatsApp): device-local time, **no zone** → `zone: unknown`; date
order is locale-dependent → infer locale from any day>12, else flag `order-ambiguous`.

---

## 4. Chronology

- **Per-artifact timeline** is the substrate (all of an artifact's own events).
- **Server-built merged ledger**: collect every event, sort by UTC, flag events that
  fall within a window of each other across artifacts (corroboration/conflict candidates).
  Surfaces the **artifact-date vs content-date divergence** ("later scan of an older doc").
- **Claude writes `outputs/CHRONOLOGY.md` narrative on demand only** (it costs tokens);
  it adjudicates dedup/conflict over the compact ledger.
- Ordering honesty: zone-unknown / date-only events carry uncertainty bands, never
  false second-precision.

---

## 5. Escalation ladder (uncertainty resolver)

Claude (main context) is the **most expensive rung in tokens** — so exhaust the
zero-main-token rungs first. Trigger (R0): Vision confidence `< 0.8` (tunable) /
absent field / ambiguous (locale).

| Rung | Method | Main-context cost | For |
|------|--------|-------------------|-----|
| **R1 Re-inspect** | higher DPI, deskew/rotate, contrast, crop-to-region, alt OCR language | 0 | legibility ("look closer") |
| **R2 Corroborate** | resolve from other extracted data / filename / sibling / parent email / recompute (e.g. total from line items) | 0 | ambiguity another datum settles |
| **R4a Human micro-assist** | open tight crops **natively (Preview/Quick Look)**, batched at end-of-run; user supplies value / constraint / **global clarification** | 0 (native pixels, ~3-token answer) | eye-legible but machine-uncertain |
| **R3 Local VLM** *(v1.1)* | on-device VLM for **coarse** judgments only (doc-type, signature present, rotation, "photo of a screen") — **never fine text** | 0 main-context | coarse visual |
| **R4 Recommend** | rescan higher-DPI / request native original / confirm orientation | 0 | provenance/quality gaps |
| **R5 Escalate to Claude** | minimal targeted question + crop/snippet only (never whole doc) | tokens | residual semantic |

- **v1 order:** R1 → R2 → R4a → R4/R5. (R3 added in v1.1 once we see how often R1/R2 suffice.)
- **Climb budget:** max 2 rungs or 5 s, then fall to R4/R5 with a note.
- **Each resolution records its rung** in `resolution_method` (feeds the provenance tier).

### 5.1 Smudge / illegible handling
- Detect via low confidence. Represent obscured regions **explicitly** (`[illegible@offset]`) — never silently drop or fill.
- "From context" has two meanings: **corroborating context** (another real source → document-backed, *prefer this*) vs **inferential context** (model guess → `model-inferred`, flagged, + R4 remediation). Inference is attached as a flagged hypothesis, never merged into the backed layer.
- **Human micro-assist (R4a)** is offered before "request clean copy": user is the arbiter of "easily by eye"; a human read becomes `human-attested`.

---

## 6. File organization (Target 2)

- **Originals are sacred:** byte-identical, never mutated. **SHA-256** at ingest (chain of custody + dedup key).
- **Non-destructive arrangement:** organized tree built via **symlinks** (default; no duplication, originals never move) + manifest records `original_path → organized_path` (reversible/auditable). Real copies optional.
- **Dedup:** identical SHA-256 → one canonical, rest `duplicate_of` (fixes the known fragmentation across Downloads/old/etc.).
- **Misfile flag:** extracted title/parties ≠ filename → flag `filename≠content`; Claude adjudicates only flagged ones (catches the "CAS HOA = Hudson" case).
- **Naming (provenance-driven):** `YYYY-MM-DD__doctype__party__shorttitle__<hash8>.ext`.
  Date fallback chain (never guessed): **operative content date → artifact created (pdf/EXIF) → fs.birthtime**; chosen date carries its provenance.
- **Manifest is the retrieval index:** `find()` returns paths + tiny snippets, never dumps docs. Finding is free; opening costs tokens on demand.
- **Idempotent/resumable** (skip up-to-date, like `ocr-batch.sh`).

---

## 7. Metering & savings

- `metrics.jsonl`, one row per local op, **tagged with a task id**:
  `{ts, task, file, rung, model, prompt_tok, gen_tok, ms, peak_mem}`.
- **On-device cost ledger** (unit per stage; never summed across currencies):
  VLM → **tokens** (exact from `mlx-vlm`); OCR/parse → pages/images/ms.
  *On-device VLM tokens ≠ Claude tokens (different tokenizer).*
- **`savings(task)`** report — **shows BOTH baselines**:
  - `baseline_raw` = Σ image tokens (~1,600/page after resize)
  - `baseline_text` = Σ text tokens (~chars/4)
  - `actual` = Claude-facing tokens (exact via token-count: ledger + slice reads + escalations)
  - `saved = baseline − actual`, ratio, breakdown.
  - On-device block shown **separately**.
  - Caveats surfaced: baselines are estimated/counterfactual; image const ≈1,600; savings scale with how much targeted reading the task triggers.
  - **Isolate ingestion savings** from analysis the user wanted anyway.

---

## 8. Output / deliverable assembly

**Principle (output-side mirror of ingest):** Claude emits a **spec** (references +
crop coords + captions); a local assembler pulls pixels from the **originals**. Zero
image tokens in either direction; full-resolution; chain of custody preserved.

- **Bridge:** OCR/`screenreduce` bounding boxes let Claude reference a region **by
  extracted text or box** — never by viewing pixels.
  ```json
  { "type":"figure", "source":"sources/lease.pdf", "page":3,
    "region": {"by_text":"Total due"},   // or [x,y,w,h] or "full_page"
    "caption":"Exhibit C — West 718 lease, p.3", "provenance":"sha256:a1b2…" }
  ```
- Visual crop decisions resolved **on-device** (escalation ladder); Claude references the label.
- Built on the existing `docx`/`pptx`/`pdf` skills, fed **crops-from-originals** (PDFKit/CGImage/sips).
- **Legal default: full-page exhibit + highlight callout** (preserves the unaltered original); tight-crop option for slides/reports.
- **Auto-provenance captions** (source + SHA-256) on every embed.
- **QA without round-trip:** show embedded crops **natively (Preview)** for the user's eye, not back through Claude.

### 8.1 Two primary deliverables
1. **Document list / exhibit schedule (outline)** — deterministic projection of the
   manifest; **~0 Claude tokens**. Auto-numbered, **chronological order (default)**
   off the merged ledger, by-type alternate. Each row: date+provenance, source, pages, hash.
2. **Digest** — server-built **fact skeleton** + typed **one-line relevance placeholders**
   Claude fills (often from ledger facts with **no slice read**; escalate to a slice
   only when facts are insufficient). The page **self-documents** `[doc-backed]` vs
   `{{synopsis}}` lines. Placeholder fills are flagged as drafting aids and run through
   `verify()`.

---

## 9. Tool surface (lean)

| Tool | Does (on the Mac) | Returns to conversation |
|------|-------------------|-------------------------|
| `ingest(folder, opts?)` | OCR + band1/band2 + hash + manifest | counts, flags, gaps (compact) |
| `find(query)` | manifest search | `[{path, exhibit_id, date, type, snippet}]` |
| `get(ref)` | targeted slice (lines / region / by_text) | just that slice |
| `verify(value, doc)` | string-presence check | `{present, locations[]}` |
| `chronology(scope, view)` | merged or per-artifact ledger | compact ledger + conflict flags |
| `organize(mode?)` | dedup + naming + symlink tree + misfile flags (non-destructive) | manifest diff + flags to adjudicate |
| `assist_queue()` / `assist_resolve(answers)` | open batched crops in Preview / record answers | pending list / confirmations |
| `exhibit_list(order)` | render schedule from manifest | the outline |
| `digest(scope)` | fact skeleton + placeholders | skeleton to fill |
| `assemble(spec, format)` | build PDF/DOCX/PPTX from originals | output path(s) |
| `savings(task)` / `stats(task)` | metering rollup | dual-baseline report |

---

## 10. Guardrails

- Claude **suggests** remediation to the **user**; never auto-contacts third parties.
- Outputs are **drafting aids requiring review**; **not legal advice**; lawyer signs off.
- Originals **never modified**; all arrangement reversible via manifest.
- Desktop **tool-approval prompts** are welcome (a wanted gate for legal work).
- Every interaction is a **typed, logged tool call** (auditable), not a freeform shell.

---

## 11. Setup, permissions, limits

- Register once in `claude_desktop_config.json`; Desktop **auto-launches** the stdio server; one restart.
- **No Full Disk Access needed in v1** (exports parsed from `sources/`, not native DBs).
- **macOS only** (Apple Vision).
- **Mobile:** the conversation syncs, but a *local* server's tools (and native-Preview
  micro-assist) only execute on the **Desktop machine running the server**.

---

## 12. Phasing

- **v1:** band1+band2 extraction · per-artifact + merged ledger · organization
  (dedup/misfile/symlink/manifest) · `find`/`get`/`verify`/`chronology` · exhibit list +
  one-line digest · `assemble` (full-page+callout) · metering + dual-baseline savings ·
  escalation R1/R2/R4a/R4/R5 · human micro-assist (Preview) · guardrails.
- **v1.1:** R3 local VLM rung (coarse-only) — gated on how often R1/R2 already resolve.
- **v2:** native iMessage `chat.db` (behind Full Disk Access) · multiple org views ·
  paragraph synopses on selected exhibits · optional remote deployment (trades away on-device).

---

## 13. Resolved at sign-off (2026-06-27)
1. **Stack:** Python MCP server shelling to the Swift Vision binaries; manifest in **SQLite**. ✅
2. **Tuning:** confidence trigger **0.8**, climb budget **2 rungs / 5 s** — starting values; `metrics.jsonl` retained to retune from real output. ✅
3. **Name:** **Dossier**. ✅
4. **Home:** own directory `~/Documents/Claude/dossier/`, referencing `ocr-tool/scripts` engines. ✅

## 14. v1 build order (milestones)
1. **Foundation** *(this milestone)* — project scaffold, manifest schema, deterministic extractors: `meta` (fs/PDF/image+GPS), `datedetect` (band 2, rules baked in), `eml` parser.
2. **Ingest** — orchestrate hash + `ocr` + extractors → write `ocr/` + manifest rows; idempotent.
3. **Chronology** — per-artifact timelines + merged UTC-sorted ledger with conflict flags.
4. **Organize** — dedup, misfile flags, provenance naming, symlink tree, manifest-as-index.
5. **Query tools** — `find` / `get` / `verify`.
6. **Deliverables** — `exhibit_list`, `digest`, `assemble` (from originals).
7. **Escalation + human micro-assist** (R1/R2/R4a/R4/R5) + metering + `savings`.
8. **MCP wrapper** — expose the lean tool surface to Claude Desktop; `claude_desktop_config.json`.
9. **v1.1** — R3 local VLM rung.

## 15. Benchmark-driven hardening (from run1, 2026-06-27)
First real-corpus run validated the token thesis (95% / 85% saved; full-text baseline
alone exceeds a context window) and exposed concrete fixes — fold into milestones 2/4/7:
1. **Own-OCR; distrust inherited `ocr/`.** A prior-pass OCR garbled the lease's page-1
   form fields (66k chars → 0 dates); our high-DPI re-OCR read them cleanly. Re-OCR with
   our engine; treat inherited text as untrusted.
2. **R1 trigger on *sparse* extraction**, not just low confidence. "Long doc, ~no events"
   is itself a re-inspect signal → high-DPI re-OCR.
3. **Per-document locale inference.** An unambiguous numeric date (day>12, e.g. `05/31/2026`)
   pins the doc's MM/DD vs DD/MM; apply to ambiguous siblings (`05/09/2025`→May 9); else
   flag `order-ambiguous`. 356 events affected in run1.
4. **Format-agnostic recall.** Match numeric *and* text date forms; FTS/anchor lookups must
   not assume one format.
5. **DocuSign awareness.** Detect `Docusign Envelope ID`; split collated PDFs by envelope;
   extract page-1 form fields per sub-document; capture DocuSign certificate signing
   timestamps (authoritative, timezone-explicit).
6. **Form-field extraction (band 1.5).** Deterministic `Label: value` pairs ("Beginning Date
   of Lease: …") give semantically-typed dates — stronger than free-text detection.
7. **Persist `value_wall`** (event column) so zone-unknown wall-clock survives ingest.
8. **`xlsx` text extraction**; the 26 sparse-OCR artifacts in run1 are R1/R4a candidates.
