import Foundation

struct DevicePostCaptureResult {
  let analysis: DeviceRoundAnalysisResult
  let diagnosticDirectory: URL
}

/// Runs the frozen local stages after capture, in dependency order.
final class DevicePostCapturePipeline {
  private let visibleCards = DeviceVisibleCardPipeline()
  private let identities = DeviceIdentityObservationPipeline()

  func run(recordingBundleURL: URL, onProgress: (String) -> Void) throws -> DevicePostCaptureResult
  {
    let manifestURL = recordingBundleURL.appendingPathComponent("manifest.json")
    let manifest = try JSONDecoder().decode(
      RepositoryBundle.self, from: Data(contentsOf: manifestURL))
    guard let eventRevisionID = manifest.files.proposalGeneratorRuns.first?.proposalGeneratorRunID
    else {
      throw DeviceVisibleCardStageError.proposalUnavailable
    }

    let deviceRoot = recordingBundleURL.appendingPathComponent(".device", isDirectory: true)
    let runLogURL = deviceRoot.appendingPathComponent("run.log")
    func log(_ stage: String, _ outcome: String, elapsedMs: Double? = nil, detail: String? = nil) {
      let timestamp = ISO8601DateFormatter().string(from: Date())
      var line = "\(timestamp) \(outcome) run=\(manifest.recordingID) stage=\(stage)"
      if let elapsedMs { line += " elapsed_ms=\(elapsedMs)" }
      if let detail { line += " message=\(detail.replacingOccurrences(of: "\n", with: " "))" }
      line += "\n"
      if let data = line.data(using: .utf8) {
        if FileManager.default.fileExists(atPath: runLogURL.path),
          let handle = try? FileHandle(forWritingTo: runLogURL)
        {
          try? handle.seekToEnd()
          try? handle.write(contentsOf: data)
          try? handle.close()
        } else {
          try? FileManager.default.createDirectory(
            at: deviceRoot, withIntermediateDirectories: true)
          try? data.write(to: runLogURL, options: .atomic)
        }
      }
    }

    var activeStage = "visible-cards"
    do {
      onProgress("Detecting visible cards")
      let visibleStart = ProcessInfo.processInfo.systemUptime
      log("visible-cards", "info", detail: "start")
      let visible = try visibleCards.run(recordingBundleURL: recordingBundleURL)
      log(
        "visible-cards", "info",
        elapsedMs: (ProcessInfo.processInfo.systemUptime - visibleStart) * 1_000,
        detail: "finish status=\(visible.status) events=\(visible.events.count)")
      guard visible.status == "complete" else {
        throw DevicePostCaptureError.stageFailed(
          "visible-cards", "Visible-card detection ended with status \(visible.status).")
      }

      onProgress("Selecting table calibration")
      activeStage = "calibration"
      let calibrationStart = ProcessInfo.processInfo.systemUptime
      log("calibration", "info", detail: "start")
      let calibrationResult = try DeviceRecordingCalibrationSelector.calibrate(revision: visible)
      let calibrationRoot = deviceRoot.appendingPathComponent(
        "stages/calibration", isDirectory: true)
      try FileManager.default.createDirectory(
        at: calibrationRoot, withIntermediateDirectories: true)
      try Self.writeJSON(
        [
          "recording_id": manifest.recordingID,
          "visible_card_revision_id": visible.stageID,
          "status": calibrationResult.status,
          "failure_code": calibrationResult.failureCode as Any? ?? NSNull(),
          "failure_message": calibrationResult.failureMessage as Any? ?? NSNull(),
          "candidate_decisions": calibrationResult.candidateDecisions,
          "candidate_count": calibrationResult.candidateEvidence.count,
          "candidate_evidence": calibrationResult.candidateEvidence.map { candidate in
            [
              "candidate_id": candidate.candidateID,
              "source_revision": candidate.sourceRevision,
              "source_frame_id": candidate.sourceFrameID,
              "decision": candidate.decision,
              "accepted": candidate.accepted,
              "rejection_reason": candidate.rejectionReason as Any? ?? NSNull(),
              "confidence": candidate.confidence,
              "quality_score": candidate.qualityScore,
              "quality_metrics": candidate.qualityMetrics,
              "receipt_digest": candidate.receiptDigest,
            ] as [String: Any]
          },
          "gates": calibrationResult.gates,
          "calibration": calibrationResult.calibration?.toMapping() as Any? ?? NSNull(),
        ], to: calibrationRoot.appendingPathComponent("result.json"))
      log(
        "calibration", "info",
        elapsedMs: (ProcessInfo.processInfo.systemUptime - calibrationStart) * 1_000,
        detail: "finish status=\(calibrationResult.status)")
      guard let calibration = calibrationResult.calibration else {
        throw DevicePostCaptureError.stageFailed(
          "calibration",
          calibrationResult.failureMessage ?? "No valid table calibration was published.")
      }

      onProgress("Fitting proposed card scenes")
      activeStage = "proposed-card-scenes"
      let sceneStart = ProcessInfo.processInfo.systemUptime
      log("proposed-card-scenes", "info", detail: "start")
      let frames = try Self.sceneInputs(from: visible)
      let scenes = try DeviceProposedCardSceneInitializer.initialize(
        frames: frames,
        detectorRevisionID: visible.stageID,
        detectorRevisionDigest: visible.videoSHA256,
        calibration: calibration
      )
      let sceneRoot = deviceRoot.appendingPathComponent(
        "stages/proposed-card-scenes", isDirectory: true)
      try FileManager.default.createDirectory(at: sceneRoot, withIntermediateDirectories: true)
      try Self.writeJSON(
        Self.sceneMapping(scenes), to: sceneRoot.appendingPathComponent("result.json"))
      log(
        "proposed-card-scenes", "info",
        elapsedMs: (ProcessInfo.processInfo.systemUptime - sceneStart) * 1_000,
        detail: "finish status=\(scenes.status) frames=\(scenes.frames.count)")
      guard scenes.status != "failed" else {
        throw DevicePostCaptureError.stageFailed(
          "proposed-card-scenes", "No card scene could be fitted.")
      }

      onProgress("Classifying visible cards")
      activeStage = "visual-identities"
      let identityStart = ProcessInfo.processInfo.systemUptime
      log("visual-identities", "info", detail: "start")
      let visibleURL = deviceRoot.appendingPathComponent("stages/visible-cards/revision.json")
      let (identityRevision, _) = try identities.run(
        recordingBundleURL: recordingBundleURL,
        visibleCardRevisionURL: visibleURL,
        eventRevisionID: eventRevisionID,
        sessionID: manifest.sessionID
      )
      log(
        "visual-identities", "info",
        elapsedMs: (ProcessInfo.processInfo.systemUptime - identityStart) * 1_000,
        detail:
          "finish status=\(identityRevision.status) outcomes=\(identityRevision.outcomes.count)")
      guard identityRevision.status != "failed" else {
        throw DevicePostCaptureError.stageFailed(
          "visual-identities", "Visual identity processing failed. See the saved stage results.")
      }

      onProgress("Reconstructing round")
      activeStage = "round-analysis"
      let analysisStart = ProcessInfo.processInfo.systemUptime
      log("round-analysis", "info", detail: "start")
      let analysis = try DeviceRoundAnalysisPipeline().run(
        recordingBundleURL: recordingBundleURL,
        recordingID: manifest.recordingID,
        sessionID: manifest.sessionID
      )
      log(
        "round-analysis", "info",
        elapsedMs: (ProcessInfo.processInfo.systemUptime - analysisStart) * 1_000,
        detail: "finish status=\(analysis.status.rawValue)")
      let analysisDirectory =
        deviceRoot
        .appendingPathComponent("stages/round-analysis", isDirectory: true)
        .appendingPathComponent(analysis.analysisID, isDirectory: true)
      _ = try DeviceRoundAnalysisStore(directoryURL: analysisDirectory).makeDiagnosticArchive()
      return DevicePostCaptureResult(analysis: analysis, diagnosticDirectory: analysisDirectory)
    } catch {
      let stage = (error as? DevicePostCaptureError)?.stage ?? activeStage
      log(stage, "error", detail: error.localizedDescription)
      let analysisID = UUID().uuidString.lowercased()
      let store = DeviceRoundAnalysisStore(
        directoryURL:
          deviceRoot
          .appendingPathComponent("stages/round-analysis", isDirectory: true)
          .appendingPathComponent(analysisID, isDirectory: true))
      try? store.saveFailure(
        analysisID: analysisID,
        recordingID: manifest.recordingID,
        error: error,
        stage: stage
      )
      _ = try? store.makeDiagnosticArchive()
      throw error
    }
  }

