import CoreGraphics
import CoreML
import CryptoKit
import Foundation
import ImageIO

/// Runs the pinned 25-class DINOv3 Core ML package with the 0104 input and output names.
final class DinoV3CoreMLRunner {
  private let model: MLModel
  let compiledModelSHA256: String

  init(modelURL: URL) throws {
    let configuration = MLModelConfiguration()
    configuration.computeUnits = .cpuOnly
    let compiledURL =
      modelURL.pathExtension == "mlpackage"
      ? try MLModel.compileModel(at: modelURL) : modelURL
    model = try MLModel(contentsOf: compiledURL, configuration: configuration)
    compiledModelSHA256 = try Self.directorySHA256(compiledURL)
  }

  static func loadBundled() throws -> DinoV3CoreMLRunner {
    guard let url = Bundle.main.url(forResource: "DINOv3Identity", withExtension: "mlmodelc") else {
      throw DeviceVisibleCardStageError.modelUnavailable
    }
    return try DinoV3CoreMLRunner(modelURL: url)
  }

  func predict(_ values: [Float]) throws -> DeviceVisualIdentityResult {
    guard values.count == 3 * 224 * 224, values.allSatisfy(\.isFinite) else {
      throw DeviceVisualIdentityError.invalidLogits
    }
    let input = try MLMultiArray(shape: [1, 3, 224, 224], dataType: .float32)
    for index in values.indices {
      input[index] = NSNumber(value: values[index])
    }
    let provider = try MLDictionaryFeatureProvider(dictionary: [
      "pixel_values": MLFeatureValue(multiArray: input)
    ])
    let output = try model.prediction(from: provider)
    guard let logits = output.featureValue(for: "logits")?.multiArrayValue,
      logits.count == 25
    else {
      throw DeviceVisibleCardStageError.invalidOutput
    }
    return try DeviceVisualIdentityPostprocessor.process(
      (0..<25).map { logits[$0].doubleValue })
  }

  func predict(image: CGImage) throws -> (DeviceVisualIdentityResult, [Float]) {
    let values = try DinoV3ImageTensor(cgImage: image).values
    return (try predict(values), values)
  }

  private static func directorySHA256(_ url: URL) throws -> String {
    let manager = FileManager.default
    guard
      let enumerator = manager.enumerator(
        at: url, includingPropertiesForKeys: [.isRegularFileKey],
        options: [.skipsHiddenFiles])
    else { throw DeviceVisibleCardStageError.modelUnavailable }
    let files = enumerator.compactMap { $0 as? URL }.filter { candidate in
      (try? candidate.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true
    }.sorted { $0.path < $1.path }
    var digest = SHA256()
    for file in files {
      let relative = String(file.path.dropFirst(url.path.count + 1))
      digest.update(data: Data(relative.utf8))
      digest.update(data: Data([0]))
      digest.update(data: try Data(contentsOf: file))
    }
    return digest.finalize().map { String(format: "%02x", $0) }.joined()
  }
}

struct DinoV3ImageTensor {
  let values: [Float]
  static let side = 224
  private static let fixedPoint = 1 << 22

  init(cgImage: CGImage) throws {
    var rgba = [UInt8](repeating: 0, count: cgImage.width * cgImage.height * 4)
    let colorSpace = CGColorSpaceCreateDeviceRGB()
    let bitmapInfo =
      CGBitmapInfo.byteOrder32Big.rawValue | CGImageAlphaInfo.premultipliedLast.rawValue
    guard
      let context = CGContext(
        data: &rgba, width: cgImage.width, height: cgImage.height, bitsPerComponent: 8,
        bytesPerRow: cgImage.width * 4, space: colorSpace, bitmapInfo: bitmapInfo)
    else { throw DeviceVisibleCardStageError.invalidOutput }
    context.draw(cgImage, in: CGRect(x: 0, y: 0, width: cgImage.width, height: cgImage.height))
    var rgb = [UInt8](repeating: 0, count: cgImage.width * cgImage.height * 3)
    for pixel in 0..<(cgImage.width * cgImage.height) {
      rgb[pixel * 3] = rgba[pixel * 4]
      rgb[pixel * 3 + 1] = rgba[pixel * 4 + 1]
      rgb[pixel * 3 + 2] = rgba[pixel * 4 + 2]
    }
    try self.init(rgb: rgb, width: cgImage.width, height: cgImage.height)
  }

  init(ppmData: Data) throws {
    let parsed = try Self.parsePPM(ppmData)
    try self.init(rgb: parsed.pixels, width: parsed.width, height: parsed.height)
  }

