// summarize.swift — band-3-lite on-device text summariser (Dossier).
// Runs Apple Intelligence Foundation Models (~3B, on-device) over an artifact's OCR text
// and emits a faithful summary + key points as JSON. Keeps full text OFF Claude's context.
// Compile: swiftc -O summarize.swift -o summarize     (requires macOS 26 SDK)
//
//   summarize <textfile> [--points N]      (or: summarize -   to read stdin)
//
// Design notes:
//  • On-device model context is small (~4k tokens) → long text is chunked (~6k chars),
//    each chunk summarised in a FRESH session (no transcript build-up), then rolled up.
//  • Reduction only — never authoritative. Deterministic band-1/2 (dates, SHAs) are unaffected.
//  • Degrades honestly: if Apple Intelligence is off / model not ready / not eligible, emits
//    {"available": false, "reason": ...} and exit 0 so the caller can fall back to Claude.
//  • Guardrail refusals are reported, not fatal.

import Foundation
#if canImport(FoundationModels)
import FoundationModels
#endif

// ---- args ----
let args = Array(CommandLine.arguments.dropFirst())
func flag(_ name: String) -> String? {
    if let i = args.firstIndex(of: name), i + 1 < args.count { return args[i + 1] }
    return nil
}
let pointsWanted = Int(flag("--points") ?? "5") ?? 5

let pathArg = args.first(where: { !$0.hasPrefix("--") })
let text: String
if let p = pathArg, p != "-" {
    guard FileManager.default.fileExists(atPath: p) else {
        FileHandle.standardError.write("error: no such file: \(p)\n".data(using: .utf8)!); exit(2)
    }
    text = (try? String(contentsOfFile: p, encoding: .utf8)) ?? ""
} else {
    text = String(data: FileHandle.standardInput.readDataToEndOfFile(), encoding: .utf8) ?? ""
}

func emit(_ obj: [String: Any]) {
    let data = try! JSONSerialization.data(withJSONObject: obj,
                    options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write("\n".data(using: .utf8)!)
}

// Split on paragraph boundaries into ~size-char chunks (leaves room for instructions+output).
func chunk(_ s: String, _ size: Int) -> [String] {
    if s.count <= size { return [s] }
    var out: [String] = [], cur = ""
    for para in s.components(separatedBy: "\n") {
        if cur.count + para.count + 1 > size, !cur.isEmpty { out.append(cur); cur = "" }
        if para.count > size {                    // a single giant line → hard-split
            var idx = para.startIndex
            while idx < para.endIndex {
                let end = para.index(idx, offsetBy: size, limitedBy: para.endIndex) ?? para.endIndex
                out.append(String(para[idx..<end])); idx = end
            }
        } else { cur += (cur.isEmpty ? "" : "\n") + para }
    }
    if !cur.isEmpty { out.append(cur) }
    return out
}

let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
if trimmed.isEmpty { emit(["available": true, "empty": true, "summary": "", "key_points": []]); exit(0) }

#if canImport(FoundationModels)
@available(macOS 26.0, *)
@Generable
struct Digest {
    @Guide(description: "A faithful, neutral 2–4 sentence summary of the document. Do not invent facts.")
    var summary: String
    @Guide(description: "Short factual bullet points: parties, dates, amounts, obligations, outcomes.")
    var keyPoints: [String]
}

@available(macOS 26.0, *)
func run() async {
    let model = SystemLanguageModel.default
    switch model.availability {
    case .available: break
    case .unavailable(let reason):
        emit(["available": false, "reason": "\(reason)"]); return
    }

    let instructions = "You summarise documents faithfully and neutrally. Never add facts that "
        + "are not present. Prefer specifics: parties, dates, amounts, and obligations."
    let opts = GenerationOptions(temperature: 0.2)
    let allChunks = chunk(trimmed, 6000)
    let maxChunks = 12                         // bound time on huge docs (~first 72k chars)
    let chunks = Array(allChunks.prefix(maxChunks))
    let truncated = allChunks.count > maxChunks

    // Long docs: summarise each chunk (fresh session → no context build-up), then roll up.
    var material = trimmed
    if chunks.count > 1 {
        var parts: [String] = []
        for (i, c) in chunks.enumerated() {
            do {
                let s = LanguageModelSession(instructions: instructions)
                let r = try await s.respond(to: "Summarise this excerpt in 2–3 sentences, keeping "
                    + "specific facts:\n\n\(c)", options: opts)
                parts.append("• \(r.content)")
            } catch let e as LanguageModelSession.GenerationError {
                parts.append("• [section \(i + 1) skipped: \(e)]")
            } catch { parts.append("• [section \(i + 1) error]") }
        }
        material = parts.joined(separator: "\n")
    }

    // Final structured pass.
    do {
        let s = LanguageModelSession(instructions: instructions)
        let prompt = (chunks.count > 1 ? "These are section summaries of one document. " : "")
            + "Produce an overall summary and up to \(pointsWanted) key points.\n\n\(material)"
        let r = try await s.respond(to: prompt, generating: Digest.self, options: opts)
        emit(["available": true, "model": "apple-foundation-models (on-device)",
              "chars": trimmed.count, "chunks": chunks.count, "truncated": truncated,
              "summary": r.content.summary, "key_points": r.content.keyPoints])
    } catch let e as LanguageModelSession.GenerationError {
        // e.g. guardrailViolation on sensitive content — report, let caller decide.
        emit(["available": true, "refused": true, "reason": "\(e)", "chunks": chunks.count])
    } catch {
        emit(["available": true, "error": "\(error)"])
    }
}

if #available(macOS 26.0, *) {
    let sem = DispatchSemaphore(value: 0)
    Task { await run(); sem.signal() }
    sem.wait()
} else {
    emit(["available": false, "reason": "requires macOS 26 (Foundation Models)"])
}
#else
emit(["available": false, "reason": "built without FoundationModels SDK (need macOS 26 toolchain)"])
#endif
