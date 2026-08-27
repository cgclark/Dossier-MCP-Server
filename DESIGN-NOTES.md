# Dossier — design notes

Running design notes for Dossier. Each note marked with a freshness caveat where it
depends on fast-moving externals.

---

## Windows portability
> ⚠️ REFRESH WHEN IMPLEMENTED — captured 2026-06; on-device OCR APIs/models move fast.
> Re-verify Windows AI OCR availability, PaddleOCR version, and DirectML support before building.

Dossier's Vision/Swift layer is macOS-locked; the Python layer is portable. To run on
Windows, swap the OCR/vision + date-detection engines; keep everything else.

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

### Dossier port mapping (~70% already portable)
| macOS-locked component | Windows substitute |
|---|---|
| `ocr` / `screenreduce` (Vision) | Windows AI OCR **or** PaddleOCR/RapidOCR |
| `datedetect` (NSDataDetector) | Python `dateparser` / `duckling` |
| `meta` (CGImageSource EXIF, PDFKit) | Pillow / `exifread` + PyMuPDF |
| **Forced raster render (R1)** | PyMuPDF page render → chosen OCR engine |

Portable as-is (Python): `eml.py`, `extract.py`, `ingest.py`, `chronology.py`,
`organize.py`, `query.py`, SQLite manifest.
