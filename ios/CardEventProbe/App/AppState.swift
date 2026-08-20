import CoreML
import Foundation
import SwiftUI

enum ModelLoadState {
    case loading
    case ready(ModelContract)
    case failed(String)

    var title: String {
        switch self {
        case .loading: return "Loading"
        case .ready: return "Ready"
        case .failed: return "Error"
        }
    }
}

@MainActor
final class AppState: ObservableObject {
    @Published private(set) var modelState: ModelLoadState = .loading
    @Published private(set) var eventCount = 0

    private(set) var modelRunner: CardEventModelRunner?
    let eventPostProcessor = EventPostProcessor()

    var roiStatus: String {
        guard let runner = modelRunner as? CoreMLCardEventModelRunner else {
            return "Unavailable"
        }
        return runner.roi == nil ? "Not configured" : "Configured"
    }

    init() {
        loadModel()
    }

    func loadModel() {
        modelState = .loading
        modelRunner = nil

        do {
            let configuration = MLModelConfiguration()
            configuration.computeUnits = .all
            let runner = try CoreMLCardEventModelRunner(configuration: configuration)
            modelRunner = runner
            modelState = .ready(runner.contract)
#if DEBUG
            print("CardEventNet model contract:\n\(runner.contract.summary)")
#endif
        } catch {
            modelState = .failed(error.localizedDescription)
        }
    }

    func resetEvents() {
        eventPostProcessor.reset()
        eventCount = 0
    }
}
