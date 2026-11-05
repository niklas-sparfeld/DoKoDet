import CoreGraphics
import Foundation

enum DeviceVisibleRegionCropper {
  static func crop(image: CGImage, normalizedPolygon: [[Int]]) throws -> CGImage? {
    guard normalizedPolygon.count >= 3,
      normalizedPolygon.allSatisfy({
        $0.count == 2 && (0...1_000).contains($0[0]) && (0...1_000).contains($0[1])
      })
    else { return nil }
    let xs = normalizedPolygon.map { $0[0] }
    let ys = normalizedPolygon.map { $0[1] }
    let minX = max(0, Int(floor(Double(xs.min()!) * Double(image.width) / 1_000)))
    let minY = max(0, Int(floor(Double(ys.min()!) * Double(image.height) / 1_000)))
    let maxX = min(image.width, Int(ceil(Double(xs.max()!) * Double(image.width) / 1_000)))
    let maxY = min(image.height, Int(ceil(Double(ys.max()!) * Double(image.height) / 1_000)))
    guard maxX - minX >= 4, maxY - minY >= 4,
      let sourceCrop = image.cropping(
        to: CGRect(x: minX, y: minY, width: maxX - minX, height: maxY - minY))
    else { return nil }
    let width = sourceCrop.width
    let height = sourceCrop.height
    var pixels = [UInt8](repeating: 128, count: width * height * 4)
    for pixel in 0..<(width * height) { pixels[pixel * 4 + 3] = 255 }
    let colorSpace = CGColorSpaceCreateDeviceRGB()
    let bitmapInfo =
      CGBitmapInfo.byteOrder32Big.rawValue | CGImageAlphaInfo.premultipliedLast.rawValue
    guard
      let context = CGContext(
        data: &pixels, width: width, height: height, bitsPerComponent: 8,
        bytesPerRow: width * 4, space: colorSpace, bitmapInfo: bitmapInfo)
    else { throw DeviceVisibleCardStageError.invalidOutput }
    context.translateBy(x: 0, y: CGFloat(height))
    context.scaleBy(x: 1, y: -1)
    let path = CGMutablePath()
    for (index, point) in normalizedPolygon.enumerated() {
      let x = CGFloat(point[0]) * CGFloat(image.width) / 1_000 - CGFloat(minX)
      let y = CGFloat(point[1]) * CGFloat(image.height) / 1_000 - CGFloat(minY)
      if index == 0 {
        path.move(to: CGPoint(x: x, y: y))
      } else {
        path.addLine(to: CGPoint(x: x, y: y))
      }
    }
    path.closeSubpath()
    context.addPath(path)
    context.clip()
    context.setShouldAntialias(false)
    context.interpolationQuality = .none
    context.draw(sourceCrop, in: CGRect(x: 0, y: 0, width: width, height: height))
    return context.makeImage()
  }
}
