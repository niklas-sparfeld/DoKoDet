import Foundation

public let deviceRoundAnalysisSchemaVersion = "doko-device-round-analysis/v1"

public enum DeviceRoundAnalysisError: LocalizedError, Equatable {
  case invalidContext
  case invalidObservations(String)

  public var errorDescription: String? {
    switch self {
    case .invalidContext:
      return "Recording, session, and round context are required for analysis."
    case .invalidObservations(let message):
      return message
    }
  }
}

/// Automatic round context used by the local PoC. These defaults do not assert gameplay facts.
public struct DeviceRoundAnalysisContext: Codable, Equatable, Sendable {
  public let recordingID: String
  public let sessionID: String
  public let gameID: String
  public let roundID: String
  public let activePlayers: [String]
  public let dealer: String
  public let firstTrickLeader: String
  public let rulesVersion: String
  public let deckVariant: String

  public init(recordingID: String, sessionID: String) throws {
    guard Self.isIdentifier(recordingID), Self.isIdentifier(sessionID),
      Self.isIdentifier("game-\(recordingID)"), Self.isIdentifier("round-\(recordingID)")
    else { throw DeviceRoundAnalysisError.invalidContext }
    self.recordingID = recordingID
    self.sessionID = sessionID
    gameID = "game-\(recordingID)"
    roundID = "round-\(recordingID)"
    activePlayers = ["player-1", "player-2", "player-3", "player-4"]
    dealer = "dealer-unspecified"
    firstTrickLeader = "player-1"
    rulesVersion = "v1"
    deckVariant = "doko-40-v1"
  }

  private static func isIdentifier(_ value: String) -> Bool {
    guard value.count <= 128, let first = value.first,
      first.isASCII && (first.isLetter || first.isNumber)
    else { return false }
    return value.allSatisfy {
      $0.isASCII && ($0.isLetter || $0.isNumber || "._:-".contains($0))
    }
  }
}

public struct DeviceRoundAnalysisSearch: Codable, Equatable, Sendable {
  public let maxMissingPlays: Int
  public let maxHypotheses: Int
  public let maxSearchNodes: Int

  public init(maxMissingPlays: Int = 1, maxHypotheses: Int = 256, maxSearchNodes: Int = 250_000) {
    self.maxMissingPlays = maxMissingPlays
    self.maxHypotheses = maxHypotheses
    self.maxSearchNodes = maxSearchNodes
  }

  private enum CodingKeys: String, CodingKey {
    case maxMissingPlays = "max_missing_plays"
    case maxHypotheses = "max_hypotheses"
    case maxSearchNodes = "max_search_nodes"
  }
}

public struct DeviceRoundAnalysisRequest: Codable, Equatable, Sendable {
  public let schemaVersion: String
  public let analysisID: String
  public let context: DeviceRoundAnalysisContext
  public let observationRevisionIDs: [String]
  public let search: DeviceRoundAnalysisSearch

  public init(
    analysisID: String, context: DeviceRoundAnalysisContext, observationRevisionIDs: [String],
    search: DeviceRoundAnalysisSearch = DeviceRoundAnalysisSearch()
  ) {
    schemaVersion = "doko-device-round-analysis-request/v1"
    self.analysisID = analysisID
    self.context = context
    self.observationRevisionIDs = observationRevisionIDs
    self.search = search
  }

  private enum CodingKeys: String, CodingKey {
    case schemaVersion = "schema_version"
    case analysisID = "analysis_id"
    case context
    case observationRevisionIDs = "observation_revision_ids"
    case search
  }
}

public struct DeviceRoundAnalysisPlay: Codable, Equatable, Sendable {
  public let playIndex: Int
  public let player: String
  public let card: String
  public let observationID: String?
  public let observedCardID: String?
  public let inferred: Bool

  private enum CodingKeys: String, CodingKey {
    case playIndex = "play_index"
    case player
    case card
    case observationID = "observation_id"
    case observedCardID = "observed_card_id"
    case inferred
  }
}

