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
    enum Target: Equatable { case home(identifier: String), shareClose }
    enum Decision: String { case pending, dashboard, share }
    enum Failure: Error { case expired, invalidObservation }
    private enum Reason: String {
        case filesControl, alert, shareIdentity, shareCloseNotReady
        case dashboardIdentity, dashboardNotReady, homeLabel, dashboard, share
        case homeNotHittable, closeNotHittable, closeAlreadyAttempted, awaitingReturnAfterClose
    }
    private struct Classification {
        let decision: Decision
        let reason: Reason
        let counts: [String: Int]
        let homeIdentifier: String?
    }
    private enum Stage: String { case snapshot, classification, homeHit, closeHit, close, finalCheck, waitReturn }

    private let window: RecoveryOCRReadinessWindow
    private let clock: () -> TimeInterval
    private let started: TimeInterval
    private let diagnosticClock: () -> TimeInterval
    private let diagnosticStarted: TimeInterval
    private let homeName: String
    private var records: [[String: Any]] = []
    private var omittedRecords = 0
    private var countersSaturated = false
    private var lastReason: Reason?
    private var lastCounts: [String: Int]?
    private var errorStage: Stage?
    private(set) var closeAttempted = false
    private(set) var observations = 0
    private(set) var lastDecision: Decision?
    private(set) var lastHomeHittable: Bool?
    private(set) var lastCloseHittable: Bool?

    init(homeName: String,
         clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
         diagnosticClock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.homeName = homeName
        self.clock = clock
        started = clock()
        self.diagnosticClock = diagnosticClock
        diagnosticStarted = diagnosticClock()
        // External Files/share transitions have their own finite allowance.
        // OCR callers retain the shared primitive's ten-second default.
        window = RecoveryOCRReadinessWindow(timeout: 30, clock: clock)
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
        try classify(observation, homeName: homeName).decision
    }

    private static func classify(_ observation: Observation, homeName: String) throws -> Classification {
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
        let exports = nodes.indices.filter {
            nodes[$0].kind == .button && nodes[$0].identifier == "inventory.exportMenu"
        }
        let homes = nodes.indices.filter {
            nodes[$0].kind == .button && nodes[$0].label.hasPrefix(homeName + ", ")
        }
        let files = nodes.filter { $0.identifier == "DOCPicker.actionButton" }.count
        let alerts = nodes.filter { $0.kind == .alert }.count
        let counts = ["nodes": nodes.count, "owners": owners.count, "headers": headers.count,
                      "closes": closes.count, "exports": exports.count, "homes": homes.count,
                      "files": files, "alerts": alerts]
        func result(_ decision: Decision, _ reason: Reason, homeIdentifier: String? = nil) -> Classification {
            Classification(decision: decision, reason: reason, counts: counts, homeIdentifier: homeIdentifier)
        }
        // A positively observed Files control or alert always blocks actions.
        // Conversely, its omission from an app-only snapshot proves nothing.
        if files > 0 { return result(.pending, .filesControl) }
        if alerts > 0 { return result(.pending, .alert) }
        if !owners.isEmpty || !headers.isEmpty || !closes.isEmpty {
            guard headers.count == 1, closes.count == 1,
                  let header = headers.first, let close = closes.first,
                  !owners.isEmpty, owners.allSatisfy({ below(header, $0) }),
                  Set(owners.map { nodes[$0].identifier }).count == owners.count,
                  below(close, header) else { return result(.pending, .shareIdentity) }
            guard nodes[close].label == "Close", nodes[close].enabled,
                  visible(nodes[header].frame, in: observation.frame),
                  visible(nodes[close].frame, in: nodes[header].frame) else {
                return result(.pending, .shareCloseNotReady)
            }
            return result(.share, .share)
        }
        guard exports.count == 1, homes.count == 1,
              let export = exports.first, let home = homes.first else {
            return result(.pending, .dashboardIdentity)
        }
        // Bind the later native query to this exact model-backed row. Only
        // buttons participate: SwiftUI can propagate the ID to child text.
        let identifier = nodes[home].identifier
        let prefix = "inventory.home."
        guard identifier.hasPrefix(prefix),
              let uuid = UUID(uuidString: String(identifier.dropFirst(prefix.count))),
              identifier == prefix + uuid.uuidString,
              nodes.filter({ $0.kind == .button && $0.identifier == identifier }).count == 1 else {
            return result(.pending, .dashboardIdentity)
        }
        guard nodes[export].enabled, nodes[home].enabled,
              visible(nodes[export].frame, in: observation.frame),
              visible(nodes[home].frame, in: observation.frame) else {
            return result(.pending, .dashboardNotReady)
        }
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
        guard exactHomeLabel else { return result(.pending, .homeLabel) }
        return result(.dashboard, .dashboard, homeIdentifier: identifier)
    }

    func poll(observe: () throws -> Observation,
              isHittable: (Target) throws -> Bool,
              close: () throws -> Void) throws -> Bool {
        lastHomeHittable = nil
        lastCloseHittable = nil
        let began = diagnosticClock()
        var stage = Stage.snapshot
        var durations: [String: Any] = [:]
        var record: [String: Any] = ["result": "pending"]
        func measured<Value>(_ next: Stage, _ operation: () throws -> Value) rethrows -> Value {
            stage = next
            let start = diagnosticClock()
            defer { durations[next.rawValue] = Self.duration(from: start, to: diagnosticClock()) }
            return try operation()
        }
        defer {
            record["started_seconds"] = Self.duration(from: diagnosticStarted, to: began)
            record["elapsed_seconds"] = Self.duration(from: began, to: diagnosticClock())
            record["stage_seconds"] = durations
            record["last_stage"] = stage.rawValue
            if records.count < 32 { records.append(record) }
            else if omittedRecords < 10_000 { omittedRecords += 1 }
            else { countersSaturated = true }
        }
        do {
            let observation = try measured(.snapshot) { try window.perform(observe) }
            if observations < 10_000 { observations += 1 } else { countersSaturated = true }
            let classification = try measured(.classification) {
                try window.perform { try Self.classify(observation, homeName: homeName) }
            }
            lastDecision = classification.decision
            lastReason = classification.reason
            lastCounts = classification.counts
            record["decision"] = classification.decision.rawValue
            record["counts"] = classification.counts
            defer { record["reason"] = lastReason?.rawValue }
            switch classification.decision {
            case .pending:
                return false
            case .share:
                guard !closeAttempted else { lastReason = .closeAlreadyAttempted; return false }
                let hittable = try measured(.closeHit) { try window.perform { try isHittable(.shareClose) } }
                lastCloseHittable = hittable
                guard hittable else { lastReason = .closeNotHittable; return false }
                try measured(.close) {
                    try window.perform {
                        closeAttempted = true // Consumed before an action that can throw.
                        try close()
                    }
                }
                lastReason = .awaitingReturnAfterClose
                return false // Closing a share is not proof of dashboard return.
            case .dashboard:
                // The snapshot identifies both anchors; one live content hit proves
                // the run-bound home is interactable within the same allowance.
                guard let identifier = classification.homeIdentifier else { throw Failure.invalidObservation }
                let homeHittable = try measured(.homeHit) {
                    try window.perform { try isHittable(.home(identifier: identifier)) }
                }
                lastHomeHittable = homeHittable
                guard homeHittable else { lastReason = .homeNotHittable; return false }
                _ = try measured(.finalCheck) { try window.remaining() }
                record["result"] = "ready"
                return true
            }
        } catch {
            errorStage = stage
            record["result"] = "failed"
            throw error // Diagnostics never replace the original native error.
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
            if errorStage == nil { errorStage = .waitReturn }
            throw Failure.expired
        }
    }

    private static func duration(from start: TimeInterval, to end: TimeInterval) -> Any {
        let seconds = end - start
        return start.isFinite && end.isFinite && seconds.isFinite && seconds >= 0
            ? seconds as Any : NSNull()
    }

    /// Fixed categories and at most 32 records. No labels, paths or error text.
    /// Timing uses a separate read-only clock, never the injected deadline clock.
    /// Unavailable observations stay null. Never resolves UI again.
    var diagnostic: [String: Any] {
        let elapsed = clock() - started
        return ["schema_version": 3, "phase": "export-return-readiness", "deadline_seconds": 30,
                "native_hit_target": "home",
                "elapsed_seconds": elapsed.isFinite ? elapsed as Any : NSNull(),
                "observations": observations, "last_decision": lastDecision?.rawValue as Any? ?? NSNull(),
                "last_reason": lastReason?.rawValue as Any? ?? NSNull(),
                "last_counts": lastCounts as Any? ?? NSNull(),
                "error_stage": errorStage?.rawValue as Any? ?? NSNull(),
                "timing_clock": "process_uptime", "records": records,
                "omitted_records": omittedRecords, "counters_saturated": countersSaturated,
                "close_attempted_once": closeAttempted,
                "home_hittable": lastHomeHittable as Any? ?? NSNull(),
                "close_hittable": lastCloseHittable as Any? ?? NSNull()]
    }
}
