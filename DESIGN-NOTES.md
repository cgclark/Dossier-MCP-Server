# Dossier — design notes

Running design notes for Dossier. Each note marked with a freshness caveat where it
depends on fast-moving externals.

---

## Windows portability
> ✅ Implemented 2026-08 on Windows 11 ARM64 (Copilot+ PC). Below is what was tried and
> what actually shipped, kept for the next platform port rather than as a still-open plan.

Dossier's Vision/Swift layer is macOS-locked; the Python layer is portable. On Windows,
`server/*.py` is untouched except a small platform dispatch; `engines/`/`helpers/` gained
`*_win.py` siblings implementing the same CLI contract in pure Python.

**What shipped, and why (superseding the original recommendation below):**
- **OCR → Windows AI OCR** (`winsdk`'s projection of `Windows.Media.Ocr`), not RapidOCR.
  RapidOCR was the original pick for lower implementation risk, but its native deps
  (`opencv-python`, `pyclipper`, `Shapely`) have **zero ARM64 Windows wheels** — installing
  them needs a full C++ build toolchain (MSVC + CMake), which is a much bigger ask than a
  pip install. Windows AI OCR turned out to have complete ARM64 wheels and no compiler
  requirement, so it flipped from "higher-risk" to "the only realistic option" once actually
  tested. Note: the `winrt-Windows.Media.Ocr` PyPI package (the one this doc originally
  pointed at) is missing OcrEngine's static factory methods in its 3.2.1 build — use the
  `winsdk` package instead, which has the full API surface.
- **summarize → Claude Haiku over the Anthropic API**, not a local model. Apple's Foundation
  Models has no Windows on-device equivalent, and there's no headless `claude` CLI to shell
  out to on a machine running the packaged Claude Desktop app (that's a GUI binary, not a
  scriptable one) — so this is the one step where Windows document text leaves the device.
  Requires `ANTHROPIC_API_KEY`; degrades to `{"available": false}` without it.
- **webcapture → Playwright driving the system-installed Edge/Chrome** (`channel="msedge"`),
  not a downloaded Chromium. Zero-download, since Edge ships with Windows.
- **assemble → `pypdf` + `reportlab`.** Matches the original recommendation.
- Windows console text defaults to the system codepage (cp1252), not UTF-8 — every script
  that prints non-ASCII (arrows, checkmarks, curly quotes the OCR text itself contains)
  needs `sys.stdout.reconfigure(encoding="utf-8")`, and every `subprocess.run(..., text=True)`
  that captures one of these scripts' output needs `encoding="utf-8"` explicitly, or the
  parent decodes with the wrong codec. This bit multiple files during the port
  (`ingest.py`, `organize.py`, all the new `*_win.py` scripts) — worth remembering for any
  future Windows work in this repo, native binary or not.

The rest of this doc is kept as-drafted below (pre-implementation OCR survey).

### On-device OCR options (peers to Apple Vision), by hardware
| Option | Runs on | Needs | Vs. Apple Vision |
|---|---|---|---|
| **Windows AI OCR** (Text Recognition, Windows AI Foundry / Copilot Runtime) | Copilot+ PCs — ARM Snapdragon X, *and* newer Intel Lunar Lake / AMD Strix w/ NPU | NPU (~40+ TOPS); built-in | **True peer** — on-device, NPU, zero-setup |
| **Windows.Media.Ocr** (legacy WinRT) | any Win10/11, ARM/Intel | none (CPU) | convenient but a notch below on scans |
| **PaddleOCR / RapidOCR** (PP-OCRv4/v5, ONNX) | any Windows, CPU or any dGPU | pip/ONNX | **matches/beats Vision**, esp. multilingual; best cross-hardware |
| **Florence-2** (MS vision foundation model) | any, CPU/GPU via ONNX+DirectML | ONNX | OCR + detection + caption in one |
| **EasyOCR / docTR / TrOCR** | GPU-friendly | PyTorch/ONNX | good DL OCR; heavier |
| **Tesseract** | any, CPU | trivial | baseline, weaker |

- GPU abstraction: **ONNX Runtime + DirectML** → runs on NVIDIA / AMD / Intel Arc equally (not CUDA-locked).
- Small **VLMs** remain weak for *precise text* on Windows too (same as our benchmark) — use a dedicated OCR engine; reserve VLMs for coarse visual judgment.

### Recommendation by tier
- **Copilot+ PC (ARM or NPU Intel/AMD):** Windows AI OCR — the Vision-equivalent, on-device, no setup.
- **Any Windows, no GPU:** RapidOCR (CPU) or `Windows.Media.Ocr`.
- **Has dGPU:** PaddleOCR (or Florence-2) on GPU via DirectML/CUDA — fastest + strongest.

### Dossier port mapping — as shipped
| macOS-locked component | Windows substitute |
|---|---|
| `ocr` (Vision) | `winsdk` (Windows AI OCR) + PyMuPDF for PDF rasterization/text-layer |
| `screenreduce` (Vision) | not ported — confirmed unused by any `server/*.py` call site |
| `datedetect` (NSDataDetector) | Python `dateparser` (`languages=["en"]`, `STRICT_PARSING`) |
| `meta` (CGImageSource EXIF, PDFKit) | Pillow (EXIF) + PyMuPDF (`/Info`) |
| `assemble` (PDFKit) | `pypdf` + `reportlab` |
| `webcapture` (WKWebView) | Playwright, `channel="msedge"` (system browser, no download) |
| `summarize` (Foundation Models) | Claude Haiku via the Anthropic API (network — see above) |
| **Forced raster render (R1)** | PyMuPDF page render → Windows AI OCR |
| `.doc`/`.rtf`/`.docx`→text (`textutil`) | `python-docx` / `striprtf`; `.doc` is a documented gap |

Portable as-is (Python, no changes beyond a platform-dispatch shim): `eml.py`, `extract.py`,
`ingest.py`, `chronology.py`, `organize.py`, `query.py`, `cluster.py`, `deliverables.py`,
`savings.py`, SQLite manifest.
