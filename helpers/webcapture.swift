// webcapture.swift — capture a PUBLIC web page to an immutable PDF snapshot + metadata.
// Native WKWebView (on-device browser engine, no pip). The snapshot becomes the evidence;
// the live URL + retrieval timestamp are provenance. Compile: swiftc -O webcapture.swift -o webcapture
//
//   webcapture <url> <out-base>      # writes <out-base>.pdf and <out-base>.html; prints metadata JSON
//
// metadata: {url, final_url, retrieved (UTC now), title, published, modified, author}

import Cocoa
import WebKit
import Foundation

let args = CommandLine.arguments
func die(_ s: String, _ code: Int32) -> Never {
    FileHandle.standardError.write((s + "\n").data(using: .utf8)!); exit(code)
}
guard args.count >= 3, let url = URL(string: args[1]) else { die("usage: webcapture <url> <out-base>", 2) }
let outBase = args[2]

let iso = ISO8601DateFormatter(); iso.formatOptions = [.withInternetDateTime]
let retrieved = iso.string(from: Date())          // authoritative "when we fetched it"

let app = NSApplication.shared
app.setActivationPolicy(.accessory)

final class Cap: NSObject, WKNavigationDelegate {
    let wv = WKWebView(frame: NSRect(x: 0, y: 0, width: 1200, height: 1600),
                       configuration: WKWebViewConfiguration())
    override init() { super.init(); wv.navigationDelegate = self }

    func webView(_ w: WKWebView, didFinish n: WKNavigation!) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { self.capture() }   // settle late render
    }
    func webView(_ w: WKWebView, didFail n: WKNavigation!, withError e: Error) { die("load failed: \(e.localizedDescription)", 3) }
    func webView(_ w: WKWebView, didFailProvisionalNavigation n: WKNavigation!, withError e: Error) { die("load failed: \(e.localizedDescription)", 3) }

    func capture() {
        let js = """
        (function(){function m(s){var e=document.querySelector(s);return e?(e.content||e.getAttribute('datetime')):null;}
        return JSON.stringify({title:document.title,
        published:m('meta[property="article:published_time"]')||m('meta[itemprop="datePublished"]')||m('meta[name="datePublished"]'),
        modified:m('meta[property="article:modified_time"]')||m('meta[name="dateModified"]'),
        author:m('meta[name="author"]')||m('meta[property="article:author"]'),
        final_url:location.href, html:document.documentElement.outerHTML});})();
        """
        wv.evaluateJavaScript(js) { res, _ in
            var meta: [String: Any] = ["url": args[1], "retrieved": retrieved]
            if let s = res as? String, let d = s.data(using: .utf8),
               let o = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any] {
                for (k, v) in o where k != "html" { if !(v is NSNull) { meta[k] = v } }
                if let html = o["html"] as? String { try? html.write(toFile: outBase + ".html", atomically: true, encoding: .utf8) }
            }
            self.wv.createPDF(configuration: WKPDFConfiguration()) { r in
                if case .success(let data) = r { try? data.write(to: URL(fileURLWithPath: outBase + ".pdf")) }
                let out = try! JSONSerialization.data(withJSONObject: meta, options: [.sortedKeys])
                FileHandle.standardOutput.write(out); print("")
                exit(0)
            }
        }
    }
}
let cap = Cap()
cap.wv.load(URLRequest(url: url))
DispatchQueue.main.asyncAfter(deadline: .now() + 30) { die("timeout", 4) }
app.run()
