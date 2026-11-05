import Foundation

public enum DeviceVisualIdentityError: Error, Equatable {
  case invalidLogits
  case invalidObservationInput
}

public struct DeviceVisualIdentityCandidate: Codable, Equatable, Sendable {
  public let card: String
  public let probability: Double

  private enum CodingKeys: String, CodingKey {
    case card
    case probability
  }
}

public struct DeviceVisualIdentityResult: Codable, Equatable, Sendable {
  public let status: String
  public let classification: String
  public let candidates: [DeviceVisualIdentityCandidate]
  public let logits: [Double]
  public let rawProbabilities: [Double]
  public let probabilities: [Double]
  public let rankedTargets: [String]
  public let reviewThreshold: Double
  public let reviewThresholdPassed: Bool

  private enum CodingKeys: String, CodingKey {
    case status
    case classification
    case candidates
    case logits
    case rawProbabilities = "raw_probabilities"
    case probabilities
    case rankedTargets = "ranked_targets"
    case reviewThreshold = "review_threshold"
    case reviewThresholdPassed = "review_threshold_passed"
  }
}

public struct DeviceVisualIdentityOutcome: Codable, Equatable, Sendable {
  public let eventID: String
  public let cardID: String
  public let status: String
  public let cropPolicy: String
  public let cropPath: String?
  public let frameSHA256: String?
  public let cropSHA256: String?
  public let inputTensorSHA256: String?
  public let result: DeviceVisualIdentityResult?
  public let elapsedMs: Double
  public let error: String?

  public init(
    eventID: String, cardID: String, status: String, cropPolicy: String,
    cropPath: String? = nil,
    frameSHA256: String?, cropSHA256: String?, inputTensorSHA256: String?,
    result: DeviceVisualIdentityResult?, elapsedMs: Double, error: String?
  ) {
    self.eventID = eventID
    self.cardID = cardID
    self.status = status
    self.cropPolicy = cropPolicy
    self.cropPath = cropPath
    self.frameSHA256 = frameSHA256
    self.cropSHA256 = cropSHA256
    self.inputTensorSHA256 = inputTensorSHA256
    self.result = result
    self.elapsedMs = elapsedMs
    self.error = error
  }

  private enum CodingKeys: String, CodingKey {
    case eventID = "event_id"
    case cardID = "card_id"
    case status
    case cropPolicy = "crop_policy"
    case cropPath = "crop_path"
    case frameSHA256 = "frame_sha256"
    case cropSHA256 = "crop_sha256"
    case inputTensorSHA256 = "input_tensor_sha256"
    case result
    case elapsedMs = "elapsed_ms"
    case error
  }
}

public struct DeviceVisualIdentityRevision: Codable, Equatable, Sendable {
  public let schemaVersion: String
  public let stageID: String
  public let recordingID: String
  public let videoSHA256: String
  public let eventRevisionID: String
  public let visibleCardRevisionID: String
  public let modelPackageSHA256: String
  public let modelID: String
  public let classMap: [String: String]
  public let compiledModelSHA256: String?
  public let preprocessing: String
  public let temperature: Double
  public let reviewThreshold: Double
  public let status: String
  public let elapsedMs: Double
  public let outcomes: [DeviceVisualIdentityOutcome]

  public init(
    stageID: String, recordingID: String, videoSHA256: String,
    eventRevisionID: String, visibleCardRevisionID: String,
    compiledModelSHA256: String?, status: String, elapsedMs: Double,
    outcomes: [DeviceVisualIdentityOutcome]
  ) {
    schemaVersion = "doko-device-visual-identities/v1"
    self.stageID = stageID
    self.recordingID = recordingID
    self.videoSHA256 = videoSHA256
    self.eventRevisionID = eventRevisionID
    self.visibleCardRevisionID = visibleCardRevisionID
    modelPackageSHA256 = DeviceVisualIdentityPostprocessor.packageSHA256
    modelID = "facebook/dinov3-vits16-pretrain-lvd1689m"
    classMap = Dictionary(
      uniqueKeysWithValues: DeviceVisualIdentityPostprocessor.targets.enumerated().map {
        (String($0.offset), $0.element)
      })
    self.compiledModelSHA256 = compiledModelSHA256
    preprocessing =
      "predicted_visible_region;dinov3-identity-letterbox-v2;imagenet-normalization-v1"
    temperature = DeviceVisualIdentityPostprocessor.temperature
    reviewThreshold = DeviceVisualIdentityPostprocessor.reviewThreshold
    self.status = status
    self.elapsedMs = elapsedMs
    self.outcomes = outcomes
  }