public struct DeviceRoundAnalysisTrick: Codable, Equatable, Sendable {
  public let trickIndex: Int
  public let leader: String
  public let winner: String
  public let winningCard: String

  private enum CodingKeys: String, CodingKey {
    case trickIndex = "trick_index"
    case leader
    case winner
    case winningCard = "winning_card"
  }
}

public struct DeviceRoundAnalysisHypothesis: Codable, Equatable, Sendable {
  public let plays: [DeviceRoundAnalysisPlay]
  public let tricks: [DeviceRoundAnalysisTrick]
  public let score: Double

  private enum CodingKeys: String, CodingKey {
    case plays
    case tricks
    case score
  }
}

public struct DeviceRoundAnalysisDiagnostics: Codable, Equatable, Sendable {
  public let observationsSeen: Int
  public let cardProposalsSeen: Int
  public let usableProposals: Int
  public let searchNodes: Int
  public let completeBranches: Int
  public let rejectedBranches: Int
  public let inferredMissingPlayCount: Int
  public let truncated: Bool
  public let elapsedMs: Double

  private enum CodingKeys: String, CodingKey {
    case observationsSeen = "observations_seen"
    case cardProposalsSeen = "card_proposals_seen"
    case usableProposals = "usable_proposals"
    case searchNodes = "search_nodes"
    case completeBranches = "complete_branches"
    case rejectedBranches = "rejected_branches"
    case inferredMissingPlayCount = "inferred_missing_play_count"
    case truncated
    case elapsedMs = "elapsed_ms"
  }
}

public struct DeviceRoundAnalysisResult: Codable, Equatable, Sendable {
  public let schemaVersion: String
  public let analysisID: String
  public let recordingID: String
  public let status: RoundAnalysisReconstructionStatus
  public let terminalStatus: String
  public let hypotheses: [DeviceRoundAnalysisHypothesis]
  public let diagnostics: DeviceRoundAnalysisDiagnostics
  public let failure: String?

  private enum CodingKeys: String, CodingKey {
    case schemaVersion = "schema_version"
    case analysisID = "analysis_id"
    case recordingID = "recording_id"
    case status
    case terminalStatus = "terminal_status"
    case hypotheses
    case diagnostics
    case failure
  }
}

public struct DeviceRoundAnalysisFailure: Codable, Equatable, Sendable {
  public let schemaVersion: String
  public let analysisID: String
  public let recordingID: String
  public let stage: String
  public let error: String
  public let failedAtUTC: String

  private enum CodingKeys: String, CodingKey {
    case schemaVersion = "schema_version"
    case analysisID = "analysis_id"
    case recordingID = "recording_id"
    case stage
    case error
    case failedAtUTC = "failed_at_utc"
  }
}

/// Bounded identity-only reconstruction with deterministic Doko V1 replay checks.
public enum DeviceRoundReconstructor {
  private struct Token {
    let observationID: String
    let cardID: String
    let candidates: [DeviceVisualIdentityCandidate]
  }

  private struct SearchState {
    var observationIndex: Int
    var plays: [DeviceRoundAnalysisPlay]
    var trickCards: [(player: String, card: String)]
    var leader: String
    var cardCounts: [String: Int]
    var playerCounts: [String: Int]
    var score: Double
  }

  private static let suits = ["CLUBS", "SPADES", "HEARTS", "DIAMONDS"]
  private static let ranks = ["JACK", "QUEEN", "KING", "TEN", "ACE"]
  private static let cards = suits.flatMap { suit in ranks.map { "\(suit)_\($0)" } }
  private static let trumpHighToLow = [
    "HEARTS_TEN", "CLUBS_QUEEN", "SPADES_QUEEN", "HEARTS_QUEEN", "DIAMONDS_QUEEN",
    "CLUBS_JACK", "SPADES_JACK", "HEARTS_JACK", "DIAMONDS_JACK", "DIAMONDS_ACE",
    "DIAMONDS_TEN", "DIAMONDS_KING", "DIAMONDS_NINE",
  ]
  private static let plainHighToLow = ["ACE", "TEN", "KING", "NINE"]

