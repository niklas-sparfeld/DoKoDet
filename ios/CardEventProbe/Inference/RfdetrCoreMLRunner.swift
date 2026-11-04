import CoreGraphics
import CoreML
import CryptoKit
import Foundation

public struct RfdetrImageTensor: Sendable {
    public static let side = 432
    public let values: [Float]

    public init(cgImage: CGImage) throws {
        let width = cgImage.width
        let height = cgImage.height
        guard width > 0, height > 0 else { throw DeviceVisibleCardStageError.invalidOutput }
        var rgba = [UInt8](repeating: 0, count: width * height * 4)
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        let info = CGBitmapInfo.byteOrder32Big.rawValue | CGImageAlphaInfo.premultipliedLast.rawValue
        guard let context = CGContext(
            data: &rgba,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * 4,
            space: colorSpace,
            bitmapInfo: info
        ) else { throw DeviceVisibleCardStageError.invalidOutput }
        context.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))

        let planeSize = Self.side * Self.side
        var tensor = [Float](repeating: 0, count: 3 * planeSize)
        let means: [Float] = [0.485, 0.456, 0.406]
        let deviations: [Float] = [0.229, 0.224, 0.225]
        for y in 0..<Self.side {
            let fy = (Float(y) + 0.5) * Float(height) / Float(Self.side) - 0.5
            let y0 = max(0, min(height - 1, Int(floor(fy))))
            let y1 = min(height - 1, y0 + 1)
            let wy = max(0, min(1, fy - Float(y0)))
            for x in 0..<Self.side {
                let fx = (Float(x) + 0.5) * Float(width) / Float(Self.side) - 0.5
                let x0 = max(0, min(width - 1, Int(floor(fx))))
                let x1 = min(width - 1, x0 + 1)
                let wx = max(0, min(1, fx - Float(x0)))
                let target = y * Self.side + x
                for channel in 0..<3 {
                    let topLeft = Float(rgba[(y0 * width + x0) * 4 + channel]) / 255
                    let topRight = Float(rgba[(y0 * width + x1) * 4 + channel]) / 255
                    let bottomLeft = Float(rgba[(y1 * width + x0) * 4 + channel]) / 255
                    let bottomRight = Float(rgba[(y1 * width + x1) * 4 + channel]) / 255
                    let top = topLeft * (1 - wx) + topRight * wx
                    let bottom = bottomLeft * (1 - wx) + bottomRight * wx
                    let pixel = top * (1 - wy) + bottom * wy
                    tensor[channel * planeSize + target] = (pixel - means[channel]) / deviations[channel]
                }
            }
        }
        values = tensor
    }
}

public final class RfdetrCoreMLRunner {
    public static let modelName = "RFDETRSegMedium"
    public static let packageSHA256 =
        "425ec4edeaed510743778229c2d03b6ef3fa727e5c182f50b2e8336b63916947"
    public static let checkpointSHA256 =
        "80accf8a7c55ec65fdd346c0d2cbfdd28b936260c242c30f1c39ced6043179e"

    private let model: MLModel
    public let compiledModelSHA256: String

    public init(modelURL: URL) throws {
        let configuration = MLModelConfiguration()
        configuration.computeUnits = .cpuAndGPU
        model = try MLModel(contentsOf: modelURL, configuration: configuration)
        compiledModelSHA256 = try Self.directorySHA256(modelURL)
    }

    public static func loadBundled() throws -> RfdetrCoreMLRunner {
        guard let modelURL = Bundle.main.url(forResource: modelName, withExtension: "mlmodelc") else {
            throw DeviceVisibleCardStageError.modelUnavailable
        }
        return try RfdetrCoreMLRunner(modelURL: modelURL)
    }

    public func predict(_ tensor: RfdetrImageTensor) throws -> RfdetrRawOutput {
        let input = try MLMultiArray(shape: [1, 3, 432, 432], dataType: .float32)
        let count = min(input.count, tensor.values.count)
        for index in 0..<count {
            input[index] = NSNumber(value: tensor.values[index])
        }
        let provider = try MLDictionaryFeatureProvider(dictionary: ["image": MLFeatureValue(multiArray: input)])
        let prediction = try model.prediction(from: provider)
        guard let boxes = prediction.featureValue(for: "boxes")?.multiArrayValue,
              let classes = prediction.featureValue(for: "class_logits")?.multiArrayValue,
              let masks = prediction.featureValue(for: "mask_logits")?.multiArrayValue,
              boxes.count >= 200 * 4, classes.count >= 200 * 3, masks.count >= 200 * 108 * 108 else {
            throw DeviceVisibleCardStageError.invalidOutput
        }
        return try RfdetrRawOutput(
            queryCount: 200,
            classCount: 3,
            maskWidth: 108,
            maskHeight: 108,
            boxesCXCYWH: Self.values(boxes, count: 200 * 4),
            classLogits: Self.values(classes, count: 200 * 3),
            maskLogits: Self.values(masks, count: 200 * 108 * 108)
        )
    }

    private static func values(_ array: MLMultiArray, count: Int) -> [Float] {
        let strides = array.strides.map(\.intValue)
        let dimensions = array.shape.map(\.intValue)
        let total = min(count, dimensions.reduce(1, *))
        return (0..<total).map { flatIndex in
            var remaining = flatIndex
            var offset = 0
            for axis in dimensions.indices.reversed() {
                let coordinate = remaining % dimensions[axis]
                remaining /= dimensions[axis]
                offset += coordinate * strides[axis]
            }
            return array[offset].floatValue
        }
    }

    private static func directorySHA256(_ url: URL) throws -> String {
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory), isDirectory.boolValue,
              let enumerator = FileManager.default.enumerator(
                  at: url,
                  includingPropertiesForKeys: [.isRegularFileKey],
                  options: [.skipsHiddenFiles]
              ) else {
            throw DeviceVisibleCardStageError.invalidOutput
        }
        let files = (enumerator.allObjects as? [URL] ?? []).filter { fileURL in
            (try? fileURL.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true
        }.sorted { $0.path < $1.path }
        guard !files.isEmpty else { throw DeviceVisibleCardStageError.invalidOutput }
        var hasher = SHA256()
        for fileURL in files {
            hasher.update(data: Data(fileURL.path.replacingOccurrences(of: url.path + "/", with: "").utf8))
            hasher.update(data: Data([0]))
            let handle = try FileHandle(forReadingFrom: fileURL)
            while let data = try handle.read(upToCount: 1024 * 1024), !data.isEmpty {
                hasher.update(data: data)
            }
            try handle.close()
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }
}