  private enum CodingKeys: String, CodingKey {
    case schemaVersion = "schema_version"
    case stageID = "stage_id"
    case recordingID = "recording_id"
    case videoSHA256 = "video_sha256"
    case eventRevisionID = "event_revision_id"
    case visibleCardRevisionID = "visible_card_revision_id"
    case modelPackageSHA256 = "model_package_sha256"
    case modelID = "model_id"
    case classMap = "class_map"
    case compiledModelSHA256 = "compiled_model_sha256"
    case preprocessing
    case temperature
    case reviewThreshold = "review_threshold"
    case status
    case elapsedMs = "elapsed_ms"
    case outcomes
  }
}

/// Applies the frozen 0104 class map and calibration to one Core ML output vector.
public enum DeviceVisualIdentityPostprocessor {
  public static let packageSHA256 =
    "5e3af365eb1d0e7dd3543011a17189f68741dae926c3ec25e09c0fef358b1c25"
  public static let temperature = 0.6487642659364355
  public static let reviewThreshold = 0.8235859761473482
  public static let targets = [
    "CLUBS_NINE", "CLUBS_JACK", "CLUBS_QUEEN", "CLUBS_KING", "CLUBS_TEN", "CLUBS_ACE",
    "SPADES_NINE", "SPADES_JACK", "SPADES_QUEEN", "SPADES_KING", "SPADES_TEN", "SPADES_ACE",
    "HEARTS_NINE", "HEARTS_JACK", "HEARTS_QUEEN", "HEARTS_KING", "HEARTS_TEN", "HEARTS_ACE",
    "DIAMONDS_NINE", "DIAMONDS_JACK", "DIAMONDS_QUEEN", "DIAMONDS_KING", "DIAMONDS_TEN",
    "DIAMONDS_ACE", "FACE_DOWN",
  ]

  public static func process(_ logits: [Double]) throws -> DeviceVisualIdentityResult {
    guard logits.count == targets.count, logits.allSatisfy(\.isFinite) else {
      throw DeviceVisualIdentityError.invalidLogits
    }
    let raw = softmax(logits)
    let calibrated = softmax(logits.map { $0 / temperature })
    let order = targets.indices.sorted {
      calibrated[$0] == calibrated[$1] ? $0 < $1 : calibrated[$0] > calibrated[$1]
    }
    let faceDown = targets[order[0]] == "FACE_DOWN"
    let candidates =
      faceDown
      ? []
      : order.filter { targets[$0] != "FACE_DOWN" }.map {
        DeviceVisualIdentityCandidate(card: targets[$0], probability: calibrated[$0])
      }
    return DeviceVisualIdentityResult(
      status: faceDown ? "face_down" : "classified",
      classification: faceDown ? "face_down" : "identity",
      candidates: candidates,
      logits: logits,
      rawProbabilities: raw,
      probabilities: calibrated,
      rankedTargets: order.map { targets[$0] },
      reviewThreshold: reviewThreshold,
      reviewThresholdPassed: calibrated[order[0]] >= reviewThreshold
    )
  }

  private static func softmax(_ values: [Double]) -> [Double] {
    let maximum = values.max() ?? 0
    let exponents = values.map { exp($0 - maximum) }
    let total = exponents.reduce(0, +)
    return exponents.map { $0 / total }
  }
}

public struct DeviceObservationCard: Codable, Equatable, Sendable {
  public let observedCardID: String
  public let side: String
  public let identityStatus: String
  public let identityCandidates: [DeviceVisualIdentityCandidate]

  private enum CodingKeys: String, CodingKey {
    case observedCardID = "observed_card_id"
    case side
    case identityStatus = "identity_status"
    case identityCandidates = "identity_candidates"
  }
}

public struct DeviceObservationSource: Codable, Equatable, Sendable {
  public let recordingID: String
  public let videoSHA256: String
  public let assemblyRunID: String
  public let inputRevisionIDs: [String]