  private init(rgb: [UInt8], width: Int, height: Int) throws {
    guard width >= 4, height >= 4, rgb.count == width * height * 3 else {
      throw DeviceVisibleCardStageError.invalidOutput
    }
    let scale = min(Double(Self.side) / Double(width), Double(Self.side) / Double(height))
    let resizedWidth = max(1, Int((Double(width) * scale).rounded(.toNearestOrEven)))
    let resizedHeight = max(1, Int((Double(height) * scale).rounded(.toNearestOrEven)))
    let resized = Self.lanczos(
      rgb, sourceWidth: width, sourceHeight: height,
      targetWidth: resizedWidth, targetHeight: resizedHeight)
    var pixels = [UInt8](repeating: 128, count: Self.side * Self.side * 3)
    let offsetX = (Self.side - resizedWidth) / 2
    let offsetY = (Self.side - resizedHeight) / 2
    for y in 0..<resizedHeight {
      let source = y * resizedWidth * 3
      let target = ((y + offsetY) * Self.side + offsetX) * 3
      pixels.replaceSubrange(
        target..<(target + resizedWidth * 3), with: resized[source..<(source + resizedWidth * 3)])
    }
    let planeSize = Self.side * Self.side
    var tensor = [Float](repeating: 0, count: 3 * planeSize)
    let means: [Double] = [0.485, 0.456, 0.406]
    let deviations: [Double] = [0.229, 0.224, 0.225]
    for pixel in 0..<planeSize {
      for channel in 0..<3 {
        let sample = Double(pixels[pixel * 3 + channel]) / 255
        tensor[channel * planeSize + pixel] = Float((sample - means[channel]) / deviations[channel])
      }
    }
    values = tensor
  }

  private static func parsePPM(_ data: Data) throws -> (width: Int, height: Int, pixels: [UInt8]) {
    let bytes = [UInt8](data)
    var cursor = 0
    func nextToken() -> String? {
      while cursor < bytes.count {
        if bytes[cursor] == 35 {
          while cursor < bytes.count && bytes[cursor] != 10 { cursor += 1 }
        } else if bytes[cursor] == 9 || bytes[cursor] == 10 || bytes[cursor] == 13
          || bytes[cursor] == 32
        {
          cursor += 1
        } else {
          break
        }
      }
      let start = cursor
      while cursor < bytes.count && bytes[cursor] != 9 && bytes[cursor] != 10
        && bytes[cursor] != 13 && bytes[cursor] != 32 && bytes[cursor] != 35
      { cursor += 1 }
      guard cursor > start else { return nil }
      return String(decoding: bytes[start..<cursor], as: UTF8.self)
    }
    guard nextToken() == "P6", let widthText = nextToken(), let width = Int(widthText),
      let heightText = nextToken(), let height = Int(heightText), nextToken() == "255"
    else { throw DeviceVisibleCardStageError.invalidOutput }
    guard cursor < bytes.count,
      bytes[cursor] == 9 || bytes[cursor] == 10 || bytes[cursor] == 13 || bytes[cursor] == 32
    else { throw DeviceVisibleCardStageError.invalidOutput }
    if bytes[cursor] == 13 && cursor + 1 < bytes.count && bytes[cursor + 1] == 10 {
      cursor += 2
    } else {
      cursor += 1
    }
    let pixels = Array(bytes[cursor...])
    guard pixels.count == width * height * 3 else {
      throw DeviceVisibleCardStageError.invalidOutput
    }
    return (width, height, pixels)
  }

  private static func lanczos(
    _ source: [UInt8], sourceWidth: Int, sourceHeight: Int,
    targetWidth: Int, targetHeight: Int
  ) -> [UInt8] {
    let horizontal = resample(
      source, sourceWidth: sourceWidth, sourceHeight: sourceHeight,
      targetLength: targetWidth, horizontal: true)
    return resample(
      horizontal, sourceWidth: targetWidth, sourceHeight: sourceHeight,
      targetLength: targetHeight, horizontal: false)
  }

  private static func resample(
    _ source: [UInt8], sourceWidth: Int, sourceHeight: Int,
    targetLength: Int, horizontal: Bool
  ) -> [UInt8] {
    let sourceLength = horizontal ? sourceWidth : sourceHeight
    let orthogonalLength = horizontal ? sourceHeight : sourceWidth
    let scale = min(1.0, Double(targetLength) / Double(sourceLength))
    let support = 3.0 / scale
    var output = [UInt8](
      repeating: 0,
      count: (horizontal ? targetLength : orthogonalLength)
        * (horizontal ? orthogonalLength : targetLength) * 3)
    for targetIndex in 0..<targetLength {
      let center = (Double(targetIndex) + 0.5) * Double(sourceLength) / Double(targetLength)
      let first = max(0, Int(floor(center - support + 0.5)))
      let last = min(sourceLength, Int(floor(center + support + 0.5)))
      var weights: [(Int, Double)] = []
      var total = 0.0
      for sourceIndex in first..<last {
        let x = (Double(sourceIndex) + 0.5 - center) * scale
        let weight = abs(x) < 3 ? sinc(x) * sinc(x / 3) : 0
        weights.append((sourceIndex, weight))
        total += weight
      }
      if total != 0 {
        weights = weights.map { ($0.0, Double(Int($0.1 / total * Double(fixedPoint) + 0.5))) }
      }
      for orthogonal in 0..<orthogonalLength {
        for channel in 0..<3 {
          var sum = fixedPoint / 2
          for (sourceIndex, fixedWeight) in weights {
            let x = horizontal ? sourceIndex : orthogonal
            let y = horizontal ? orthogonal : sourceIndex
            sum += Int(source[(y * sourceWidth + x) * 3 + channel]) * Int(fixedWeight)
          }
          let value = UInt8(max(0, min(255, sum >> 22)))
          let x = horizontal ? targetIndex : orthogonal
          let y = horizontal ? orthogonal : targetIndex
          output[(y * (horizontal ? targetLength : orthogonalLength) + x) * 3 + channel] = value
        }
      }
    }
    return output
  }

  private static func sinc(_ value: Double) -> Double {
    if value == 0 { return 1 }
    let angle = Double.pi * value
    return sin(angle) / angle
  }
}
