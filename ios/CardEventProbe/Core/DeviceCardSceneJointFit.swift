import Foundation

public struct DeviceCardSceneJointFit: Equatable, Sendable {
  public let order: [String]
  public let poses: [String: DeviceProposedCardPose]
  public let score: Double?
  public let baselineScore: Double?
  public let margin: Double?
  public let status: String
  public let elapsedMilliseconds: Double
  public let estimatedPeakBytes: Int
}

/// Bounded mask-scoring search for the overlapping proposals in one frame.
/// The search is deterministic and keeps the detector and calibration inputs immutable.
public enum DeviceCardSceneJointFitter {
  private struct Pose: Equatable {
    var center: DevicePoint2D
    var angle: Double
  }

  private struct BeamEntry {
    var score: Double
    var order: [Int]
    var changed: [Int: Pose]
    var masks: [[UInt64]]
    var variants: [String]
  }

  private struct Grid {
    let width: Int
    let height: Int
    var pixels: [UInt8]

    init(width: Int, height: Int) {
      self.width = width
      self.height = height
      pixels = [UInt8](repeating: 0, count: width * height)
    }

    mutating func fill(_ polygon: [DevicePoint2D]) {
      guard polygon.count >= 3 else { return }
      let points = polygon.map { point($0.x.rounded(), $0.y.rounded()) }
      let minY = max(0, Int(points.map(\.y).min()!))
      let maxY = min(height - 1, Int(points.map(\.y).max()!))
      guard minY <= maxY else { return }
      for y in minY...maxY {
        let scan = Double(y)
        var crossings: [Double] = []
        for i in points.indices {
          let a = points[i]
          let b = points[(i + 1) % points.count]
          if (a.y <= scan && b.y > scan) || (b.y <= scan && a.y > scan) {
            crossings.append(a.x + (scan - a.y) * (b.x - a.x) / (b.y - a.y))
          }
        }
        crossings.sort()
        guard crossings.count >= 2 else { continue }
        for pair in stride(from: 0, to: crossings.count - 1, by: 2) {
          let x0 = max(0, Int(ceil(crossings[pair])))
          let x1 = min(width - 1, Int(floor(crossings[pair + 1])))
          if x0 <= x1 {
            for x in x0...x1 { pixels[y * width + x] = 1 }
          }
        }
      }
    }
  }