  private enum CodingKeys: String, CodingKey {
    case recordingID = "recording_id"
    case videoSHA256 = "video_sha256"
    case assemblyRunID = "assembly_run_id"
    case inputRevisionIDs = "input_revision_ids"
  }
}

public struct DeviceObservationSession: Codable, Equatable, Sendable {
  public let sessionID: String
  public let eventSequence: Int

  private enum CodingKeys: String, CodingKey {
    case sessionID = "session_id"
    case eventSequence = "event_sequence"
  }
}

public struct DeviceObservationAnalyzer: Codable, Equatable, Sendable {
  public let name: String
  public let version: String
}

public struct DeviceTableObservation: Codable, Equatable, Sendable {
  public let schemaVersion: String
  public let observationID: String
  public let source: DeviceObservationSource
  public let session: DeviceObservationSession
  public let observedAtMs: Int64
  public let status: String
  public let capabilities: [String]
  public let cards: [DeviceObservationCard]
  public let calibration: String
  public let analyzer: DeviceObservationAnalyzer
  public let diagnostics: [String: String]

  private enum CodingKeys: String, CodingKey {
    case schemaVersion = "schema_version"
    case observationID = "observation_id"
    case source
    case session
    case observedAtMs = "observed_at_ms"
    case status
    case capabilities
    case cards
    case calibration
    case analyzer
    case diagnostics
  }
}

/// Joins each saved event to its visible-card and identity evidence without assigning game state.
public enum DeviceTableObservationAssembler {
  public static func assemble(
    events: [DeviceVisibleCardEventResult],
    outcomesByEvent: [String: [String: DeviceVisualIdentityOutcome]],
    recordingID: String,
    videoSHA256: String,
    assemblyRunID: String,
    sessionID: String,
    eventRevisionID: String,
    visibleCardRevisionID: String,
    visualIdentityRevisionID: String
  ) throws -> [DeviceTableObservation] {
    let revisions = [eventRevisionID, visibleCardRevisionID, visualIdentityRevisionID]
    guard revisions.allSatisfy({ !$0.isEmpty }), Set(revisions).count == 3,
      !recordingID.isEmpty, !assemblyRunID.isEmpty, !sessionID.isEmpty,
      videoSHA256.count == 64, videoSHA256.allSatisfy({ $0.isHexDigit && !$0.isUppercase })
    else {
      throw DeviceVisualIdentityError.invalidObservationInput
    }
    return events.enumerated().map { index, event in
      let outcomes = outcomesByEvent[event.event.eventID] ?? [:]
      let cards = event.detections.enumerated().map { cardIndex, _ in
        let cardID = "\(event.event.eventID)-card-\(cardIndex + 1)"
        let outcome = outcomes[cardID]
        let result = outcome?.result
        let side: String
        if outcome?.status == "face_down" {
          side = "face_down"
        } else if outcome?.status == "classified" {
          side = "face_up"
        } else {
          side = "unknown"
        }
        return DeviceObservationCard(
          observedCardID: cardID,
          side: side,
          identityStatus: outcome?.status ?? (side == "face_down" ? "face_down" : "failed"),
          identityCandidates: result?.candidates ?? []
        )
      }
      let status =
        event.status == "failed" || event.status == "interrupted"
        ? "insufficient_evidence" : "observed"
      return DeviceTableObservation(
        schemaVersion: "table-observation/v1",
        observationID: "\(assemblyRunID)-observation-\(String(format: "%04d", index + 1))",
        source: DeviceObservationSource(
          recordingID: recordingID,
          videoSHA256: videoSHA256,
          assemblyRunID: assemblyRunID,
          inputRevisionIDs: revisions),
        session: DeviceObservationSession(sessionID: sessionID, eventSequence: index + 1),
        observedAtMs: Int64((event.event.timeS * 1_000).rounded(.towardZero)),
        status: status,
        capabilities: ["identity_candidates"],
        cards: event.status == "failed" || event.status == "interrupted" ? [] : cards,
        calibration: "uncalibrated",
        analyzer: DeviceObservationAnalyzer(name: "observation-assembler", version: "v1"),
        diagnostics: ["event_id": event.event.eventID]
      )
    }
  }
}