  private static func sceneInputs(from revision: DeviceVisibleCardRevision) throws
    -> [DeviceSceneFrameInput]
  {
    try revision.events.map { event in
      guard let digest = event.imageSHA256,
        let width = event.imageWidth,
        let height = event.imageHeight
      else {
        throw DevicePostCaptureError.stageFailed(
          "proposed-card-scenes", "An event frame or its digest is missing.")
      }
      let candidates = try event.detections.enumerated().compactMap {
        index, detection -> DeviceSceneCandidate? in
        guard let polygon = detection.polygon else { return nil }
        let points = try polygon.map { point -> DevicePoint2D in
          guard point.count == 2 else {
            throw DevicePostCaptureError.stageFailed(
              "proposed-card-scenes", "A detector polygon is malformed.")
          }
          return try DevicePoint2D(x: Double(point[0]), y: Double(point[1]))
        }
        return DeviceSceneCandidate(
          candidateID: "\(event.event.eventID)-card-\(index + 1)",
          polygons: [points], confidence: detection.score
        )
      }
      let status =
        event.status == "complete"
        ? (candidates.isEmpty ? "empty" : "detected") : event.status
      return DeviceSceneFrameInput(
        frameID: event.event.eventID,
        sourceFrameDigest: digest,
        width: width,
        height: height,
        status: status,
        candidates: candidates
      )
    }
  }