  public static func run(
    observations: [DeviceTableObservation], context: DeviceRoundAnalysisContext,
    search: DeviceRoundAnalysisSearch = DeviceRoundAnalysisSearch(),
    analysisID: String = UUID().uuidString.lowercased()
  ) throws -> (DeviceRoundAnalysisRequest, DeviceRoundAnalysisResult) {
    let started = ProcessInfo.processInfo.systemUptime
    guard search.maxMissingPlays >= 0, search.maxHypotheses > 0, search.maxSearchNodes > 0,
      context.activePlayers.count == 4, Set(context.activePlayers).count == 4,
      context.activePlayers.contains(context.firstTrickLeader), context.deckVariant == "doko-40-v1",
      context.rulesVersion == "v1"
    else { throw DeviceRoundAnalysisError.invalidContext }

    let sorted = observations.sorted {
      ($0.observedAtMs, $0.session.eventSequence, $0.observationID)
        < ($1.observedAtMs, $1.session.eventSequence, $1.observationID)
    }
    guard
      sorted.allSatisfy({
        $0.schemaVersion == "table-observation/v1"
          && $0.source.recordingID == context.recordingID
          && Self.isSHA256($0.source.videoSHA256)
          && !$0.source.assemblyRunID.isEmpty
          && $0.session.sessionID == context.sessionID
          && $0.source.inputRevisionIDs.count == 3
          && Set($0.source.inputRevisionIDs).count == 3
      })
    else {
      throw DeviceRoundAnalysisError.invalidObservations(
        "Saved table observations do not match the recording, session, or source revisions.")
    }
    let revisionIDs = sorted.first?.source.inputRevisionIDs ?? []
    guard
      sorted.allSatisfy({
        $0.source.inputRevisionIDs == revisionIDs
          && $0.source.videoSHA256 == sorted.first?.source.videoSHA256
          && $0.source.assemblyRunID == sorted.first?.source.assemblyRunID
      }), Set(sorted.map(\.observationID)).count == sorted.count
    else {
      throw DeviceRoundAnalysisError.invalidObservations(
        "Saved table observations mix different source revisions.")
    }
    var tokens: [Token] = []
    for observation in sorted {
      for card in observation.cards where !card.identityCandidates.isEmpty {
        tokens.append(
          Token(
            observationID: observation.observationID, cardID: card.observedCardID,
            candidates: card.identityCandidates))
      }
    }
    let request = DeviceRoundAnalysisRequest(
      analysisID: analysisID, context: context, observationRevisionIDs: revisionIDs, search: search)
    var nodes = 0
    var complete = 0
    var rejected = 0
    var truncated = false
    var results: [String: DeviceRoundAnalysisHypothesis] = [:]

    func retain(_ state: SearchState) {
      guard state.plays.count == 40, state.observationIndex == tokens.count,
        let tricks = replay(state.plays, context: context)
      else {
        rejected += 1
        return
      }
      complete += 1
      let key = playKey(state.plays)
      if results[key] == nil || results[key]!.score < state.score {
        results[key] = DeviceRoundAnalysisHypothesis(
          plays: state.plays, tricks: tricks, score: state.score)
      }
      if results.count > search.maxHypotheses {
        let worst = results.min { lhs, rhs in
          lhs.value.score == rhs.value.score
            ? playKey(lhs.value.plays) > playKey(rhs.value.plays)
            : lhs.value.score < rhs.value.score
        }!.key
        results.removeValue(forKey: worst)
      }
    }

    func walk(_ state: SearchState, missing: Int) {
      guard nodes < search.maxSearchNodes else {
        truncated = true
        return
      }
      nodes += 1
      if state.plays.count == 40 {
        retain(state)
        return
      }
      let remaining = tokens.count - state.observationIndex
      if state.plays.count + remaining + (search.maxMissingPlays - missing) < 40 {
        rejected += 1
        return
      }

      if missing < search.maxMissingPlays {
        let cardOptions = cards.filter { state.cardCounts[$0, default: 0] < 2 }
        for card in cardOptions {
          var next = state
          guard append(card, token: nil, to: &next, context: context) else { continue }
          next.score -= 0.75
          walk(next, missing: missing + 1)
          if truncated && nodes >= search.maxSearchNodes { return }
        }
      }

      guard state.observationIndex < tokens.count else { return }
      let token = tokens[state.observationIndex]
      for candidate in token.candidates {
        guard cards.contains(candidate.card), state.cardCounts[candidate.card, default: 0] < 2
        else {
          rejected += 1
          continue
        }
        var next = state
        next.observationIndex += 1
        guard append(candidate.card, token: token, to: &next, context: context) else { continue }
        next.score += log(candidate.probability)
        walk(next, missing: missing)
        if truncated && nodes >= search.maxSearchNodes { return }
      }
    }

    walk(
      SearchState(
        observationIndex: 0, plays: [], trickCards: [], leader: context.firstTrickLeader,
        cardCounts: [:], playerCounts: [:], score: 0), missing: 0)
    let hypotheses = results.values.sorted {
      $0.score == $1.score ? playKey($0.plays) < playKey($1.plays) : $0.score > $1.score
    }
    let status: RoundAnalysisReconstructionStatus
    if truncated && !hypotheses.isEmpty {
      status = .ambiguous
    } else if !hypotheses.isEmpty {
      status = hypotheses.count == 1 ? .resolved : .ambiguous
    } else if tokens.count < 40 {
      status = .incomplete
    } else {
      status = .impossible
    }
    let inferredCount = hypotheses.first?.plays.filter(\.inferred).count ?? 0
    let result = DeviceRoundAnalysisResult(
      schemaVersion: deviceRoundAnalysisSchemaVersion, analysisID: analysisID,
      recordingID: context.recordingID, status: status, terminalStatus: "complete",
      hypotheses: hypotheses,
      diagnostics: DeviceRoundAnalysisDiagnostics(
        observationsSeen: observations.count,
        cardProposalsSeen: sorted.reduce(0) { $0 + $1.cards.count }, usableProposals: tokens.count,
        searchNodes: nodes, completeBranches: complete, rejectedBranches: rejected,
        inferredMissingPlayCount: inferredCount, truncated: truncated,
        elapsedMs: (ProcessInfo.processInfo.systemUptime - started) * 1_000),
      failure: hypotheses.isEmpty
        ? (status == .incomplete
          ? "The saved observations do not contain enough usable card proposals for a complete round."
          : "No legal complete round survived deck-copy and trick-rule validation.")
        : (truncated ? "The search limit was reached; retained hypotheses may be incomplete." : nil)
    )
    return (request, result)
  }

