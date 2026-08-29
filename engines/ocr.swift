// ocr.swift — local, offline OCR for macOS using Apple's Vision framework.
// Renders PDF pages (or loads an image) and recognizes text fully on-device.
// No network, no Homebrew deps. Compile: swiftc -O ocr.swift -o ocr
//
// Usage:
//   ocr <input.pdf | input.png/jpg/tiff> [-o out.txt] [--dpi 300]
//       [--lang en-US,de-DE] [--fast] [--page-sep] [--quiet]
//
// Output: recognized text to stdout (or -o file). With --page-sep, pages are
// delimited by a "\f===== PAGE n =====" marker so downstream tools can split.

import Foundation
import Vision
import PDFKit
import CoreGraphics
import ImageIO

// ---- argument parsing -------------------------------------------------------
var input: String?
var output: String?
var dpi: CGFloat = 300
var langs: [String] = []          // empty => Vision auto
var accurate = true
var pageSep = false
var quiet = false
var forceVision = false           // skip the embedded text layer; always render+Vision
var pageLo = 1                     // 1-indexed page range (default all)
var pageHi = Int.max

var i = 1
let argv = CommandLine.arguments
func fail(_ msg: String) -> Never { FileHandle.standardError.write((msg + "\n").data(using: .utf8)!); exit(2) }

while i < argv.count {
    let a = argv[i]
    switch a {
    case "-o", "--out":     i += 1; output = i < argv.count ? argv[i] : nil
    case "--dpi":           i += 1; dpi = CGFloat(Double(argv[i]) ?? 300)
    case "--lang":          i += 1; langs = argv[i].split(separator: ",").map(String.init)
    case "--fast":          accurate = false
    case "--page-sep":      pageSep = true
    case "--quiet":         quiet = true
    case "--force-vision":  forceVision = true
    case "--pages":         i += 1
                            let parts = argv[i].split(separator: "-").compactMap { Int($0) }
                            if parts.count == 2 { pageLo = parts[0]; pageHi = parts[1] }
                            else if parts.count == 1 { pageLo = parts[0]; pageHi = parts[0] }
    case "-h", "--help":
        print("usage: ocr <input.pdf|image> [-o out.txt] [--dpi N] [--lang a,b] [--fast] [--page-sep] [--force-vision] [--pages a-b] [--quiet]")
        exit(0)
    default:
        if input == nil { input = a } else { fail("unexpected arg: \(a)") }
    }
    i += 1
}
guard let inPath = input else { fail("error: no input file. See --help.") }
guard FileManager.default.fileExists(atPath: inPath) else { fail("error: no such file: \(inPath)") }

func log(_ s: String) { if !quiet { FileHandle.standardError.write((s + "\n").data(using: .utf8)!) } }

// ---- Vision OCR on a single CGImage ----------------------------------------
func recognize(_ cg: CGImage) -> String {
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = accurate ? .accurate : .fast
    req.usesLanguageCorrection = true
    if !langs.isEmpty { req.recognitionLanguages = langs }
    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    do { try handler.perform([req]) } catch { log("  ! vision error: \(error)"); return "" }
    let obs = req.results ?? []
    return obs.compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
}

// ---- normalize any CGImage into a clean device-RGB bitmap -------------------
// Vision silently returns 0 results for some color profiles / bit depths /
// alpha configs (e.g. profiled PNGs). Redrawing into device RGB fixes it —
// this is exactly what the PDF render path does implicitly.
func normalize(_ cg: CGImage) -> CGImage {
    let w = cg.width, h = cg.height
    guard w > 0, h > 0,
          let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8,
                              bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return cg }
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    ctx.draw(cg, in: CGRect(x: 0, y: 0, width: w, height: h))
    return ctx.makeImage() ?? cg
}

// ---- render one PDF page to a CGImage at target DPI -------------------------
func render(_ page: PDFPage, dpi: CGFloat) -> CGImage? {
    let rect = page.bounds(for: .mediaBox)
    let scale = dpi / 72.0
    let w = Int((rect.width  * scale).rounded())
    let h = Int((rect.height * scale).rounded())
    guard w > 0, h > 0,
          let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8,
                              bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return nil }
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    ctx.scaleBy(x: scale, y: scale)
    ctx.translateBy(x: -rect.origin.x, y: -rect.origin.y)
    page.draw(with: .mediaBox, to: ctx)
    return ctx.makeImage()
}

// ---- drive: PDF (multi-page) or single image --------------------------------
var pages: [String] = []
let ext = (inPath as NSString).pathExtension.lowercased()

if ext == "pdf" {
    guard let doc = PDFDocument(url: URL(fileURLWithPath: inPath)) else { fail("error: cannot open PDF") }
    log("OCR: \(doc.pageCount) page(s) @ \(Int(dpi)) DPI")
    for p in 0..<doc.pageCount {
        if (p + 1) < pageLo || (p + 1) > pageHi { continue }   // page-granular range
        guard let page = doc.page(at: p) else { continue }
        // Embedded text layer is free/exact — but it scrambles label↔value adjacency on
        // form/DocuSign PDFs, so --force-vision bypasses it and OCRs the rendered page.
        if !forceVision, let s = page.string, s.trimmingCharacters(in: .whitespacesAndNewlines).count > 20 {
            log("  page \(p+1): embedded text")
            pages.append(s); continue
        }
        guard let cg = render(page, dpi: dpi) else { log("  page \(p+1): render failed"); pages.append(""); continue }
        log("  page \(p+1): vision OCR")
        pages.append(recognize(cg))
    }
} else {
    guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: inPath) as CFURL, nil),
          let raw = CGImageSourceCreateImageAtIndex(src, 0, nil) else { fail("error: cannot load image") }
    log("OCR: 1 image")
    pages.append(recognize(normalize(raw)))
}

// ---- emit -------------------------------------------------------------------
let text: String
if pageSep {
    text = pages.enumerated().map { "\u{0C}===== PAGE \($0.offset + 1) =====\n\($0.element)" }.joined(separator: "\n")
} else {
    text = pages.joined(separator: "\n\n")
}

if let out = output {
    try? text.write(toFile: out, atomically: true, encoding: .utf8)
    log("wrote \(out) (\(text.count) chars)")
} else {
    print(text)
}
