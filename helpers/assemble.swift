// assemble.swift — Dossier Milestone 6 (assemble exhibit bundle from ORIGINALS).
// Reads a JSON spec; emits a single PDF: a schedule cover page + each exhibit's
// original pages (full-fidelity, pulled from source — chain of custody preserved).
// Native PDFKit, no pip deps. Compile: swiftc -O assemble.swift -o assemble
//
//   assemble <spec.json> <out.pdf>
//
// spec.json: {"title":"...","exhibits":[{"ex":"A","date":"..","desc":"..","source":"/abs.pdf",
//             "pages":"all"|"1"|"1-3","sha":"…"}]}

import Foundation
import PDFKit
import AppKit
import CoreText

struct Ex: Decodable { let ex: String; let date: String?; let desc: String?
                       let source: String; let pages: String?; let sha: String? }
struct Spec: Decodable { let title: String; let exhibits: [Ex] }

func die(_ s: String) -> Never { FileHandle.standardError.write((s+"\n").data(using:.utf8)!); exit(2) }
let a = CommandLine.arguments
guard a.count == 3 else { die("usage: assemble <spec.json> <out.pdf>") }
guard let spec = try? JSONDecoder().decode(Spec.self, from: Data(contentsOf: URL(fileURLWithPath: a[1])))
else { die("bad spec.json") }

let out = PDFDocument()

// ---- cover / schedule page (drawn text) ----
func coverPage(_ spec: Spec) -> PDFPage? {
    let pw: CGFloat = 612, ph: CGFloat = 792
    let data = NSMutableData()
    var box = CGRect(x: 0, y: 0, width: pw, height: ph)
    guard let cons = CGDataConsumer(data: data),
          let ctx = CGContext(consumer: cons, mediaBox: &box, nil) else { return nil }
    ctx.beginPDFPage(nil)
    func draw(_ s: String, _ x: CGFloat, _ y: CGFloat, _ size: CGFloat, bold: Bool = false) {
        let f = bold ? NSFont.boldSystemFont(ofSize: size) : NSFont.systemFont(ofSize: size)
        let line = CTLineCreateWithAttributedString(NSAttributedString(string: s,
                    attributes: [.font: f, .foregroundColor: NSColor.black]))
        ctx.textPosition = CGPoint(x: x, y: y); CTLineDraw(line, ctx)
    }
    draw(spec.title, 54, ph - 70, 18, bold: true)
    draw("Exhibit Schedule", 54, ph - 96, 13)
    var y = ph - 130
    for e in spec.exhibits {
        let row = "\(e.ex).  \(e.date ?? "")   \((e.desc ?? "").prefix(60))"
        draw(row, 54, y, 10)
        if let sha = e.sha { draw("SHA-256 \(sha.prefix(12))…", 360, y, 8) }
        y -= 18; if y < 54 { break }
    }
    ctx.endPDFPage(); ctx.closePDF()
    return PDFDocument(data: data as Data)?.page(at: 0)
}

var idx = 0
if let cp = coverPage(spec) { out.insert(cp, at: idx); idx += 1 }

// ---- append each exhibit's original pages ----
func pageRange(_ s: String?, count: Int) -> [Int] {
    guard let s = s, s != "all" else { return Array(0..<count) }
    let p = s.split(separator: "-").compactMap { Int($0) }
    if p.count == 2 { return Array((p[0]-1)...(min(p[1], count)-1)) }
    if p.count == 1 { return [p[0]-1] }
    return Array(0..<count)
}

for e in spec.exhibits {
    guard let src = PDFDocument(url: URL(fileURLWithPath: e.source)) else {
        FileHandle.standardError.write("  ! skip \(e.ex): cannot open \(e.source)\n".data(using:.utf8)!); continue
    }
    for p in pageRange(e.pages, count: src.pageCount) {
        if let pg = src.page(at: p) { out.insert(pg, at: idx); idx += 1 }
    }
}

if out.write(to: URL(fileURLWithPath: a[2])) {
    print("assembled \(idx) pages → \(a[2])")
} else { die("write failed") }
