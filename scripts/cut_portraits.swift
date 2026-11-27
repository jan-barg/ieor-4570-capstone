// Cuts each person out of their portrait photo with Apple's Vision framework (on the Mac, free, no download).
// Run through scripts/cut_portraits.py, which compiles it and writes the results into people.json.
//   cut_portraits <photos dir> <out dir>
// For each photo: finds the largest face, keeps only the foreground instance under that face (a second person in
// the shot is dropped), crops to the person, writes <slug>.png with transparency, and prints one JSON line:
// {"file", "w", "h", "face": [x0,y0,x1,y1] (0-1 of the cutout, top-left origin), "crop", "photo_w", "photo_h", ...}.
import AppKit
import CoreImage
import Foundation
import Vision

func cgImage(_ url: URL) -> CGImage? {
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
    return CGImageSourceCreateImageAtIndex(src, 0, nil)
}

func emit(_ d: [String: Any]) {
    let data = try! JSONSerialization.data(withJSONObject: d, options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
}

let args = CommandLine.arguments
let inDir = URL(fileURLWithPath: args[1]), outDir = URL(fileURLWithPath: args[2])
try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
let files = try! FileManager.default.contentsOfDirectory(at: inDir, includingPropertiesForKeys: nil)
    .filter { ["jpg", "jpeg", "png"].contains($0.pathExtension.lowercased()) }
    .sorted { $0.lastPathComponent < $1.lastPathComponent }
let ci = CIContext()

for url in files {
    let slug = url.deletingPathExtension().lastPathComponent
    guard let img = cgImage(url) else { emit(["file": slug, "error": "unreadable"]); continue }
    let W = img.width, H = img.height
    let handler = VNImageRequestHandler(cgImage: img, options: [:])
    let faces = VNDetectFaceRectanglesRequest()
    let fg = VNGenerateForegroundInstanceMaskRequest()
    do { try handler.perform([faces, fg]) } catch { emit(["file": slug, "error": "\(error)"]); continue }
    guard let obs = fg.results?.first else { emit(["file": slug, "error": "no person found"]); continue }

    // the largest face (Vision: normalized, origin bottom-left)
    let face = (faces.results ?? []).max { $0.boundingBox.width * $0.boundingBox.height < $1.boundingBox.width * $1.boundingBox.height }
    var keep = obs.allInstances
    if let f = face {
        let lab = obs.instanceMask
        CVPixelBufferLockBaseAddress(lab, .readOnly)
        let mw = CVPixelBufferGetWidth(lab), mh = CVPixelBufferGetHeight(lab)
        let row = CVPixelBufferGetBytesPerRow(lab)
        let base = CVPixelBufferGetBaseAddress(lab)!.assumingMemoryBound(to: UInt8.self)
        // vote over the face box: the instance most of the face belongs to
        var votes = [Int: Int]()
        for i in 0..<9 { for j in 0..<9 {
            let x = f.boundingBox.minX + f.boundingBox.width * (CGFloat(i) + 0.5) / 9
            let y = f.boundingBox.minY + f.boundingBox.height * (CGFloat(j) + 0.5) / 9
            let px = min(mw - 1, Int(x * CGFloat(mw))), py = min(mh - 1, Int((1 - y) * CGFloat(mh)))
            let v = Int(base[py * row + px]); if v > 0 { votes[v, default: 0] += 1 }
        } }
        CVPixelBufferUnlockBaseAddress(lab, .readOnly)
        if let best = votes.max(by: { $0.value < $1.value })?.key { keep = IndexSet(integer: best) }
    }
    guard let maskBuf = try? obs.generateScaledMaskForImage(forInstances: keep, from: handler) else {
        emit(["file": slug, "error": "mask failed"]); continue
    }
    // mask bounding box (mask is full image size, float 0-1, origin top-left in memory)
    CVPixelBufferLockBaseAddress(maskBuf, .readOnly)
    let mw = CVPixelBufferGetWidth(maskBuf), mh = CVPixelBufferGetHeight(maskBuf)
    let mrow = CVPixelBufferGetBytesPerRow(maskBuf) / 4
    let mbase = CVPixelBufferGetBaseAddress(maskBuf)!.assumingMemoryBound(to: Float32.self)
    var x0 = mw, y0 = mh, x1 = 0, y1 = 0, on = 0
    for y in 0..<mh { for x in 0..<mw where mbase[y * mrow + x] > 0.5 {
        on += 1; x0 = min(x0, x); y0 = min(y0, y); x1 = max(x1, x); y1 = max(y1, y)
    } }
    CVPixelBufferUnlockBaseAddress(maskBuf, .readOnly)
    if on == 0 { emit(["file": slug, "error": "empty mask"]); continue }

    let input = CIImage(cgImage: img)
    let mask = CIImage(cvPixelBuffer: maskBuf)
    let blended = input.applyingFilter("CIBlendWithMask", parameters: [
        kCIInputBackgroundImageKey: CIImage.empty(), kCIInputMaskImageKey: mask])
    let pad = 4
    let cx0 = max(0, x0 - pad), cy0 = max(0, y0 - pad), cx1 = min(W - 1, x1 + pad), cy1 = min(H - 1, y1 + pad)
    // CoreImage is bottom-left origin
    let rect = CGRect(x: cx0, y: H - 1 - cy1, width: cx1 - cx0 + 1, height: cy1 - cy0 + 1)
    guard let out = ci.createCGImage(blended, from: rect, format: .RGBA8, colorSpace: CGColorSpace(name: CGColorSpace.sRGB)) else {
        emit(["file": slug, "error": "render failed"]); continue
    }
    let dest = outDir.appendingPathComponent("\(slug).png")
    let rep = NSBitmapImageRep(cgImage: out)
    try! rep.representation(using: .png, properties: [:])!.write(to: dest)

    var d: [String: Any] = ["file": slug, "w": out.width, "h": out.height, "people": obs.allInstances.count,
                            "cover": Double(on) / Double(mw * mh),
                            "touches_bottom": y1 >= H - 3, "touches_sides": x0 <= 2 || x1 >= W - 3,
                            "photo_w": W, "photo_h": H, "crop": [cx0, cy0]]
    if let f = face {
        let fx0 = (f.boundingBox.minX * CGFloat(W) - CGFloat(cx0)) / CGFloat(out.width)
        let fx1 = (f.boundingBox.maxX * CGFloat(W) - CGFloat(cx0)) / CGFloat(out.width)
        let fy0 = ((1 - f.boundingBox.maxY) * CGFloat(H) - CGFloat(cy0)) / CGFloat(out.height)
        let fy1 = ((1 - f.boundingBox.minY) * CGFloat(H) - CGFloat(cy0)) / CGFloat(out.height)
        d["face"] = [fx0, fy0, fx1, fy1].map { (Double($0) * 1000).rounded() / 1000 }
    }
    emit(d)
}