  private static func append(
    _ card: String, token: Token?, to state: inout SearchState,
    context: DeviceRoundAnalysisContext
  ) -> Bool {
    let players = context.activePlayers
    guard state.plays.count < 40 else { return false }
    let trickOffset = state.trickCards.count
    let leaderIndex = players.firstIndex(of: state.leader)!
    let player = players[(leaderIndex + trickOffset) % players.count]
    guard state.playerCounts[player, default: 0] < 10 else { return false }
    state.cardCounts[card, default: 0] += 1
    state.playerCounts[player, default: 0] += 1
    state.plays.append(
      DeviceRoundAnalysisPlay(
        playIndex: state.plays.count + 1, player: player, card: card,
        observationID: token?.observationID, observedCardID: token?.cardID, inferred: token == nil))
    state.trickCards.append((player, card))
    if state.trickCards.count == 4 {
      state.leader = trickWinner(state.trickCards).player
      state.trickCards.removeAll(keepingCapacity: true)
    }
    return true
  }

  private static func replay(
    _ plays: [DeviceRoundAnalysisPlay], context: DeviceRoundAnalysisContext
  ) -> [DeviceRoundAnalysisTrick]? {
    guard plays.count == 40 else { return nil }
    var hands = Dictionary(uniqueKeysWithValues: context.activePlayers.map { ($0, [String]()) })
    for play in plays { hands[play.player, default: []].append(play.card) }
    var remaining = hands
    var leader = context.firstTrickLeader
    var tricks: [DeviceRoundAnalysisTrick] = []
    for index in stride(from: 0, to: plays.count, by: 4) {
      let trick = Array(plays[index..<(index + 4)])
      let leaderIndex = context.activePlayers.firstIndex(of: leader)!
      for (offset, play) in trick.enumerated() {
        let expected = context.activePlayers[(leaderIndex + offset) % 4]
        guard play.player == expected, let hand = remaining[play.player], hand.contains(play.card)
        else {
          return nil
        }
        let legal = legalCards(hand, trick: Array(trick.prefix(offset)))
        guard legal.contains(play.card) else { return nil }
        var handAfterPlay = remaining[play.player]!
        handAfterPlay.remove(at: handAfterPlay.firstIndex(of: play.card)!)
        remaining[play.player] = handAfterPlay
      }
      let winner = trickWinner(trick.map { ($0.player, $0.card) })
      tricks.append(
        DeviceRoundAnalysisTrick(
          trickIndex: index / 4 + 1, leader: leader, winner: winner.player, winningCard: winner.card
        ))
      leader = winner.player
    }
    return tricks
  }

