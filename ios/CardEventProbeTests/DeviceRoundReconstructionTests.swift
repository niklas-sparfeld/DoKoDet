import Foundation
import XCTest

@testable import CardEventProbeCore

final class DeviceRoundReconstructionTests: XCTestCase {
  private let fixtureCards = [
    "DIAMONDS_JACK", "DIAMONDS_TEN", "CLUBS_JACK", "DIAMONDS_QUEEN", "SPADES_KING",
    "SPADES_ACE", "SPADES_TEN", "SPADES_TEN", "CLUBS_KING", "CLUBS_TEN", "CLUBS_KING",
    "CLUBS_ACE", "HEARTS_TEN", "DIAMONDS_ACE", "SPADES_JACK", "HEARTS_JACK",
    "DIAMONDS_TEN", "HEARTS_QUEEN", "SPADES_QUEEN", "HEARTS_QUEEN", "HEARTS_ACE",
    "HEARTS_KING", "HEARTS_KING", "SPADES_JACK", "CLUBS_QUEEN", "HEARTS_TEN",
    "DIAMONDS_KING", "SPADES_QUEEN", "HEARTS_ACE", "HEARTS_JACK", "DIAMONDS_QUEEN",
    "DIAMONDS_KING", "CLUBS_JACK", "DIAMONDS_ACE", "SPADES_KING", "CLUBS_TEN",
    "CLUBS_QUEEN", "DIAMONDS_JACK", "SPADES_ACE", "CLUBS_ACE",
  ]

  func testCompleteFixtureReconstructsAndRetainsTenTricks() throws {
    let context = try DeviceRoundAnalysisContext(
      recordingID: "recording-fixture", sessionID: "session-fixture")
    let (_, result) = try DeviceRoundReconstructor.run(
      observations: observations(fixtureCards), context: context)

    XCTAssertEqual(result.status, .resolved)
    let hypothesis = try XCTUnwrap(result.hypotheses.first)
    XCTAssertEqual(hypothesis.plays.count, 40)
    XCTAssertEqual(hypothesis.tricks.count, 10)
    XCTAssertEqual(hypothesis.plays.first?.card, fixtureCards[0])
    XCTAssertEqual(hypothesis.plays.first?.player, "player-1")
    XCTAssertTrue(hypothesis.plays.allSatisfy { !$0.inferred && $0.observedCardID != nil })
    XCTAssertGreaterThan(result.diagnostics.searchNodes, 0)
    XCTAssertGreaterThanOrEqual(result.diagnostics.elapsedMs, 0)
  }

  func testEmptyObservationsAreRetainedAsIncomplete() throws {
    let context = try DeviceRoundAnalysisContext(
      recordingID: "recording-empty", sessionID: "session-fixture")
    let (_, result) = try DeviceRoundReconstructor.run(observations: [], context: context)

    XCTAssertEqual(result.status, .incomplete)
    XCTAssertTrue(result.hypotheses.isEmpty)
    XCTAssertEqual(result.diagnostics.usableProposals, 0)
  }

  func testImpossibleDuplicateDeckEvidenceReturnsNoHypothesis() throws {
    var cards = Array(repeating: "CLUBS_JACK", count: 40)
    cards[2] = "DIAMONDS_JACK"
    cards[3] = "DIAMONDS_TEN"
    let context = try DeviceRoundAnalysisContext(
      recordingID: "recording-fixture", sessionID: "session-fixture")
    let (_, result) = try DeviceRoundReconstructor.run(
      observations: observations(cards), context: context,
      search: DeviceRoundAnalysisSearch(maxMissingPlays: 0))

    XCTAssertEqual(result.status, .impossible)
    XCTAssertTrue(result.hypotheses.isEmpty)
    XCTAssertGreaterThan(result.diagnostics.rejectedBranches, 0)
  }

  func testContextRequiresRecordingAndSessionAndObservationsMustMatchThem() throws {
    XCTAssertThrowsError(try DeviceRoundAnalysisContext(recordingID: "recording-x", sessionID: ""))

    let context = try DeviceRoundAnalysisContext(
      recordingID: "recording-other", sessionID: "session-fixture")
    XCTAssertThrowsError(
      try DeviceRoundReconstructor.run(
        observations: observations([fixtureCards[0]]), context: context))
  }

