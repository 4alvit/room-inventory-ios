import Foundation
import XCTest

/// Wait for a positively identified return state after the one real Files Save.
/// A missing remote Files node is never evidence that the save completed.
@MainActor
final class ExportReturnReadiness {
    enum Kind { case button, text, navigationBar, alert, other }
    struct Element {
        let kind: Kind
        let identifier: String
        let label: String
        let enabled: Bool
        let frame: CGRect
        let parent: Int?
    }
    struct Observation {
        let frame: CGRect
        let elements: [Element]
    }
    enum Target: String { case home, shareClose }
    enum Decision: String { case pending, dashboard, share }
    enum Failure: Error { case expired, invalidObservation }

    private let window: RecoveryOCRReadinessWindow
    private let clock: () -> TimeInterval
    private let started: TimeInterval
    private let homeName: String
    private(set) var closeAttempted = false
    private(set) var observations = 0
    private(set) var lastDecision: Decision?
    private(set) var lastHomeHittable: Bool?
    private(set) var lastCloseHittable: Bool?

    init(homeName: String,
         clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.homeName = homeName
        self.clock = clock
        started = clock()
        window = RecoveryOCRReadinessWindow(clock: clock)
    }

    private static let shareOwnerIDs: Set<String> = [
        "inventory.exportShare", "ActivityListView", "ShareSheet.RemoteContainerView"
    ]

    private static func visible(_ frame: CGRect, in root: CGRect) -> Bool {
        [root.minX, root.minY, root.width, root.height,
         frame.minX, frame.minY, frame.width, frame.height].allSatisfy(\.isFinite)
            && root.width > 0 && root.height > 0 && frame.width > 0 && frame.height > 0
            && root.contains(frame)
    }

    /// Pure classification; live native hit testing is still required below.
    static func decision(_ observation: Observation, homeName: String) throws -> Decision {
        let nodes = observation.elements
        guard !homeName.isEmpty, nodes.count <= 10_000,
              nodes.enumerated().allSatisfy({ index, node in
                  node.parent.map { $0 >= 0 && $0 < index } ?? true
              }) else { throw Failure.invalidObservation }
        func below(_ child: Int, _ ancestor: Int) -> Bool {
            var current = nodes[child].parent
            while let index = current {
                if index == ancestor { return true }
                current = nodes[index].parent
            }
            return false
        }
        let owners = nodes.indices.filter { shareOwnerIDs.contains(nodes[$0].identifier) }
        let headers = nodes.indices.filter {
            nodes[$0].kind == .navigationBar && nodes[$0].identifier == "UIActivityContentView"
        }
        let closes = nodes.indices.filter {
            nodes[$0].kind == .button && nodes[$0].identifier == "header.closeButton"
        }
        // A positively observed Files control or alert always blocks actions.
        // Conversely, its omission from an app-only snapshot proves nothing.
        if nodes.contains(where: { $0.identifier == "DOCPicker.actionButton" || $0.kind == .alert }) {
            return .pending
        }
        if !owners.isEmpty || !headers.isEmpty || !closes.isEmpty {
            guard headers.count == 1, closes.count == 1,
                  let header = headers.first, let close = closes.first,
                  !owners.isEmpty, owners.allSatisfy({ below(header, $0) }),
                  Set(owners.map { nodes[$0].identifier }).count == owners.count,
                  below(close, header),
                  nodes[close].label == "Close", nodes[close].enabled,
                  visible(nodes[header].frame, in: observation.frame),
                  visible(nodes[close].frame, in: nodes[header].frame) else { return .pending }
            return .share
        }
        let exports = nodes.indices.filter {
            nodes[$0].kind == .button && nodes[$0].identifier == "inventory.exportMenu"
        }
        let homes = nodes.indices.filter {
            nodes[$0].kind == .button && nodes[$0].label.hasPrefix(homeName + ", ")
        }
        guard exports.count == 1, homes.count == 1,
              let export = exports.first, let home = homes.first,
              nodes[export].enabled, nodes[home].enabled,
              visible(nodes[export].frame, in: observation.frame),
              visible(nodes[home].frame, in: observation.frame) else { return .pending }
        var insideHome = Array(repeating: false, count: nodes.count)
        var exactHomeLabel = false
        for index in nodes.indices {
            if let parent = nodes[index].parent {
                insideHome[index] = parent == home || insideHome[parent]
            }
            if insideHome[index], nodes[index].kind == .text, nodes[index].label == homeName {
                exactHomeLabel = true
            }
        }
        guard exactHomeLabel else { return .pending }
        return .dashboard
    }

    func poll(observe: () throws -> Observation,
              isHittable: (Target) throws -> Bool,
              close: () throws -> Void) throws -> Bool {
        lastHomeHittable = nil
        lastCloseHittable = nil
        let observation = try window.perform(observe)
        observations += 1
        let decision = try window.perform { try Self.decision(observation, homeName: homeName) }
        lastDecision = decision
        switch decision {
        case .pending:
            return false
        case .share:
            guard !closeAttempted else { return false }
            let hittable = try window.perform { try isHittable(.shareClose) }
            lastCloseHittable = hittable
            guard hittable else { return false }
            try window.perform {
                closeAttempted = true // Consumed before an action that can throw.
                try close()
            }
            return false // Closing a share is not proof of dashboard return.
        case .dashboard:
            // The snapshot identifies both anchors; one live content hit proves
            // the run-bound home is interactable within the same allowance.
            let homeHittable = try window.perform { try isHittable(.home) }
            lastHomeHittable = homeHittable
            guard homeHittable else { return false }
            _ = try window.remaining()
            return true
        }
    }

    func waitForReturn(observe: @escaping () throws -> Observation,
                       isHittable: @escaping (Target) throws -> Bool,
                       close: @escaping () throws -> Void) throws -> Bool {
        var probeError: Error?
        do {
            let result = try window.waitForProbe {
                do { return try self.poll(observe: observe, isHittable: isHittable, close: close) }
                catch { probeError = error; return true }
            }
            if let probeError { throw probeError }
            _ = try window.remaining()
            return result == .completed && lastDecision == .dashboard
                && lastHomeHittable == true
        } catch is RecoveryOCRReadinessWindow.Failure {
            throw Failure.expired
        }
    }

    /// Scalars only; unavailable observations stay null. Never resolves UI again.
    var diagnostic: [String: Any] {
        let elapsed = clock() - started
        return ["schema_version": 2, "phase": "export-return-readiness", "deadline_seconds": 10,
                "native_hit_target": "home",
                "elapsed_seconds": elapsed.isFinite ? elapsed as Any : NSNull(),
                "observations": observations, "last_decision": lastDecision?.rawValue as Any? ?? NSNull(),
                "close_attempted_once": closeAttempted,
                "home_hittable": lastHomeHittable as Any? ?? NSNull(),
                "close_hittable": lastCloseHittable as Any? ?? NSNull()]
    }
}