  private static func legalCards(_ hand: [String], trick: [DeviceRoundAnalysisPlay]) -> [String] {
    guard let lead = trick.first?.card else { return hand }
    let category = followingCategory(lead)
    let following = hand.filter { followingCategory($0) == category }
    return following.isEmpty ? hand : following
  }

  private static func followingCategory(_ card: String) -> String {
    let parts = card.split(separator: "_")
    let suit = String(parts[0])
    let rank = String(parts[1])
    return suit == "DIAMONDS" || (suit == "HEARTS" && rank == "TEN") || rank == "QUEEN"
      || rank == "JACK"
      ? "TRUMP" : suit
  }

  private static func cardBeats(_ candidate: String, _ incumbent: String, lead: String) -> Bool {
    let leadCategory = followingCategory(lead)
    let candidateCategory = followingCategory(candidate)
    let incumbentCategory = followingCategory(incumbent)
    let candidateEligible = candidateCategory == "TRUMP" || candidateCategory == leadCategory
    let incumbentEligible = incumbentCategory == "TRUMP" || incumbentCategory == leadCategory
    if candidateEligible != incumbentEligible { return candidateEligible }
    guard candidateEligible else { return false }
    if candidateCategory != incumbentCategory { return candidateCategory == "TRUMP" }
    let order = candidateCategory == "TRUMP" ? trumpHighToLow : plainHighToLow
    return (order.firstIndex(of: candidate) ?? Int.max)
      < (order.firstIndex(of: incumbent) ?? Int.max)
  }

  private static func trickWinner(
    _ trick: [(player: String, card: String)]
  ) -> (player: String, card: String) {
    var winner = trick[0]
    let lead = trick[0].card
    for card in trick.dropFirst() where cardBeats(card.card, winner.card, lead: lead) {
      winner = card
    }
    return winner
  }

  private static func playKey(_ plays: [DeviceRoundAnalysisPlay]) -> String {
    plays.map { "\($0.player):\($0.card):\($0.observedCardID ?? "~")" }.joined(separator: "|")
  }

  private static func isSHA256(_ value: String) -> Bool {
    value.count == 64 && value.allSatisfy { $0.isHexDigit && !$0.isUppercase }
  }
}

/// Durable request and result files for restart inspection of one local analysis.
public struct DeviceRoundAnalysisStore: Sendable {
  public let directoryURL: URL

  public init(directoryURL: URL) { self.directoryURL = directoryURL }

