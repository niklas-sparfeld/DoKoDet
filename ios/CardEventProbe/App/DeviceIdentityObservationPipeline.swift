import CoreGraphics
import CryptoKit
import Foundation
import ImageIO
import UniformTypeIdentifiers

/// Runs frozen DINOv3 on each visible-card proposal and retains the observation handoff.
final class DeviceIdentityObservationPipeline {
  private let fileManager = FileManager.default

  func run(
    recordingBundleURL: URL,
    visibleCardRevisionURL: URL,
    eventRevisionID: String,
    sessionID: String
  ) throws -> (DeviceVisualIdentityRevision, [DeviceTableObservation]) {
    let started = ProcessInfo.processInfo.systemUptime
    let visible = try JSONDecoder().decode(
      DeviceVisibleCardRevision.self, from: Data(contentsOf: visibleCardRevisionURL))
    guard !eventRevisionID.isEmpty, !sessionID.isEmpty,
      RepositoryIntakeContract.isIdentifier(visible.recordingID),
      RepositoryIntakeContract.isSHA256(visible.videoSHA256)
    else { throw DeviceVisibleCardStageError.invalidRun }

    let stageRoot =
      recordingBundleURL
      .appendingPathComponent(".device/stages/visual-identities", isDirectory: true)
    let cropRoot = stageRoot.appendingPathComponent("crops", isDirectory: true)
    try fileManager.createDirectory(at: cropRoot, withIntermediateDirectories: true)
    let needsModel = visible.events.contains { $0.status == "complete" && !$0.detections.isEmpty }
    let model = needsModel ? try DinoV3CoreMLRunner.loadBundled() : nil
    var outcomes: [DeviceVisualIdentityOutcome] = []
    var outcomesByEvent: [String: [String: DeviceVisualIdentityOutcome]] = [:]

    for event in visible.events {
      guard event.status == "complete" else {
        for index in event.detections.indices {
          let item = Self.failed(
            event: event, index: index,
            message: event.error ?? "The visible-card event is \(event.status).")
          outcomes.append(item)
          outcomesByEvent[event.event.eventID, default: [:]][item.cardID] = item
        }
        continue
      }
      guard let imagePath = event.imagePath,
        let frameDigest = event.imageSHA256,
        let image = Self.loadImage(recordingBundleURL.appendingPathComponent(imagePath))
      else {
        for index in event.detections.indices {
          let item = Self.failed(
            event: event, index: index, message: "The retained event frame is unavailable.")
          outcomes.append(item)
          outcomesByEvent[event.event.eventID, default: [:]][item.cardID] = item
        }
        continue
      }
      for (index, detection) in event.detections.enumerated() {
        let cardID = "\(event.event.eventID)-card-\(index + 1)"
        let itemStarted = ProcessInfo.processInfo.systemUptime
        guard let polygon = detection.polygon,
          let crop = try DeviceVisibleRegionCropper.crop(image: image, normalizedPolygon: polygon)
        else {
          let item = DeviceVisualIdentityOutcome(
            eventID: event.event.eventID, cardID: cardID, status: "unusable",
            cropPolicy: "predicted_visible_region", frameSHA256: frameDigest,
            cropSHA256: nil, inputTensorSHA256: nil, result: nil,
            elapsedMs: (ProcessInfo.processInfo.systemUptime - itemStarted) * 1_000,
            error: "The visible-card proposal has no usable polygon crop.")
          outcomes.append(item)
          outcomesByEvent[event.event.eventID, default: [:]][cardID] = item
          continue
        }
        do {
          let cropData = try Self.pngData(crop)
          let cropURL = cropRoot.appendingPathComponent("\(cardID).png")
          try cropData.write(to: cropURL, options: .atomic)
          guard let model else { throw DeviceVisibleCardStageError.modelUnavailable }
          let (result, values) = try model.predict(image: crop)
          let tensorBytes = values.withUnsafeBytes { Data($0) }
          let item = DeviceVisualIdentityOutcome(
            eventID: event.event.eventID, cardID: cardID, status: result.status,
            cropPolicy: "predicted_visible_region",
            cropPath: ".device/stages/visual-identities/crops/\(cardID).png",
            frameSHA256: frameDigest,
            cropSHA256: Self.sha256(cropData), inputTensorSHA256: Self.sha256(tensorBytes),
            result: result,
            elapsedMs: (ProcessInfo.processInfo.systemUptime - itemStarted) * 1_000,
            error: nil)
          outcomes.append(item)
          outcomesByEvent[event.event.eventID, default: [:]][cardID] = item
        } catch {
          let item = DeviceVisualIdentityOutcome(
            eventID: event.event.eventID, cardID: cardID, status: "failed",
            cropPolicy: "predicted_visible_region", frameSHA256: frameDigest,
            cropSHA256: nil, inputTensorSHA256: nil, result: nil,
            elapsedMs: (ProcessInfo.processInfo.systemUptime - itemStarted) * 1_000,
            error: error.localizedDescription)
          outcomes.append(item)
          outcomesByEvent[event.event.eventID, default: [:]][cardID] = item
        }
      }
    }

    let failed = visible.status != "complete" || outcomes.contains { $0.status == "failed" }
    let identityRevision = DeviceVisualIdentityRevision(
      stageID: "visual-identities-\(visible.recordingID)",
      recordingID: visible.recordingID, videoSHA256: visible.videoSHA256,
      eventRevisionID: eventRevisionID, visibleCardRevisionID: visible.stageID,
      compiledModelSHA256: model?.compiledModelSHA256,
      status: failed ? "failed" : "complete",
      elapsedMs: (ProcessInfo.processInfo.systemUptime - started) * 1_000,
      outcomes: outcomes)
    let observations = try DeviceTableObservationAssembler.assemble(
      events: visible.events, outcomesByEvent: outcomesByEvent,
      recordingID: visible.recordingID, videoSHA256: visible.videoSHA256,
      assemblyRunID: identityRevision.stageID, sessionID: sessionID,
      eventRevisionID: eventRevisionID, visibleCardRevisionID: visible.stageID,
      visualIdentityRevisionID: identityRevision.stageID)
    try Self.write(identityRevision, to: stageRoot.appendingPathComponent("revision.json"))
    try Self.write(observations, to: stageRoot.appendingPathComponent("table-observations.json"))
    return (identityRevision, observations)
  }

