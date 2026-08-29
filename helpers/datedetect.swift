// datedetect.swift — band-2 deterministic in-content date extractor (Dossier).
// Runs Apple's NSDataDetector over OCR text and emits date candidates as JSON.
// Compile: swiftc -O datedetect.swift -o datedetect
//
//   datedetect <textfile>     (or: datedetect -   to read stdin)
//
// Rules baked in (SPEC §3.2):
//  • keep ranges whole — "X to Y" yields BOTH endpoints (via match.duration)
//  • never invent a timezone — if the detector has no zone, value_utc is null and
//    we report the wall-clock the text actually stated (no offset asserted)
//  • preserve the raw span + character offset (provenance: content@<offset>)

import Foundation

// read input
let a = Array(CommandLine.arguments.dropFirst())
let text: String
if let p = a.first, p != "-" {
    // A file arg was given — fail loudly if it doesn't exist (never silently block on stdin,
    // which hangs forever in the background when a path-with-spaces gets split).
    guard FileManager.default.fileExists(atPath: p) else {
        FileHandle.standardError.write("error: no such file: \(p)\n".data(using: .utf8)!); exit(2)
    }
    text = (try? String(contentsOfFile: p, encoding: .utf8)) ?? ""
} else {
    text = String(data: FileHandle.standardInput.readDataToEndOfFile(), encoding: .utf8) ?? ""
}

let isoAbs = ISO8601DateFormatter(); isoAbs.formatOptions = [.withInternetDateTime]
// wall-clock formatter in the machine zone — recovers the stated local time WITHOUT
// asserting an offset (we emit it as value_wall, never as value_utc).
let wall = DateFormatter()
wall.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
wall.timeZone = TimeZone.current

func granularity(_ s: String) -> String {
    let l = s.lowercased()
    if l.range(of: #"\d{1,2}:\d{2}"#, options: .regularExpression) != nil || l.contains("am") || l.contains("pm") { return "second" }
    if l.range(of: #"\b\d{1,2}\b"#, options: .regularExpression) != nil { return "day" }
    if l.range(of: #"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"#, options: .regularExpression) != nil { return "month" }
    if l.range(of: #"\b\d{4}\b"#, options: .regularExpression) != nil { return "year" }
    return "day"
}

func record(date: Date, zone: TimeZone?, span: String, offset: Int, kind: String) -> [String: Any] {
    var r: [String: Any] = [
        "kind": kind, "value_raw": span, "granularity": granularity(span),
        "source": "content@\(offset)", "provenance": "document-backed",
    ]
    if let z = zone {
        r["zone_status"] = "explicit"
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime]; f.timeZone = z
        r["value_utc"] = isoAbs.string(from: date)   // absolute instant is sound when zone known
    } else {
        r["zone_status"] = "unknown"
        r["value_utc"] = NSNull()                    // never invent a zone
        r["value_wall"] = wall.string(from: date)    // the stated wall-clock, offset-free
    }
    return r
}

var out: [[String: Any]] = []
let det = try NSDataDetector(types: NSTextCheckingResult.CheckingType.date.rawValue)
let ns = text as NSString
det.enumerateMatches(in: text, range: NSRange(location: 0, length: ns.length)) { m, _, _ in
    guard let m = m, let d = m.date else { return }
    let span = ns.substring(with: m.range)
    let off = m.range.location
    if m.duration > 0 {   // a range: emit both endpoints
        out.append(record(date: d, zone: m.timeZone, span: span, offset: off, kind: "content-range-start"))
        let end = d.addingTimeInterval(m.duration)
        out.append(record(date: end, zone: m.timeZone, span: span, offset: off, kind: "content-range-end"))
    } else {
        out.append(record(date: d, zone: m.timeZone, span: span, offset: off, kind: "content"))
    }
}

let data = try! JSONSerialization.data(withJSONObject: out, options: [.prettyPrinted])
FileHandle.standardOutput.write(data); print("")