  public func save(request: DeviceRoundAnalysisRequest, result: DeviceRoundAnalysisResult) throws {
    try FileManager.default.createDirectory(at: directoryURL, withIntermediateDirectories: true)
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    try encoder.encode(request).write(
      to: directoryURL.appendingPathComponent("request.json"), options: .atomic)
    try encoder.encode(result).write(
      to: directoryURL.appendingPathComponent("result.json"), options: .atomic)
    let formatter = ISO8601DateFormatter()
    let now = formatter.string(from: Date())
    let log =
      [
        "\(now) info run=\(request.analysisID) stage=round-analysis message=start observations=\(result.diagnostics.observationsSeen)",
        "\(now) \(result.failure == nil ? "info" : "error") run=\(request.analysisID) stage=round-analysis message=finish status=\(result.status.rawValue) hypotheses=\(result.hypotheses.count) search_nodes=\(result.diagnostics.searchNodes) elapsed_ms=\(result.diagnostics.elapsedMs)",
      ].joined(separator: "\n") + "\n"
    try Data(log.utf8).write(to: directoryURL.appendingPathComponent("run.log"), options: .atomic)
  }

  public func saveFailure(analysisID: String, recordingID: String, error: Error) throws {
    try FileManager.default.createDirectory(at: directoryURL, withIntermediateDirectories: true)
    let formatter = ISO8601DateFormatter()
    let timestamp = formatter.string(from: Date())
    let detail = error.localizedDescription.replacingOccurrences(of: "\n", with: " ")
    let record = DeviceRoundAnalysisFailure(
      schemaVersion: "doko-device-round-analysis-failure/v1", analysisID: analysisID,
      recordingID: recordingID, stage: "round-analysis", error: detail, failedAtUTC: timestamp)
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    try encoder.encode(record).write(
      to: directoryURL.appendingPathComponent("failure.json"), options: .atomic)
    let log =
      "\(timestamp) error run=\(analysisID) stage=round-analysis message=failed error=\(detail)\n"
    try Data(log.utf8).write(to: directoryURL.appendingPathComponent("run.log"), options: .atomic)
  }

  public func load() throws -> (DeviceRoundAnalysisRequest, DeviceRoundAnalysisResult)? {
    let requestURL = directoryURL.appendingPathComponent("request.json")
    let resultURL = directoryURL.appendingPathComponent("result.json")
    guard FileManager.default.fileExists(atPath: requestURL.path),
      FileManager.default.fileExists(atPath: resultURL.path)
    else { return nil }
    let request = try JSONDecoder().decode(
      DeviceRoundAnalysisRequest.self, from: Data(contentsOf: requestURL))
    let result = try JSONDecoder().decode(
      DeviceRoundAnalysisResult.self, from: Data(contentsOf: resultURL))
    guard request.analysisID == result.analysisID, request.context.recordingID == result.recordingID
    else {
      throw DeviceRoundAnalysisError.invalidObservations(
        "Saved round-analysis request and result lineage differ.")
    }
    return (request, result)
  }
}

/// Runs analysis from the observation revision retained by M10 and stores a reloadable result.
public struct DeviceRoundAnalysisPipeline: Sendable {
  public init() {}

  @discardableResult
  public func run(
    recordingBundleURL: URL, recordingID: String, sessionID: String,
    search: DeviceRoundAnalysisSearch = DeviceRoundAnalysisSearch()
  ) throws -> DeviceRoundAnalysisResult {
    let analysisID = UUID().uuidString.lowercased()
    let store = DeviceRoundAnalysisStore(
      directoryURL: recordingBundleURL.appendingPathComponent(
        ".device/stages/round-analysis/\(analysisID)", isDirectory: true))
    do {
      let observationsURL =
        recordingBundleURL
        .appendingPathComponent(".device/stages/visual-identities/table-observations.json")
      let observations = try JSONDecoder().decode(
        [DeviceTableObservation].self, from: Data(contentsOf: observationsURL))
      let context = try DeviceRoundAnalysisContext(recordingID: recordingID, sessionID: sessionID)
      let (request, result) = try DeviceRoundReconstructor.run(
        observations: observations, context: context, search: search, analysisID: analysisID)
      try store.save(request: request, result: result)
      return result
    } catch {
      try store.saveFailure(analysisID: analysisID, recordingID: recordingID, error: error)
      throw error
    }
  }
}
