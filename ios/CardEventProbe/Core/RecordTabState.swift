import Foundation

public enum AppTab: String, CaseIterable, Sendable {
    case live
    case record
    case replay
}

public struct RecordTabState: Equatable, Sendable {
    public private(set) var selectedTab: AppTab
    public private(set) var profile: CollectionProfile

    public init(
        selectedTab: AppTab = .live,
        profile: CollectionProfile = .newDraft()
    ) {
        self.selectedTab = selectedTab
        self.profile = profile
    }

    public var isRecordTabSelected: Bool { selectedTab == .record }
    public var canFinalize: Bool { profile.isComplete }

    public mutating func select(_ tab: AppTab) {
        selectedTab = tab
    }

    public mutating func update(profile: CollectionProfile) {
        self.profile = profile
    }

    public func message(for field: CollectionProfileValidationField) -> String? {
        profile.validationIssues.first { $0.field == field }?.message
    }
}
