import CryptoKit
import Foundation

/// Validates a durable evidence-package bundle, including its exact member set and every digest.
public func validateEvidencePackageBundleDirectory(at directoryURL: URL) throws -> RepositoryEvidencePackageBundle {
    var isDirectory: ObjCBool = false
    guard FileManager.default.fileExists(atPath: directoryURL.path, isDirectory: &isDirectory),
          isDirectory.boolValue else {
        throw repositoryContractError("evidence package bundle directory is missing")
    }
    let manifestData = try Data(contentsOf: directoryURL.appendingPathComponent("manifest.json"))
    let bundle = try decodeRepositoryJSON(RepositoryEvidencePackageBundle.self, data: manifestData)
    let evidenceData = try Data(contentsOf: directoryURL.appendingPathComponent(bundle.files.evidenceManifest.relativePath))
    let recordData = try Data(contentsOf: directoryURL.appendingPathComponent(bundle.files.packageRecord.relativePath))
    let enrollmentData = try Data(contentsOf: directoryURL.appendingPathComponent(bundle.files.taskEnrollment.relativePath))
    let lineageData = try Data(contentsOf: directoryURL.appendingPathComponent(bundle.files.lineage.relativePath))
    let evidence = try decodeRepositoryJSON(EvidencePackageManifest.self, data: evidenceData)
    let record = try decodeRepositoryJSON(RepositoryEvidencePackageRecord.self, data: recordData)
    let enrollments = try decodeRepositoryJSON(RepositoryTaskEnrollmentDocument.self, data: enrollmentData)
    let lineage = try decodeRepositoryJSON(RepositoryEvidencePackageLineage.self, data: lineageData)
    guard evidence.packageID.uuidString.lowercased() == bundle.packageID.lowercased(),
          record.packageID == bundle.packageID, record.sourceAssetID == bundle.sourceAssetID,
          enrollments.sourceAssetID == bundle.sourceAssetID, lineage.packageID == bundle.packageID else {
        throw repositoryContractError("evidence package documents have different identities")
    }

    try verifyRepositoryBytes(evidenceData, descriptor: bundle.files.evidenceManifest)
    try verifyRepositoryBytes(recordData, descriptor: bundle.files.packageRecord)
    try verifyRepositoryBytes(enrollmentData, descriptor: bundle.files.taskEnrollment)
    try verifyRepositoryBytes(lineageData, descriptor: bundle.files.lineage)
    let expectedFrames = Set(evidence.frames.map { "frames/\($0.partName).jpg" })
    guard expectedFrames == Set(bundle.files.frames.map(\.relativePath)) else {
        throw repositoryContractError("evidence package frame descriptors differ from manifest")
    }
    for descriptor in bundle.files.frames {
        try verifyEvidencePackageFile(
            directoryURL.appendingPathComponent(descriptor.relativePath), descriptor: descriptor
        )
    }
    let expectedSnippet: String? = {
        guard let snippet = evidence.videoSnippet, snippet.captureComplete, let partName = snippet.partName else {
            return nil
        }
        return "video/\(partName).mp4"
    }()
    guard expectedSnippet == bundle.files.videoSnippet?.relativePath else {
        throw repositoryContractError("evidence package snippet descriptor differs from manifest")
    }
    if let descriptor = bundle.files.videoSnippet {
        try verifyEvidencePackageFile(
            directoryURL.appendingPathComponent(descriptor.relativePath), descriptor: descriptor
        )
    }
    let expected = Set([
        "manifest.json",
        bundle.files.evidenceManifest.relativePath,
        bundle.files.packageRecord.relativePath,
        bundle.files.taskEnrollment.relativePath,
        bundle.files.lineage.relativePath,
    ] + bundle.files.frames.map(\.relativePath) + (bundle.files.videoSnippet.map { [$0.relativePath] } ?? []))
    guard let enumerator = FileManager.default.enumerator(
        at: directoryURL,
        includingPropertiesForKeys: [.isDirectoryKey, .isRegularFileKey],
        options: [.skipsHiddenFiles]
    ) else {
        throw repositoryContractError("evidence package directory could not be inspected")
    }
    var actual: Set<String> = []
    let rootPath = directoryURL.standardizedFileURL.path
    for case let url as URL in enumerator {
        guard (try? url.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true else {
            continue
        }
        let filePath = url.standardizedFileURL.path
        guard filePath.hasPrefix(rootPath + "/") else {
            throw repositoryContractError("evidence package member is outside its directory")
        }
        actual.insert(String(filePath.dropFirst(rootPath.count + 1)))
    }
    guard actual == expected else {
        throw repositoryContractError("evidence package contains an unexpected or missing file")
    }
    return bundle
}

private func verifyEvidencePackageFile(_ url: URL, descriptor: RepositoryBundleFile) throws {
    try verifyRepositoryBytes(Data(contentsOf: url), descriptor: descriptor)
}

/// Validates a durable recording bundle, including its exact member set and every declared digest.
public func validateRepositoryBundleDirectory(at directoryURL: URL) throws -> RepositoryBundle {
    var isDirectory: ObjCBool = false
    guard FileManager.default.fileExists(atPath: directoryURL.path, isDirectory: &isDirectory),
          isDirectory.boolValue else {
        throw repositoryContractError("repository bundle directory is missing")
    }
    let manifestData = try Data(contentsOf: directoryURL.appendingPathComponent("manifest.json"))
    let bundle: RepositoryBundle
    do {
        bundle = try decodeRepositoryJSON(RepositoryBundle.self, data: manifestData)
    } catch {
        throw repositoryContractError("manifest: \(error.localizedDescription)")
    }
    guard bundle.files.sourceRecord.relativePath == "source-record.json",
          bundle.files.taskEnrollment.relativePath == "initial-task-enrollment.json",
          bundle.files.video.relativePath.hasPrefix("videos/"),
          bundle.files.video.relativePath.hasSuffix(".mov"),
          bundle.files.proposalGeneratorRuns.allSatisfy({
              $0.relativePath.hasPrefix("predictions/") && $0.relativePath.hasSuffix(".json")
          }) else {
        throw repositoryContractError("bundle member paths are invalid")
    }

    let sourceURL = directoryURL.appendingPathComponent(bundle.files.sourceRecord.relativePath)
    let enrollmentURL = directoryURL.appendingPathComponent(bundle.files.taskEnrollment.relativePath)
    let videoURL = directoryURL.appendingPathComponent(bundle.files.video.relativePath)
    let sourceData = try Data(contentsOf: sourceURL)
    let enrollmentData = try Data(contentsOf: enrollmentURL)
    let source: RepositorySourceRecord
    let enrollments: RepositoryTaskEnrollmentDocument
    do {
        source = try decodeRepositoryJSON(RepositorySourceRecord.self, data: sourceData)
    } catch {
        throw repositoryContractError("source record: \(error.localizedDescription)")
    }
    do {
        enrollments = try decodeRepositoryJSON(RepositoryTaskEnrollmentDocument.self, data: enrollmentData)
    } catch {
        throw repositoryContractError("task enrollment: \(error.localizedDescription)")
    }
    var proposalData: [String: Data] = [:]
    for descriptor in bundle.files.proposalGeneratorRuns {
        let data = try Data(contentsOf: directoryURL.appendingPathComponent(descriptor.relativePath))
        try verifyRepositoryBytes(data, descriptor: descriptor)
        let run: RepositoryProposalGeneratorRun
        do {
            run = try decodeRepositoryJSON(RepositoryProposalGeneratorRun.self, data: data)
        } catch {
            throw repositoryContractError("proposal run: \(error.localizedDescription)")
        }
        proposalData[run.proposalGeneratorRunID] = data
    }
    let proposalRuns = try proposalData.values.map {
        try decodeRepositoryJSON(RepositoryProposalGeneratorRun.self, data: $0)
    }
    try RepositoryIntakeContract.validate(
        bundle: bundle,
        source: source,
        enrollments: enrollments,
        proposalRuns: proposalRuns
    )
    try verifyRepositoryBytes(manifestData, descriptor: RepositoryBundleFile(
        relativePath: "manifest.json",
        type: "application/json",
        byteLength: manifestData.count,
        sha256: manifestData.sha256Hex
    ))
    try verifyRepositoryFile(videoURL, descriptor: bundle.files.video)
    try verifyRepositoryBytes(sourceData, descriptor: bundle.files.sourceRecord)
    try verifyRepositoryBytes(enrollmentData, descriptor: bundle.files.taskEnrollment)

    let expected = Set([
        "manifest.json",
        bundle.files.video.relativePath,
        bundle.files.sourceRecord.relativePath,
        bundle.files.taskEnrollment.relativePath,
    ] + bundle.files.proposalGeneratorRuns.map(\.relativePath))
    guard let enumerator = FileManager.default.enumerator(
        at: directoryURL,
        includingPropertiesForKeys: [.isDirectoryKey, .isRegularFileKey],
        options: [.skipsHiddenFiles]
    ) else {
        throw repositoryContractError("bundle directory could not be inspected")
    }
    var actual: Set<String> = []
    let rootPath = directoryURL.standardizedFileURL.path
    for case let url as URL in enumerator {
        guard (try? url.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true else {
            continue
        }
        let filePath = url.standardizedFileURL.path
        guard filePath.hasPrefix(rootPath + "/") else {
            throw repositoryContractError("bundle member is outside its directory")
        }
        actual.insert(String(filePath.dropFirst(rootPath.count + 1)))
    }
    guard actual == expected else {
        throw repositoryContractError("bundle contains an unexpected or missing file")
    }
    return bundle
}

private func verifyRepositoryFile(_ url: URL, descriptor: RepositoryBundleFile) throws {
    let values = try url.resourceValues(forKeys: [.fileSizeKey])
    guard let byteLength = values.fileSize, byteLength == descriptor.byteLength else {
        throw repositoryContractError("bundle file bytes do not match their descriptor")
    }
    let handle = try FileHandle(forReadingFrom: url)
    defer { try? handle.close() }
    var hasher = SHA256()
    while let chunk = try handle.read(upToCount: 1024 * 1024), !chunk.isEmpty {
        hasher.update(data: chunk)
    }
    let digest = hasher.finalize().map { String(format: "%02x", $0) }.joined()
    guard digest == descriptor.sha256 else {
        throw repositoryContractError("bundle file bytes do not match their descriptor")
    }
}

public enum RepositoryIntakeContract {
    public static func validate(
        bundle: RepositoryBundle,
        source: RepositorySourceRecord,
        enrollments: RepositoryTaskEnrollmentDocument,
        proposalRuns: [RepositoryProposalGeneratorRun]
    ) throws {
        guard bundle.sourceAssetID == source.sourceAssetID, bundle.sourceSHA256 == source.sha256,
              bundle.recordingID == source.recordingID, bundle.videoID == source.videoID,
              bundle.sessionID == source.sessionID, source.mediaType == "video/quicktime",
              source.byteLength == bundle.files.video.byteLength,
              source.originalFilename == bundle.files.video.relativePath.split(separator: "/").last.map(String.init),
              source.tableSetup != nil,
              source.contentType != "real_game" || source.gameID != nil,
              enrollments.sourceAssetID == bundle.sourceAssetID else {
            throw repositoryContractError("repository bundle documents have different identities")
        }
        let expected = Set(bundle.files.proposalGeneratorRuns.map(\.proposalGeneratorRunID))
        guard expected == Set(proposalRuns.map(\.proposalGeneratorRunID)) else {
            throw repositoryContractError("bundle proposal files do not match proposal runs")
        }
        for run in proposalRuns {
            guard run.sourceAssetID == bundle.sourceAssetID, run.recordingID == bundle.recordingID,
                  run.videoID == bundle.videoID, run.sourceSHA256 == bundle.sourceSHA256 else {
                throw repositoryContractError("proposal run lineage does not match source bundle")
            }
        }
    }

    static func isIdentifier(_ value: String) -> Bool {
        guard let first = value.unicodeScalars.first, isASCIIAlphaNumeric(first) else { return false }
        return value.unicodeScalars.dropFirst().allSatisfy { scalar in
            isASCIIAlphaNumeric(scalar) || [0x2E, 0x3A, 0x5F, 0x2D].contains(scalar.value)
        }
    }

    static func isFilename(_ value: String) -> Bool {
        guard let first = value.unicodeScalars.first, isASCIIAlphaNumeric(first) else { return false }
        return value.unicodeScalars.dropFirst().allSatisfy { scalar in
            isASCIIAlphaNumeric(scalar) || [0x2E, 0x5F, 0x2D].contains(scalar.value)
        }
    }

    static func isSHA256(_ value: String) -> Bool {
        value.count == 64 && value.unicodeScalars.allSatisfy { scalar in
            (0x30...0x39).contains(scalar.value) || (0x61...0x66).contains(scalar.value)
        }
    }

    static func isUTCTimestamp(_ value: String) -> Bool {
        guard value.hasSuffix("Z") else { return false }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: value) != nil || {
            formatter.formatOptions = [.withInternetDateTime]
            return formatter.date(from: value) != nil
        }()
    }

    private static func isASCIIAlphaNumeric(_ scalar: Unicode.Scalar) -> Bool {
        (0x30...0x39).contains(scalar.value) || (0x41...0x5A).contains(scalar.value)
            || (0x61...0x7A).contains(scalar.value)
    }
}

public enum RepositoryIntakeContractError: LocalizedError, Equatable {
    case invalid(String)

    public var errorDescription: String? {
        switch self {
        case let .invalid(message): return "Invalid repository intake: \(message)."
        }
    }
}

func repositoryContractError(_ message: String) -> RepositoryIntakeContractError {
    .invalid(message)
}

private struct RepositoryAnyCodingKey: CodingKey {
    let stringValue: String
    let intValue: Int? = nil

    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { return nil }
}

func repositoryRequireExactKeys<Key: CodingKey & CaseIterable>(
    _ decoder: Decoder,
    _ keyType: Key.Type
) throws {
    let container = try decoder.container(keyedBy: RepositoryAnyCodingKey.self)
    let expected = Set(keyType.allCases.map(\.stringValue))
    let actual = Set(container.allKeys.map(\.stringValue))
    guard actual == expected else { throw repositoryContractError("unexpected or missing fields") }
}

public func decodeRepositoryJSON<T: Decodable>(_ type: T.Type, data: Data) throws -> T {
    try JSONDecoder().decode(type, from: data)
}

public func encodeRepositoryJSON<T: Encodable>(_ value: T) throws -> Data {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    return try encoder.encode(value)
}

public func verifyRepositoryBytes(_ data: Data, descriptor: RepositoryBundleFile) throws {
    guard data.count == descriptor.byteLength,
          data.sha256Hex == descriptor.sha256 else {
        throw repositoryContractError("bundle file bytes do not match their descriptor")
    }
}

public func verifyRepositoryBytes(_ data: Data, descriptor: RepositoryProposalFile) throws {
    guard data.count == descriptor.byteLength,
          data.sha256Hex == descriptor.sha256 else {
        throw repositoryContractError("bundle file bytes do not match their descriptor")
    }
}

private extension Data {
    var sha256Hex: String {
        SHA256.hash(data: self).map { String(format: "%02x", $0) }.joined()
    }
}