  public static func fit(
    frame: DeviceSceneFrameInput, scene: DeviceProposedCardSceneFrame,
    calibration: DeviceRecordingCalibration, savedOrder: [String]? = nil
  ) -> DeviceCardSceneJointFit {
    let start = ProcessInfo.processInfo.systemUptime
    guard scene.status == "supported" || scene.status == "partial" else {
      return result(
        status: "not_applicable", order: [], poses: [:], score: nil,
        baseline: nil, margin: nil, start: start, bytes: 0)
    }
    let candidates = frame.candidates.sorted { $0.candidateID < $1.candidateID }
    let poses = scene.poses.sorted { $0.sourceCandidateID < $1.sourceCandidateID }
    guard !poses.isEmpty else {
      return result(
        status: "complete", order: [], poses: [:], score: nil,
        baseline: nil, margin: nil, start: start, bytes: 0)
    }
    let ids = poses.map(\.cardID)
    let byCandidate = Dictionary(uniqueKeysWithValues: candidates.map { ($0.candidateID, $0) })
    let poseByCard = Dictionary(
      uniqueKeysWithValues: poses.map {
        ($0.cardID, Pose(center: $0.center, angle: $0.rotationDegrees))
      })
    let count = ids.count
    guard count <= 8 else {
      return result(
        status: "skipped_card_limit", order: ids, poses: [:], score: nil,
        baseline: nil, margin: nil, start: start, bytes: 0)
    }
    guard !candidates.isEmpty else {
      return result(
        status: "failed_missing_masks", order: ids, poses: [:], score: nil,
        baseline: nil, margin: nil, start: start, bytes: 0)
    }
    let width = (frame.width + 7) / 8
    let height = (frame.height + 7) / 8
    guard width > 0, height > 0, width * height <= 2_000_000 else {
      return result(
        status: "failed_invalid_dimensions", order: ids, poses: [:], score: nil,
        baseline: nil, margin: nil, start: start, bytes: 0)
    }
    let baseMasks = poses.map { pose in
      sourceMask(byCandidate[pose.sourceCandidateID], width: width, height: height)
    }
    let full = poses.map {
      raster(
        poseByCard[$0.cardID]!, calibration: calibration,
        width: width, height: height, scale: 8)
    }
    let cardIndex = Dictionary(uniqueKeysWithValues: ids.enumerated().map { ($1, $0) })
    var order = (savedOrder ?? ids).compactMap { cardIndex[$0] }
    for i in 0..<count where !order.contains(i) { order.append(i) }
    let baseline = score(source: baseMasks, full: full, order: order)
    var connected: Set<Int> = []
    if count > 1 {
      for i in 0..<count {
        if (0..<count).contains(where: { $0 != i && overlap(full[i], full[$0]) >= 4 }) {
          connected.insert(i)
        }
      }
    }
    var variants: [[(Pose, [UInt64], String)]] = Array(repeating: [], count: count)
    for i in connected.sorted() {
      guard let seed = poseByCard[ids[i]] else { continue }
      for turn in [0.0, 90.0] {
        let angle = seed.angle + turn
        let a = angle * .pi / 180
        let u = scaled(point(cos(a), sin(a)), calibration.cardShortSize)
        let v = scaled(point(-sin(a), cos(a)), calibration.cardLongSize)
        for sx in [-0.5, -0.25, 0.0, 0.25, 0.5] {
          for ly in [-0.5, -0.25, 0.0, 0.25, 0.5] {
            if turn == 0 && sx == 0 && ly == 0 { continue }
            let center = add(add(seed.center, scaled(u, sx)), scaled(v, ly))
            let candidate = Pose(center: center, angle: angle)
            variants[i].append(
              (
                candidate,
                raster(candidate, calibration: calibration, width: width, height: height, scale: 8),
                "\(Int(turn)):\(sx):\(ly)"
              ))
          }
        }
      }
    }
    var beam = [
      BeamEntry(
        score: baseline, order: order, changed: [:], masks: full,
        variants: Array(repeating: "", count: count))
    ]
    for _ in 0..<2 {
      var pool = beam
      for entry in beam {
        for i in connected.subtracting(entry.changed.keys).sorted() {
          for (pose, mask, variant) in variants[i] {
            var trialMasks = entry.masks
            trialMasks[i] = mask
            var trialOrders = [entry.order]
            if count > 1 {
              for j in 0..<(count - 1)
              where overlap(
                trialMasks[entry.order[j]],
                trialMasks[entry.order[j + 1]]) >= 4
              {
                var swapped = entry.order
                swapped.swapAt(j, j + 1)
                trialOrders.append(swapped)
              }
            }
            for trialOrder in trialOrders {
              var changes = entry.changed
              changes[i] = pose
              var descriptors = entry.variants
              descriptors[i] = variant
              pool.append(
                BeamEntry(
                  score: score(
                    source: baseMasks, full: trialMasks,
                    order: trialOrder),
                  order: trialOrder, changed: changes, masks: trialMasks,
                  variants: descriptors))
            }
          }
        }
      }
      pool.sort { $0.score > $1.score }
      var seen: Set<String> = []
      beam = []
      for entry in pool {
        let key = "\(entry.order):\(entry.variants)"
        if seen.insert(key).inserted { beam.append(entry) }
        if beam.count == 3 { break }
      }
    }
    guard let winner = beam.first else {
      return result(
        status: "failed_search", order: ids, poses: [:], score: nil,
        baseline: baseline, margin: nil, start: start, bytes: 0)
    }
    let margin = beam.count > 1 ? winner.score - beam[1].score : nil
    let ambiguous = margin != nil && margin! < 0.005
    let refined = winner.score >= baseline && !ambiguous ? winner.changed : [:]
    let replacements = Dictionary(
      uniqueKeysWithValues: refined.map { index, pose in
        (
          ids[index],
          DeviceProposedCardPose(
            cardID: ids[index],
            sourceCandidateID: poses[index].sourceCandidateID, center: pose.center,
            rotationDegrees: pose.angle.truncatingRemainder(dividingBy: 180),
            fitResidual: poses[index].fitResidual)
        )
      })
    let status = ambiguous ? "complete_ambiguous" : "complete"
    let retainedOrder = winner.score >= baseline && !ambiguous ? winner.order : order
    let maskBytes = ((width * height + 63) / 64) * MemoryLayout<UInt64>.size
    let bytes =
      (baseMasks.count + full.count) * maskBytes
      + variants.reduce(0) {
        $0 + $1.reduce(0) { $0 + $1.1.count * MemoryLayout<UInt64>.size }
      }
    return result(
      status: status, order: retainedOrder.map { ids[$0] }, poses: replacements,
      score: max(baseline, winner.score), baseline: baseline, margin: margin,
      start: start, bytes: bytes)
  }

