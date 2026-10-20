// Mac helper for follow the work. No dependencies beyond macOS frameworks.
//   fow front          -> JSON {app, title, window_id} of the frontmost window
//   fow ocr <image>    -> recognized text, one line per text block, top to bottom
//   fow clip           -> clipboard text, empty if a password manager concealed it
// The window title needs Screen Recording permission for the terminal.
import AppKit
import Foundation
import Vision

func front() {
    guard let app = NSWorkspace.shared.frontmostApplication else { print("{}"); return }
    let pid = app.processIdentifier
    let opts: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
    let list = (CGWindowListCopyWindowInfo(opts, kCGNullWindowID) as? [[String: Any]]) ?? []
    var out: [String: Any] = ["app": app.localizedName ?? "", "title": "", "window_id": 0]
    for w in list {
        guard (w[kCGWindowOwnerPID as String] as? Int32) == pid,
              (w[kCGWindowLayer as String] as? Int) == 0 else { continue }
        out["title"] = w[kCGWindowName as String] as? String ?? ""
        out["window_id"] = w[kCGWindowNumber as String] as? Int ?? 0
        break
    }
    let data = try! JSONSerialization.data(withJSONObject: out)
    print(String(data: data, encoding: .utf8)!)
}

func ocr(_ path: String) {
    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        FileHandle.standardError.write("cannot read \(path)\n".data(using: .utf8)!)
        exit(1)
    }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = true
    req.recognitionLanguages = ["en-US", "nl-NL", "fr-FR"]
    try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
    let obs = (req.results ?? []).sorted {
        abs($0.boundingBox.midY - $1.boundingBox.midY) > 0.01
            ? $0.boundingBox.midY > $1.boundingBox.midY
            : $0.boundingBox.minX < $1.boundingBox.minX
    }
    // Join blocks on roughly the same row so table rows stay on one line.
    var lines: [String] = []
    var lastY: CGFloat = -1
    for o in obs {
        guard let s = o.topCandidates(1).first?.string else { continue }
        if lastY >= 0 && abs(o.boundingBox.midY - lastY) <= 0.01, !lines.isEmpty {
            lines[lines.count - 1] += "  " + s
        } else {
            lines.append(s)
            lastY = o.boundingBox.midY
        }
    }
    print(lines.joined(separator: "\n"))
}

// Clipboard text, empty when a password manager marked it concealed or transient.
func clip() {
    let pb = NSPasteboard.general
    let types = (pb.types ?? []).map { $0.rawValue }
    let hidden = ["org.nspasteboard.ConcealedType", "org.nspasteboard.TransientType",
                  "com.agilebits.onepassword"]
    if types.contains(where: { hidden.contains($0) }) { return }
    print(String((pb.string(forType: .string) ?? "").prefix(200)), terminator: "")
}

let args = CommandLine.arguments
if args.count >= 2 && args[1] == "front" { front() }
else if args.count >= 2 && args[1] == "clip" { clip() }
else if args.count >= 3 && args[1] == "ocr" { ocr(args[2]) }
else { print("usage: fow front | fow ocr <image>"); exit(2) }
