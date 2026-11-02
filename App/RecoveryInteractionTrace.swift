#if DEBUG
import Foundation
import SwiftUI
import UIKit
import OSLog
import ObjectiveC

/// Diagnostic-only metadata. This is not evidence that a touch's associated
/// UIView received a control action, nor a durable replacement for test evidence.
@MainActor
enum RecoveryInteractionTrace {
    struct Snapshot: Equatable {
        struct Selection: Equatable {
            let field: OCRField
            let isSelected: Bool
        }
        let resultID: UUID
        let selections: [Selection]

        init(result: OCRResult) {
            resultID = result.id
            selections = result.suggestions.prefix(OCRField.allCases.count).map {
                Selection(field: $0.field, isSelected: $0.isSelected)
            }
        }
    }

    static func isEnabled(arguments: [String], environment: [String: String]) -> Bool {
        arguments.contains("--ui-testing")
            && environment["RECOVERY_TRACE_OCR"] == "1"
            && environment["UITEST_RUN_ID"].flatMap(UUID.init(uuidString:)) != nil
    }

    private static let logger = Logger(subsystem: "com.alvit.roominventory", category: "RecoveryInteractionTrace")
    private static let live = Recorder(
        arguments: ProcessInfo.processInfo.arguments,
        environment: ProcessInfo.processInfo.environment,
        emit: { logger.notice("\($0, privacy: .public)") },
        install: { installSendEventHook() }
    )

    static func binding(_ original: Binding<Bool>, field: OCRField, resultID: UUID) -> Binding<Bool> {
        live.binding(original, field: field, resultID: resultID)
    }
    static func begin(result: OCRResult) { live.begin(result: result) }
    static func end(resultID: UUID) { live.end(resultID: resultID) }
    static func stateChanged(from: Snapshot, to: Snapshot) { live.stateChanged(from: from, to: to) }

    /// Values only: no UIView, UITouch or UIEvent is retained across dispatch.
    struct ViewSample {
        let className: String
        let frame: CGRect
        let hidden: Bool
        let alpha: Double
        let interactionEnabled: Bool
        let controlEnabled: Bool?
        let switchOn: Bool?
    }
    struct TouchSample {
        let phase: Int
        let timestamp: Double
        let locationInWindow: CGPoint
        let ancestors: [ViewSample]
    }
    struct EventSample {
        let resultID: UUID
        let observedUptime: Double
        let touches: [TouchSample]
        let totalTouchCount: Int
    }

    /// An isolated recorder lets unit tests exercise forwarding and limits
    /// without modifying the application's Objective-C method table.
    @MainActor
    final class Recorder {
        static let maximumRecords = 128
        static let maximumTouchRecords = 96 // Reserve state/lifecycle evidence.
        static let maximumMessageBytes = 8192
        private let enabled: Bool
        private let emit: (String) -> Void
        private let install: () -> Bool
        private var installationAttempted = false
        private var hookInstalled = false
        private(set) var activeResultID: UUID?
        private var recordCount = 0
        private var touchRecordCount = 0
        private var droppedCount = 0
        private var touchLimitRecorded = false

        init(arguments: [String], environment: [String: String],
             emit: @escaping (String) -> Void, install: @escaping () -> Bool) {
            enabled = RecoveryInteractionTrace.isEnabled(arguments: arguments, environment: environment)
            self.emit = emit
            self.install = install
        }

        func begin(result: OCRResult) {
            guard enabled, activeResultID != result.id else { return }
            if !installationAttempted {
                installationAttempted = true
                hookInstalled = install()
            }
            if let prior = activeResultID {
                record("scope_replaced", resultID: prior, fields: [:])
            }
            activeResultID = result.id
            record("begin", resultID: result.id, fields: [
                "touch_hook_installed": hookInstalled,
                "selection": selection(Snapshot(result: result))
            ])
        }

        func end(resultID: UUID) {
            guard enabled, activeResultID == resultID else { return }
            record("end", resultID: resultID, fields: ["dropped_records": droppedCount])
            activeResultID = nil
        }

        func binding(_ original: Binding<Bool>, field: OCRField, resultID: UUID) -> Binding<Bool> {
            guard enabled else { return original }
            return Binding(get: { original.wrappedValue }, set: { newValue, transaction in
                let active = self.activeResultID == resultID
                let oldValue = active ? original.wrappedValue : false
                // Forward first, once, and with the incoming transaction. No
                // diagnostic failure or exhausted log allowance can block it.
                original.transaction(transaction).wrappedValue = newValue
                if active {
                    self.record("binding_set", resultID: resultID, fields: [
                        "field": field.rawValue, "old": oldValue, "new": newValue
                    ])
                }
            })
        }

        func stateChanged(from: Snapshot, to: Snapshot) {
            guard enabled, activeResultID == from.resultID else { return }
            activeResultID = to.resultID
            record("state_observed", resultID: to.resultID, fields: [
                "from_result_id": from.resultID.uuidString,
                "to_result_id": to.resultID.uuidString,
                "old": selection(from), "new": selection(to)
            ])
        }

        /// Close sampling before walking UIKit objects once its evidence budget
        /// is exhausted. The cap is lifetime-wide and never reset by a sheet.
        func touchResultIDForObservation() -> UUID? {
            guard enabled, let resultID = activeResultID else { return nil }
            guard recordCount < Self.maximumRecords - 1,
                  touchRecordCount < Self.maximumTouchRecords else {
                noteTouchLimit(resultID: resultID)
                return nil
            }
            return resultID
        }