  private static func result(
    status: String, order: [String], poses: [String: DeviceProposedCardPose],
    score: Double?, baseline: Double?, margin: Double?, start: Double,
    bytes: Int
  ) -> DeviceCardSceneJointFit {
    DeviceCardSceneJointFit(
      order: order, poses: poses, score: score, baselineScore: baseline,
      margin: margin, status: status,
      elapsedMilliseconds: (ProcessInfo.processInfo.systemUptime - start) * 1000,
      estimatedPeakBytes: bytes)
  }

  private static func sourceMask(_ candidate: DeviceSceneCandidate?, width: Int, height: Int)
    -> [UInt64]
  {
    var pixels = [UInt8](repeating: 0, count: width * height)
    for polygon in candidate?.polygons ?? [] where polygon.count >= 3 {
      let points = polygon.map { (x: $0.x.rounded(), y: $0.y.rounded()) }
      for y in 0..<height {
        let py = Double(y * 8 + 4)
        for x in 0..<width {
          let px = Double(x * 8 + 4)
          var inside = false
          for i in points.indices {
            let a = points[i]
            let b = points[(i + 1) % points.count]
            let cross = (px - a.x) * (b.y - a.y) - (py - a.y) * (b.x - a.x)
            if abs(cross) < 1e-8,
              px >= min(a.x, b.x), px <= max(a.x, b.x),
              py >= min(a.y, b.y), py <= max(a.y, b.y)
            {
              inside = true
              break
            }
            if (a.y > py) != (b.y > py),
              px < (b.x - a.x) * (py - a.y) / (b.y - a.y) + a.x
            {
              inside.toggle()
            }
          }
          if inside { pixels[y * width + x] = 1 }
        }
      }
    }
    return bitmask(pixels)
  }

  private static func raster(
    _ pose: Pose, calibration: DeviceRecordingCalibration,
    width: Int, height: Int, scale: Double
  ) -> [UInt64] {
    guard
      let polygon = try? DeviceCardPlaneGeometry.projectFixedCard(
        tableToImage: calibration.tableToImage, center: pose.center,
        rotationDegrees: pose.angle, shortSize: calibration.cardShortSize,
        longSize: calibration.cardLongSize)
    else { return [UInt64](repeating: 0, count: (width * height + 63) / 64) }
    var grid = Grid(width: width, height: height)
    grid.fill(polygon.map { point($0.x / scale, $0.y / scale) })
    return bitmask(grid.pixels)
  }

  private static func point(_ x: Double, _ y: Double) -> DevicePoint2D {
    // Inputs and projected poses are validated as finite by the geometry layer.
    try! DevicePoint2D(x: x, y: y)
  }

  private static func add(_ a: DevicePoint2D, _ b: DevicePoint2D) -> DevicePoint2D {
    point(a.x + b.x, a.y + b.y)
  }

  private static func scaled(_ a: DevicePoint2D, _ value: Double) -> DevicePoint2D {
    point(a.x * value, a.y * value)
  }

  private static func bitmask(_ pixels: [UInt8]) -> [UInt64] {
    var words = [UInt64](repeating: 0, count: (pixels.count + 63) / 64)
    for index in pixels.indices where pixels[index] != 0 {
      words[index >> 6] |= UInt64(1) << (index & 63)
    }
    return words
  }

  private static func overlap(_ a: [UInt64], _ b: [UInt64]) -> Int {
    zip(a, b).reduce(0) { $0 + ($1.0 & $1.1).nonzeroBitCount }
  }

  private static func score(source: [[UInt64]], full: [[UInt64]], order: [Int]) -> Double {
    guard let first = full.first, !order.isEmpty else { return 0 }
    var covered = [UInt64](repeating: 0, count: first.count)
    var total = 0.0
    for index in order {
      var intersection = 0
      var union = 0
      for word in first.indices {
        let visible = full[index][word] & ~covered[word]
        let detected = source[index][word]
        intersection += (visible & detected).nonzeroBitCount
        union += (visible | detected).nonzeroBitCount
        covered[word] |= full[index][word]
      }
      total += Double(intersection) / Double(max(union, 1))
    }
    return total / Double(order.count)
  }
}