  private static func sceneMapping(_ revision: DeviceProposedCardSceneRevision) -> [String: Any] {
    [
      "detector_revision_id": revision.detectorRevisionID,
      "detector_revision_digest": revision.detectorRevisionDigest,
      "calibration_revision_id": revision.calibrationRevisionID,
      "calibration_digest": revision.calibrationDigest,
      "status": revision.status,
      "frames": revision.frames.map { frame in
        [
          "frame_id": frame.frameID,
          "source_frame_sha256": frame.sourceFrameDigest,
          "status": frame.status,
          "poses": frame.poses.map { pose in
            [
              "card_id": pose.cardID, "candidate_id": pose.sourceCandidateID,
              "center": [pose.center.x, pose.center.y], "rotation_degrees": pose.rotationDegrees,
              "fit_residual": pose.fitResidual,
            ] as [String: Any]
          },
          "order_evidence": frame.orderEvidence.map { evidence in
            [
              "left_card_id": evidence.leftCardID, "right_card_id": evidence.rightCardID,
              "overlap_area_pixels": evidence.overlapAreaPixels,
              "left_support": evidence.leftSupport,
              "right_support": evidence.rightSupport, "decision": evidence.decision,
            ] as [String: Any]
          },
          "uncertain_order_pairs": frame.uncertainOrderPairs,
          "failure_reasons": frame.failureReasons,
          "joint_fit": frame.jointFit.map { fit in
            [
              "status": fit.status, "score": fit.score as Any? ?? NSNull(),
              "baseline_score": fit.baselineScore as Any? ?? NSNull(),
              "margin": fit.margin as Any? ?? NSNull(),
              "elapsed_ms": fit.elapsedMilliseconds, "estimated_peak_bytes": fit.estimatedPeakBytes,
            ] as [String: Any]
          } as Any? ?? NSNull(),
        ] as [String: Any]
      },
    ]
  }

  private static func writeJSON(_ value: Any, to url: URL) throws {
    let data = try JSONSerialization.data(
      withJSONObject: value, options: [.prettyPrinted, .sortedKeys])
    try data.write(to: url, options: .atomic)
  }
}

private enum DevicePostCaptureError: LocalizedError {
  case stageFailed(String, String)

  var stage: String {
    if case .stageFailed(let stage, _) = self { return stage }
    return "post-capture"
  }

  var errorDescription: String? {
    if case .stageFailed(_, let message) = self { return message }
    return "On-device post-capture processing failed."
  }
}