  private static func failed(
    event: DeviceVisibleCardEventResult, index: Int, message: String
  ) -> DeviceVisualIdentityOutcome {
    DeviceVisualIdentityOutcome(
      eventID: event.event.eventID, cardID: "\(event.event.eventID)-card-\(index + 1)",
      status: "failed", cropPolicy: "predicted_visible_region", frameSHA256: event.imageSHA256,
      cropSHA256: nil, inputTensorSHA256: nil, result: nil, elapsedMs: 0, error: message)
  }

  private static func loadImage(_ url: URL) -> CGImage? {
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
    return CGImageSourceCreateImageAtIndex(source, 0, nil)
  }

  private static func pngData(_ image: CGImage) throws -> Data {
    let data = NSMutableData()
    guard
      let destination = CGImageDestinationCreateWithData(
        data, UTType.png.identifier as CFString, 1, nil)
    else { throw DeviceVisibleCardStageError.invalidOutput }
    CGImageDestinationAddImage(destination, image, nil)
    guard CGImageDestinationFinalize(destination) else {
      throw DeviceVisibleCardStageError.invalidOutput
    }
    return data as Data
  }

  private static func sha256(_ data: Data) -> String {
    SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
  }

  private static func write<T: Encodable>(_ value: T, to url: URL) throws {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    try encoder.encode(value).write(to: url, options: .atomic)
  }
}