  func testSavedAnalysisReloadsAfterPipelineRun() throws {
    let bundle = FileManager.default.temporaryDirectory
      .appendingPathComponent("device-round-analysis-\(UUID().uuidString)", isDirectory: true)
    defer { try? FileManager.default.removeItem(at: bundle) }
    let stage = bundle.appendingPathComponent(".device/stages/visual-identities", isDirectory: true)
    try FileManager.default.createDirectory(at: stage, withIntermediateDirectories: true)
    let input = try JSONEncoder().encode(observations(fixtureCards))
    try input.write(to: stage.appendingPathComponent("table-observations.json"), options: .atomic)

    let result = try DeviceRoundAnalysisPipeline().run(
      recordingBundleURL: bundle, recordingID: "recording-fixture", sessionID: "session-fixture")
    let store = DeviceRoundAnalysisStore(
      directoryURL: bundle.appendingPathComponent(
        ".device/stages/round-analysis/\(result.analysisID)", isDirectory: true))
    let reloaded = try XCTUnwrap(store.load())

    XCTAssertEqual(result.status, .resolved)
    XCTAssertEqual(reloaded.0.context.gameID, "game-recording-fixture")
    XCTAssertEqual(reloaded.0.context.roundID, "round-recording-fixture")
    XCTAssertEqual(
      reloaded.0.context.activePlayers, ["player-1", "player-2", "player-3", "player-4"])
    XCTAssertEqual(reloaded.0.context.dealer, "dealer-unspecified")
    XCTAssertEqual(reloaded.0.context.firstTrickLeader, "player-1")
    XCTAssertEqual(reloaded.1, result)
    let log = try String(
      contentsOf: bundle.appendingPathComponent(
        ".device/stages/round-analysis/\(result.analysisID)/run.log"), encoding: .utf8)
    XCTAssertTrue(log.contains("stage=round-analysis"))
    let archive = try Data(contentsOf: store.makeDiagnosticArchive())
    XCTAssertEqual(Array(archive.prefix(4)), [0x50, 0x4b, 0x03, 0x04])
    let archiveText = String(decoding: archive, as: UTF8.self)
    XCTAssertTrue(archiveText.contains("table-observations.json"))
    XCTAssertTrue(archiveText.contains("run.log"))
  }

  func testPipelineRetainsMissingSessionFailure() throws {
    let bundle = FileManager.default.temporaryDirectory
      .appendingPathComponent(
        "device-round-analysis-failure-\(UUID().uuidString)", isDirectory: true)
    defer { try? FileManager.default.removeItem(at: bundle) }
    let stage = bundle.appendingPathComponent(".device/stages/visual-identities", isDirectory: true)
    try FileManager.default.createDirectory(at: stage, withIntermediateDirectories: true)
    let input = try JSONEncoder().encode(observations(fixtureCards))
    try input.write(to: stage.appendingPathComponent("table-observations.json"), options: .atomic)

    XCTAssertThrowsError(
      try DeviceRoundAnalysisPipeline().run(
        recordingBundleURL: bundle, recordingID: "recording-fixture", sessionID: ""))
    let root = bundle.appendingPathComponent(".device/stages/round-analysis", isDirectory: true)
    let run = try XCTUnwrap(
      FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil).first)
    let failure = try JSONDecoder().decode(
      DeviceRoundAnalysisFailure.self,
      from: Data(contentsOf: run.appendingPathComponent("failure.json")))
    XCTAssertEqual(failure.stage, "round-analysis")
    XCTAssertTrue(failure.error.contains("session"))
    XCTAssertTrue(
      FileManager.default.fileExists(atPath: run.appendingPathComponent("diagnostics.zip").path))
  }

  func testPipelineRetainsMissingObservationInputAndExportableFailure() throws {
    let bundle = FileManager.default.temporaryDirectory
      .appendingPathComponent(
        "device-round-analysis-no-input-\(UUID().uuidString)", isDirectory: true)
    defer { try? FileManager.default.removeItem(at: bundle) }

    XCTAssertThrowsError(
      try DeviceRoundAnalysisPipeline().run(
        recordingBundleURL: bundle, recordingID: "recording-fixture", sessionID: "session-fixture"))
    let root = bundle.appendingPathComponent(".device/stages/round-analysis", isDirectory: true)
    let run = try XCTUnwrap(
      FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil).first)
    let failure = try JSONDecoder().decode(
      DeviceRoundAnalysisFailure.self,
      from: Data(contentsOf: run.appendingPathComponent("failure.json")))
    XCTAssertEqual(failure.stage, "round-analysis")
    XCTAssertTrue(failure.error.contains("table-observations"))
    XCTAssertTrue(
      FileManager.default.fileExists(atPath: run.appendingPathComponent("diagnostics.zip").path))
  }

  private func observations(_ cards: [String]) -> [DeviceTableObservation] {
    cards.enumerated().map { index, card in
      DeviceTableObservation(
        schemaVersion: "table-observation/v1",
        observationID: "observation-\(index + 1)",
        source: DeviceObservationSource(
          recordingID: "recording-fixture", videoSHA256: String(repeating: "a", count: 64),
          assemblyRunID: "assembly-fixture",
          inputRevisionIDs: ["events-fixture", "visible-fixture", "identity-fixture"]),
        session: DeviceObservationSession(sessionID: "session-fixture", eventSequence: index + 1),
        observedAtMs: Int64(index * 1_000), status: "observed",
        capabilities: ["identity_candidates"],
        cards: [
          DeviceObservationCard(
            observedCardID: "card-\(index + 1)", side: "face_up", identityStatus: "classified",
            identityCandidates: [DeviceVisualIdentityCandidate(card: card, probability: 1)])
        ],
        calibration: "fixture",
        analyzer: DeviceObservationAnalyzer(name: "fixture", version: "v1"), diagnostics: [:])
    }
  }
}
