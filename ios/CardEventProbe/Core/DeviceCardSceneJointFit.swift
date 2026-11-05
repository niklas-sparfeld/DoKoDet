import Foundation

public struct DeviceCardSceneJointFit: Equatable, Sendable {
  public let order: [String]
  public let poses: [String: DeviceProposedCardPose]
  public let score: Double?
  public let beamScoreBeforeEdgeRefinement: Double?
  public let baselineScore: Double?
  public let margin: Double?
  public let marginStage: String?
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

  private struct EdgeContext {
    let x: Int
    let y: Int
    let width: Int
    let height: Int
    let source: [UInt8]
    let grownOccluder: [UInt8]
    let distanceToSource: [Float]
    let sourceCount: Int
    let sourceMask: [UInt64]
    let occluderMask: [UInt64]
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

  private static let distanceOffsets: [(Int, Int, Float)] = [
    (-1, 0, 0.955), (1, 0, 0.955), (0, -1, 0.955), (0, 1, 0.955),
    (-1, -1, 1.3693), (1, -1, 1.3693), (-1, 1, 1.3693), (1, 1, 1.3693),
    (-2, -1, 2.3243), (2, -1, 2.3243), (-2, 1, 2.3243), (2, 1, 2.3243),
    (-1, -2, 2.3243), (1, -2, 2.3243), (-1, 2, 2.3243), (1, 2, 2.3243),
  ]

