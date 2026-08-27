// screenreduce.swift — on-device "vision reduction": turn pixels into compact text/JSON
// so a screenshot becomes ~tens of tokens instead of ~1,500–2,500 image tokens.
// Fully local: Apple Vision (OCR, tier 1) + Accessibility tree (semantic UI, tier 0).
// Compile: swiftc -O screenreduce.swift -o screenreduce
//
// Subcommands:
//   screenreduce ocr <image>        # tier 1: OCR an image -> {w,h,lines[],text}
//   screenreduce capture [-R x,y,w,h]   # grab screen (via /usr/sbin/screencapture) then ocr
//   screenreduce ax                 # tier 0: dump frontmost app's accessibility tree
//
// Output: compact JSON on stdout. Coordinates are top-left pixel ints.

import Foundation
import Vision
import ImageIO
import CoreGraphics
import AppKit
import ApplicationServices

func die(_ s: String) -> Never { FileHandle.standardError.write((s+"\n").data(using:.utf8)!); exit(2) }
func emit(_ obj: Any) {
    let d = try! JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys])
    FileHandle.standardOutput.write(d); print("")
}

// ---- normalize any CGImage into clean device-RGB (Vision is picky) ----------
func normalize(_ cg: CGImage) -> CGImage {
    let w = cg.width, h = cg.height
    guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
            space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return cg }
    ctx.setFillColor(CGColor(red:1,green:1,blue:1,alpha:1)); ctx.fill(CGRect(x:0,y:0,width:w,height:h))
    ctx.draw(cg, in: CGRect(x:0,y:0,width:w,height:h))
    return ctx.makeImage() ?? cg
}

func loadCG(_ path: String) -> CGImage {
    guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let cg = CGImageSourceCreateImageAtIndex(src, 0, nil) else { die("cannot load image: \(path)") }
    return normalize(cg)
}

// ---- tier 1: OCR an image to compact line records ---------------------------
func ocr(_ path: String) {
    let cg = loadCG(path)
    let W = cg.width, H = cg.height
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = true
    try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
    var lines: [[String: Any]] = []
    var plain: [String] = []
    for o in (req.results ?? []) {
        guard let c = o.topCandidates(1).first else { continue }
        let b = o.boundingBox  // normalized, origin bottom-left
        let x = Int((b.minX * CGFloat(W)).rounded())
        let y = Int(((1 - b.maxY) * CGFloat(H)).rounded())
        let w = Int((b.width * CGFloat(W)).rounded())
        let h = Int((b.height * CGFloat(H)).rounded())
        lines.append(["t": c.string, "box": [x, y, w, h], "conf": Double(round(c.confidence*100))/100])
        plain.append(c.string)
    }
    emit(["w": W, "h": H, "lines": lines, "text": plain.joined(separator: "\n")])
}

// ---- capture the screen via the system tool, then OCR -----------------------
func capture(region: String?) {
    let tmp = NSTemporaryDirectory() + "screenreduce_\(getpid()).png"
    var args = ["-x"]                       // -x: no capture sound
    if let r = region { args += ["-R", r] } // x,y,w,h
    args.append(tmp)
    let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture"); p.arguments = args
    do { try p.run(); p.waitUntilExit() } catch { die("screencapture failed: \(error)") }
    guard FileManager.default.fileExists(atPath: tmp) else {
        die("capture produced no file — grant Screen Recording permission to the terminal/host app.")
    }
    ocr(tmp)
    try? FileManager.default.removeItem(atPath: tmp)
}

// ---- tier 0: dump the frontmost app's accessibility tree --------------------
func axAttr(_ el: AXUIElement, _ key: String) -> AnyObject? {
    var v: AnyObject?
    return AXUIElementCopyAttributeValue(el, key as CFString, &v) == .success ? v : nil
}
func axPoint(_ el: AXUIElement, _ key: String) -> [Int]? {
    guard let v = axAttr(el, key) else { return nil }
    let val = v as! AXValue
    if AXValueGetType(val) == .cgPoint { var p = CGPoint.zero; AXValueGetValue(val, .cgPoint, &p); return [Int(p.x), Int(p.y)] }
    if AXValueGetType(val) == .cgSize  { var s = CGSize.zero;  AXValueGetValue(val, .cgSize, &s);  return [Int(s.width), Int(s.height)] }
    return nil
}
var axNodeCount = 0
func axWalk(_ el: AXUIElement, depth: Int) -> [String: Any]? {
    if axNodeCount > 500 || depth > 14 { return nil }
    axNodeCount += 1
    var node: [String: Any] = [:]
    if let r = axAttr(el, kAXRoleAttribute as String) as? String { node["role"] = r }
    if let t = axAttr(el, kAXTitleAttribute as String) as? String, !t.isEmpty { node["title"] = t }
    if let v = axAttr(el, kAXValueAttribute as String) as? String, !v.isEmpty { node["value"] = v }
    if let d = axAttr(el, kAXDescriptionAttribute as String) as? String, !d.isEmpty { node["desc"] = d }
    if let pos = axPoint(el, kAXPositionAttribute as String), let sz = axPoint(el, kAXSizeAttribute as String) {
        node["frame"] = [pos[0], pos[1], sz[0], sz[1]]
    }
    if let kids = axAttr(el, kAXChildrenAttribute as String) as? [AXUIElement] {
        var children: [[String: Any]] = []
        for k in kids { if let c = axWalk(k, depth: depth+1) { children.append(c) } }
        if !children.isEmpty { node["children"] = children }
    }
    return node
}
func ax() {
    guard AXIsProcessTrusted() else {
        die("Accessibility permission not granted. Enable it for the terminal/host app in System Settings ▸ Privacy & Security ▸ Accessibility.")
    }
    guard let app = NSWorkspace.shared.frontmostApplication else { die("no frontmost app") }
    let root = AXUIElementCreateApplication(app.processIdentifier)
    let tree = axWalk(root, depth: 0) ?? [:]
    emit(["app": app.localizedName ?? "?", "pid": app.processIdentifier, "nodes": axNodeCount, "tree": tree])
}

// ---- dispatch ---------------------------------------------------------------
let a = Array(CommandLine.arguments.dropFirst())
switch a.first {
case "ocr":     guard a.count >= 2 else { die("usage: screenreduce ocr <image>") }; ocr(a[1])
case "capture": var r: String? = nil; if let i = a.firstIndex(of: "-R"), i+1 < a.count { r = a[i+1] }; capture(region: r)
case "ax":      ax()
default: die("usage: screenreduce <ocr <image> | capture [-R x,y,w,h] | ax>")
}
