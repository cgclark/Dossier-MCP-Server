// meta.swift — band-1 deterministic provenance extractor (Dossier).
// Given a file, emit structured metadata as JSON: SHA-256, fs dates, and
// type-specific embedded metadata (PDF /Info; image EXIF/GPS/TIFF). No LLM.
// Compile: swiftc -O meta.swift -o meta
//
//   meta <file>
//
// Rules honored here (see SPEC §3.2): never invent a timezone — image
// DateTimeOriginal has no zone unless OffsetTime* present, so it is reported with
// zone_status accordingly; GPS is emitted so a zone can later be *derived*, not guessed.

import Foundation
import CryptoKit
import ImageIO
import PDFKit

func die(_ s: String) -> Never { FileHandle.standardError.write((s+"\n").data(using:.utf8)!); exit(2) }
let args = Array(CommandLine.arguments.dropFirst())
guard let path = args.first else { die("usage: meta <file>") }
let url = URL(fileURLWithPath: path)
guard FileManager.default.fileExists(atPath: path) else { die("no such file: \(path)") }

let iso = ISO8601DateFormatter()
iso.formatOptions = [.withInternetDateTime]
func isoUTC(_ d: Date?) -> Any { d.map { iso.string(from: $0) } ?? NSNull() }

var out: [String: Any] = ["path": path]

// --- SHA-256 (chain of custody + dedup key) ---
if let data = try? Data(contentsOf: url, options: .mappedIfSafe) {
    out["sha256"] = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    out["bytes"] = data.count
}

// --- filesystem dates ---
if let attrs = try? FileManager.default.attributesOfItem(atPath: path) {
    out["fs"] = [
        "birth": isoUTC(attrs[.creationDate] as? Date),
        "mtime": isoUTC(attrs[.modificationDate] as? Date),
    ]
}

let ext = url.pathExtension.lowercased()

// --- PDF /Info + page count ---
if ext == "pdf", let doc = PDFDocument(url: url) {
    var pdf: [String: Any] = ["pages": doc.pageCount]
    if let a = doc.documentAttributes {
        if let d = a[PDFDocumentAttribute.creationDateAttribute] as? Date { pdf["created"] = isoUTC(d) }
        if let d = a[PDFDocumentAttribute.modificationDateAttribute] as? Date { pdf["modified"] = isoUTC(d) }
        if let s = a[PDFDocumentAttribute.titleAttribute] as? String, !s.isEmpty { pdf["title"] = s }
        if let s = a[PDFDocumentAttribute.authorAttribute] as? String, !s.isEmpty { pdf["author"] = s }
        if let s = a[PDFDocumentAttribute.producerAttribute] as? String, !s.isEmpty { pdf["producer"] = s }
    }
    out["kind"] = "pdf"
    out["pdf"] = pdf
}

// --- image EXIF / GPS / TIFF ---
if ["png","jpg","jpeg","tiff","tif","heic","heif"].contains(ext),
   let src = CGImageSourceCreateWithURL(url as CFURL, nil),
   let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any] {
    var img: [String: Any] = [:]
    img["pixelW"] = props[kCGImagePropertyPixelWidth]
    img["pixelH"] = props[kCGImagePropertyPixelHeight]

    if let exif = props[kCGImagePropertyExifDictionary] as? [CFString: Any] {
        // DateTimeOriginal is local-with-no-zone unless OffsetTimeOriginal accompanies it.
        if let dto = exif[kCGImagePropertyExifDateTimeOriginal] as? String {
            img["DateTimeOriginal"] = dto
            if let off = exif[kCGImagePropertyExifOffsetTimeOriginal] as? String {
                img["OffsetTimeOriginal"] = off; img["zone_status"] = "explicit"
            } else {
                img["zone_status"] = "unknown"   // do NOT fabricate a zone
            }
        }
    }
    if let tiff = props[kCGImagePropertyTIFFDictionary] as? [CFString: Any] {
        if let m = tiff[kCGImagePropertyTIFFMake] as? String { img["make"] = m }
        if let m = tiff[kCGImagePropertyTIFFModel] as? String { img["model"] = m }
        if let o = tiff[kCGImagePropertyTIFFOrientation] { img["orientation"] = o }
        if let d = tiff[kCGImagePropertyTIFFDateTime] as? String { img["DateTime"] = d }
    }
    if let gps = props[kCGImagePropertyGPSDictionary] as? [CFString: Any],
       let lat = gps[kCGImagePropertyGPSLatitude] as? Double,
       let lon = gps[kCGImagePropertyGPSLongitude] as? Double {
        let latRef = (gps[kCGImagePropertyGPSLatitudeRef] as? String) ?? "N"
        let lonRef = (gps[kCGImagePropertyGPSLongitudeRef] as? String) ?? "E"
        img["gps"] = ["lat": latRef == "S" ? -lat : lat,
                      "lon": lonRef == "W" ? -lon : lon]  // → zone derivable later, not guessed
    }
    out["kind"] = "image"
    out["image"] = img
}

if out["kind"] == nil { out["kind"] = (ext == "eml") ? "email" : "other" }

let data = try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys, .prettyPrinted])
FileHandle.standardOutput.write(data); print("")