  public static func fit(
    frame: DeviceSceneFrameInput, scene: DeviceProposedCardSceneFrame,
    calibration: DeviceRecordingCalibration, savedOrder: [String]? = nil,
    movableCardIDs: Set<String>? = nil
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
    if let movableCardIDs {
      connected = connected.filter { movableCardIDs.contains(ids[$0]) }
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
            if count > 1 && movableCardIDs == nil {
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
      pool = pool.enumerated().sorted { left, right in
        if left.element.score != right.element.score {
          return left.element.score > right.element.score
        }
        return left.offset < right.offset
      }.map(\.element)
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
    var refined = winner.score >= baseline && !ambiguous ? winner.changed : [:]
    var refinedOrder = winner.score >= baseline && !ambiguous ? winner.order : order
    var edgeWorkingBytes = 0
    if !ambiguous && !refined.isEmpty {
      let quarterWidth = (frame.width + 3) / 4
      let quarterHeight = (frame.height + 3) / 4
      if quarterWidth * quarterHeight <= 8_000_000 {
        var posesForRefinement = poses.map {
          Pose(center: $0.center, angle: $0.rotationDegrees)
        }
        for (index, pose) in refined { posesForRefinement[index] = pose }
        var quarterFull = posesForRefinement.map {
          raster(
            $0, calibration: calibration, width: quarterWidth,
            height: quarterHeight, scale: 4)
        }
        for index in refinedOrder {
          guard let seed = refined[index] else { continue }
          var occluder = [UInt64](repeating: 0, count: quarterFull[index].count)
          for front in refinedOrder {
            if front == index { break }
            for word in occluder.indices { occluder[word] |= quarterFull[front][word] }
          }
          guard overlap(occluder, occluder) > 0 else { continue }
          let source = sourceMask(
            byCandidate[poses[index].sourceCandidateID], width: quarterWidth,
            height: quarterHeight, scale: 4)
          guard
            let context = edgeContext(
              source: source, occluder: occluder,
              width: quarterWidth, height: quarterHeight)
          else { continue }
          let quarterMaskBytes = quarterFull[index].count * MemoryLayout<UInt64>.size
          edgeWorkingBytes = max(
            edgeWorkingBytes,
            (quarterFull.count + 2) * quarterMaskBytes
              + context.width * context.height * 24)
          let angle = seed.angle * .pi / 180
          let short = scaled(point(cos(angle), sin(angle)), calibration.cardShortSize)
          let long = scaled(point(-sin(angle), cos(angle)), calibration.cardLongSize)
          var best: (score: Double, pose: Pose, mask: [UInt64])?
          for angleDelta in -2...9 {
            for step in 0...16 {
              let sx = -0.2 + Double(step) * 0.025
              for longStep in 0...16 {
                let ly = -0.2 + Double(longStep) * 0.025
                let pose = Pose(
                  center: add(add(seed.center, scaled(short, sx)), scaled(long, ly)),
                  angle: seed.angle + Double(angleDelta))
                let mask = raster(
                  pose, calibration: calibration, width: quarterWidth,
                  height: quarterHeight, scale: 4)
                guard
                  let metrics = edgeScore(
                    predicted: mask, context: context, frameWidth: quarterWidth)
                else { continue }
                let value = (metrics.edge + metrics.overlap) / 2
                if best == nil || value > best!.score {
                  best = (value, pose, mask)
                }
              }
            }
          }
          if let best {
            refined[index] = best.pose
            posesForRefinement[index] = best.pose
            quarterFull[index] = best.mask
          }
        }
      }
    }
    var finalMasks = full
    for (index, pose) in refined {
      finalMasks[index] = raster(
        pose, calibration: calibration, width: width, height: height, scale: 8)
    }
    let finalScore = score(source: baseMasks, full: finalMasks, order: refinedOrder)
    if finalScore < baseline {
      refined = [:]
      refinedOrder = order
    }
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
    let maskBytes = ((width * height + 63) / 64) * MemoryLayout<UInt64>.size
    let bytes =
      (baseMasks.count + full.count) * maskBytes
      + variants.reduce(0) {
        $0 + $1.reduce(0) { $0 + $1.1.count * MemoryLayout<UInt64>.size }
      }
      + edgeWorkingBytes
    return result(
      status: status, order: refinedOrder.map { ids[$0] }, poses: replacements,
      score: max(baseline, finalScore), baseline: baseline, margin: margin,
      start: start, bytes: bytes, beamScore: winner.score,
      marginStage: "beam_before_edge_refinement")
  }

  private static func result(
    status: String, order: [String], poses: [String: DeviceProposedCardPose],
    score: Double?, baseline: Double?, margin: Double?, start: Double,
    bytes: Int, beamScore: Double? = nil, marginStage: String? = nil
  ) -> DeviceCardSceneJointFit {
    DeviceCardSceneJointFit(
      order: order, poses: poses, score: score,
      beamScoreBeforeEdgeRefinement: beamScore, baselineScore: baseline,
      margin: margin, marginStage: marginStage, status: status,
      elapsedMilliseconds: (ProcessInfo.processInfo.systemUptime - start) * 1000,
      estimatedPeakBytes: bytes)
  }

  private static func sourceMask(
    _ candidate: DeviceSceneCandidate?, width: Int, height: Int, scale: Int = 8
  )
    -> [UInt64]
  {
    var pixels = [UInt8](repeating: 0, count: width * height)
    for polygon in candidate?.polygons ?? [] where polygon.count >= 3 {
      let points = polygon.map { (x: $0.x.rounded(), y: $0.y.rounded()) }
      for y in 0..<height {
        let py = Double(y * scale + scale / 2)
        for x in 0..<width {
          let px = Double(x * scale + scale / 2)
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

  private static func edgeContext(
    source: [UInt64], occluder: [UInt64], width: Int, height: Int
  ) -> EdgeContext? {
    guard let sourceBounds = bounds(source, width: width, height: height) else { return nil }
    let x0 = max(0, sourceBounds.minX - 28)
    let y0 = max(0, sourceBounds.minY - 28)
    let x1 = min(width, sourceBounds.maxX + 28)
    let y1 = min(height, sourceBounds.maxY + 28)
    let localWidth = x1 - x0
    let localHeight = y1 - y0
    guard localWidth > 0, localHeight > 0 else { return nil }
    var sourcePixels = crop(source, width: width, x: x0, y: y0, w: localWidth, h: localHeight)
    let occluderPixels = crop(
      occluder, width: width, x: x0, y: y0, w: localWidth, h: localHeight)
    let localCount = localWidth * localHeight
    var horizontal = [UInt8](repeating: 0, count: localCount)
    for y in 0..<localHeight {
      var prefix = [Int](repeating: 0, count: localWidth + 1)
      for x in 0..<localWidth {
        prefix[x + 1] = prefix[x] + Int(occluderPixels[y * localWidth + x])
      }
      for x in 0..<localWidth {
        let left = max(0, x - 8)
        let right = min(localWidth, x + 9)
        if prefix[right] > prefix[left] { horizontal[y * localWidth + x] = 1 }
      }
    }
    var grown = [UInt8](repeating: 0, count: localCount)
    for x in 0..<localWidth {
      var prefix = [Int](repeating: 0, count: localHeight + 1)
      for y in 0..<localHeight {
        prefix[y + 1] = prefix[y] + Int(horizontal[y * localWidth + x])
      }
      for y in 0..<localHeight {
        let top = max(0, y - 8)
        let bottom = min(localHeight, y + 9)
        if prefix[bottom] > prefix[top] { grown[y * localWidth + x] = 1 }
      }
    }
    sourcePixels = edgePixels(sourcePixels, width: localWidth, height: localHeight)
    for index in grown.indices where grown[index] != 0 {
      sourcePixels[index] = 0
    }
    let sourceCount = sourcePixels.reduce(0) { $0 + Int($1) }
    let distanceToSource = distanceTransform(sourcePixels, width: localWidth, height: localHeight)
    return EdgeContext(
      x: x0, y: y0, width: localWidth, height: localHeight,
      source: sourcePixels, grownOccluder: grown,
      distanceToSource: distanceToSource, sourceCount: sourceCount,
      sourceMask: source, occluderMask: occluder)
  }

  private static func edgeScore(
    predicted: [UInt64], context: EdgeContext, frameWidth: Int
  ) -> (edge: Double, overlap: Double)? {
    var predictedPixels = crop(
      predicted, width: frameWidth, x: context.x, y: context.y,
      w: context.width, h: context.height)
    predictedPixels = edgePixels(predictedPixels, width: context.width, height: context.height)
    for index in context.grownOccluder.indices where context.grownOccluder[index] != 0 {
      predictedPixels[index] = 0
    }
    let predictedCount = predictedPixels.reduce(0) { $0 + Int($1) }
    guard context.sourceCount >= 8, predictedCount >= 8 else { return nil }
    let distanceToPredicted = distanceTransform(
      predictedPixels, width: context.width, height: context.height)
    var sourceDistance = 0.0
    var predictedDistance = 0.0
    for index in context.source.indices where context.source[index] != 0 {
      sourceDistance += Double(min(distanceToPredicted[index], 12))
    }
    for index in predictedPixels.indices where predictedPixels[index] != 0 {
      predictedDistance += Double(min(context.distanceToSource[index], 12))
    }
    let edge =
      1
      - (sourceDistance / Double(context.sourceCount) + predictedDistance / Double(predictedCount))
      / 24
    var intersection = 0
    var union = 0
    for index in predicted.indices {
      let visible = predicted[index] & ~context.occluderMask[index]
      intersection += (visible & context.sourceMask[index]).nonzeroBitCount
      union += (visible | context.sourceMask[index]).nonzeroBitCount
    }
    return (edge, Double(intersection) / Double(max(union, 1)))
  }

  private static func bounds(_ words: [UInt64], width: Int, height: Int)
    -> (minX: Int, minY: Int, maxX: Int, maxY: Int)?
  {
    var minX = width
    var minY = height
    var maxX = -1
    var maxY = -1
    for wordIndex in words.indices {
      var word = words[wordIndex]
      while word != 0 {
        let bit = word.trailingZeroBitCount
        let index = wordIndex * 64 + bit
        if index < width * height {
          let x = index % width
          let y = index / width
          minX = min(minX, x)
          maxX = max(maxX, x)
          minY = min(minY, y)
          maxY = max(maxY, y)
        }
        word &= word - 1
      }
    }
    return maxX >= 0 ? (minX, minY, maxX + 1, maxY + 1) : nil
  }

  private static func crop(
    _ words: [UInt64], width: Int, x: Int, y: Int, w: Int, h: Int
  ) -> [UInt8] {
    var result = [UInt8](repeating: 0, count: w * h)
    for row in 0..<h {
      for column in 0..<w {
        let index = (y + row) * width + x + column
        if words[index >> 6] & (UInt64(1) << (index & 63)) != 0 {
          result[row * w + column] = 1
        }
      }
    }
    return result
  }

  private static func edgePixels(_ pixels: [UInt8], width: Int, height: Int) -> [UInt8] {
    var edge = [UInt8](repeating: 0, count: pixels.count)
    guard width >= 3, height >= 3 else { return edge }
    for y in 1..<(height - 1) {
      for x in 1..<(width - 1) {
        let index = y * width + x
        guard pixels[index] != 0 else { continue }
        var interior = true
        for dy in -1...1 where interior {
          for dx in -1...1 where pixels[(y + dy) * width + x + dx] == 0 {
            interior = false
            break
          }
        }
        if !interior { edge[index] = 1 }
      }
    }
    return edge
  }

  private static func distanceTransform(
    _ edge: [UInt8], width: Int, height: Int
  ) -> [Float] {
    let infinity: Float = 12
    var distance = edge.map { $0 == 0 ? infinity : 0 }
    let forward = distanceOffsets.filter { $0.1 < 0 || ($0.1 == 0 && $0.0 < 0) }
    let backward = distanceOffsets.filter { $0.1 > 0 || ($0.1 == 0 && $0.0 > 0) }
    for y in 0..<height {
      for x in 0..<width {
        let index = y * width + x
        for (dx, dy, weight) in forward where x + dx >= 0 && y + dy >= 0 {
          let neighbor = (y + dy) * width + x + dx
          distance[index] = min(distance[index], distance[neighbor] + weight)
        }
      }
    }
    for y in (0..<height).reversed() {
      for x in (0..<width).reversed() {
        let index = y * width + x
        for (dx, dy, weight) in backward where x + dx < width && y + dy < height {
          let neighbor = (y + dy) * width + x + dx
          distance[index] = min(distance[index], distance[neighbor] + weight)
        }
      }
    }
    return distance
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