        private func noteTouchLimit(resultID: UUID) {
            droppedCount += 1
            if !touchLimitRecorded {
                touchLimitRecorded = true
                record("touch_limit", resultID: resultID, fields: ["diagnostic_incomplete": true])
            }
        }

        /// Call after forwarding; these values describe the association sampled
        /// before dispatch, not a new hit test or proof of an action recipient.
        func eventWasForwarded(_ sample: EventSample) {
            guard enabled else { return }
            guard touchRecordCount < Self.maximumTouchRecords else {
                noteTouchLimit(resultID: sample.resultID)
                return
            }
            touchRecordCount += 1
            record("touch_association", resultID: sample.resultID, fields: [
                "observed_before_dispatch_uptime": finite(sample.observedUptime),
                "original_send_event_returned": true,
                "action_recipient_proven": false,
                "touch_count": sample.totalTouchCount,
                "touches_truncated": sample.totalTouchCount > 4,
                "touches": sample.touches.prefix(4).map(touchFields)
            ])
        }

        private func touchFields(_ touch: TouchSample) -> [String: Any] {
            ["phase": touch.phase, "timestamp": finite(touch.timestamp),
             "location_in_window": [finite(Double(touch.locationInWindow.x)), finite(Double(touch.locationInWindow.y))],
             "ancestor_limit": 8,
             "ancestors": touch.ancestors.prefix(8).map(viewFields)]
        }

        private func viewFields(_ view: ViewSample) -> [String: Any] {
            ["class": String(view.className.prefix(96)),
             "frame_in_superview": [finite(Double(view.frame.origin.x)), finite(Double(view.frame.origin.y)),
                                    finite(Double(view.frame.size.width)), finite(Double(view.frame.size.height))],
             "hidden": view.hidden, "alpha": finite(view.alpha),
             "interaction_enabled": view.interactionEnabled,
             "control_enabled": view.controlEnabled.map { $0 as Any } ?? NSNull(),
             "switch_on": view.switchOn.map { $0 as Any } ?? NSNull()]
        }

        private func selection(_ snapshot: Snapshot) -> [[String: Any]] {
            snapshot.selections.map { ["field": $0.field.rawValue, "selected": $0.isSelected] }
        }

        private func finite(_ value: Double) -> Any { value.isFinite ? value : NSNull() }

        private func record(_ kind: String, resultID: UUID, fields: [String: Any]) {
            guard recordCount < Self.maximumRecords else { droppedCount += 1; return }
            recordCount += 1
            var payload: [String: Any] = [
                "schema": 1, "sequence": recordCount, "kind": kind,
                "result_id": resultID.uuidString,
                "uptime": ProcessInfo.processInfo.systemUptime
            ]
            if recordCount == Self.maximumRecords {
                droppedCount += 1
                payload["kind"] = "record_limit"
                payload["diagnostic_incomplete"] = true
            } else {
                payload.merge(fields) { _, new in new }
            }
            guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]) else { return }
            let output: Data
            if data.count > Self.maximumMessageBytes {
                droppedCount += 1
                payload = ["schema": 1, "sequence": recordCount, "kind": "message_limit",
                           "result_id": resultID.uuidString, "diagnostic_incomplete": true]
                guard let limited = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]) else { return }
                output = limited
            } else { output = data }
            guard let text = String(data: output, encoding: .utf8) else { return }
            emit(text)
        }
    }

    private static var sendEventHookInstalled = false
    private static func installSendEventHook() -> Bool {
        if sendEventHookInstalled { return true }
        guard let original = class_getInstanceMethod(UIApplication.self, #selector(UIApplication.sendEvent(_:))),
              let observer = class_getInstanceMethod(UIApplication.self, #selector(UIApplication.recoveryTrace_sendEvent(_:))),
              let originalType = method_getTypeEncoding(original),
              let observerType = method_getTypeEncoding(observer),
              String(cString: originalType) == String(cString: observerType) else { return false }
        method_exchangeImplementations(original, observer)
        sendEventHookInstalled = true
        return true
    }

    fileprivate static func sample(_ event: UIEvent) -> EventSample? {
        guard event.type == .touches, let resultID = live.touchResultIDForObservation(),
              let allTouches = event.allTouches, !allTouches.isEmpty else { return nil }
        let touches = allTouches.prefix(4).map { touch in
            var ancestors: [ViewSample] = []
            var current = touch.view
            while let view = current, ancestors.count < 8 {
                ancestors.append(ViewSample(className: NSStringFromClass(type(of: view)), frame: view.frame,
                                            hidden: view.isHidden, alpha: Double(view.alpha),
                                            interactionEnabled: view.isUserInteractionEnabled,
                                            controlEnabled: (view as? UIControl)?.isEnabled,
                                            switchOn: (view as? UISwitch)?.isOn))
                current = view.superview
            }
            return TouchSample(phase: touch.phase.rawValue, timestamp: touch.timestamp,
                               locationInWindow: touch.location(in: touch.window), ancestors: ancestors)
        }
        return EventSample(resultID: resultID, observedUptime: ProcessInfo.processInfo.systemUptime,
                           touches: touches, totalTouchCount: allTouches.count)
    }

    fileprivate static func forwarded(_ sample: EventSample?) {
        if let sample { live.eventWasForwarded(sample) }
    }
}

private extension UIApplication {
    @objc dynamic func recoveryTrace_sendEvent(_ event: UIEvent) {
        let sample = RecoveryInteractionTrace.sample(event)
        // After exchange, this selector invokes the original implementation.
        recoveryTrace_sendEvent(event)
        RecoveryInteractionTrace.forwarded(sample)
    }
}
#endif
