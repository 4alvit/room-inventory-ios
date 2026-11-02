#if DEBUG
import XCTest
import SwiftUI
@testable import RoomInventory

@MainActor
final class RecoveryInteractionTraceTests: XCTestCase {
    private let arguments = ["app", "--ui-testing"]
    private var environment: [String: String] {
        ["UITEST_RUN_ID": "45E4CD18-0E93-4F48-8C0C-87E80C3E4505", "RECOVERY_TRACE_OCR": "1"]
    }
    private func result() -> OCRResult {
        OCRResult(text: "PRIVATE OCR TEXT", suggestions: [OCRSuggestion(field: .model, value: "PRIVATE VALUE")])
    }
    private func decode(_ records: [String]) throws -> [[String: Any]] {
        try records.map { try XCTUnwrap(JSONSerialization.jsonObject(with: Data($0.utf8)) as? [String: Any]) }
    }

    func testGateRequiresAllThreeExplicitConditions() {
        XCTAssertTrue(RecoveryInteractionTrace.isEnabled(arguments: arguments, environment: environment))
        XCTAssertFalse(RecoveryInteractionTrace.isEnabled(arguments: [], environment: environment))
        for key in ["UITEST_RUN_ID", "RECOVERY_TRACE_OCR"] {
            var invalid = environment; invalid.removeValue(forKey: key)
            XCTAssertFalse(RecoveryInteractionTrace.isEnabled(arguments: arguments, environment: invalid))
        }
        var invalid = environment; invalid["UITEST_RUN_ID"] = "../other-inventory"
        XCTAssertFalse(RecoveryInteractionTrace.isEnabled(arguments: arguments, environment: invalid))
        invalid = environment; invalid["RECOVERY_TRACE_OCR"] = "true"
        XCTAssertFalse(RecoveryInteractionTrace.isEnabled(arguments: arguments, environment: invalid))
    }

    func testDisabledRecorderNeverInstallsOrLogsAndStillForwardsBinding() {
        var installations = 0; var records: [String] = []; var writes = 0; var value = false
        let recorder = RecoveryInteractionTrace.Recorder(arguments: [], environment: environment,
            emit: { records.append($0) }, install: { installations += 1; return true })
        let model = result()
        recorder.begin(result: model)
        let original = Binding(get: { value }, set: { value = $0; writes += 1 })
        recorder.binding(original, field: .model, resultID: model.id).wrappedValue = true
        recorder.end(resultID: model.id)
        XCTAssertTrue(value); XCTAssertEqual(writes, 1)
        XCTAssertEqual(installations, 0); XCTAssertTrue(records.isEmpty)
    }

    func testScopeAndInstallationAreIdempotentAndDoNotResetOnReappearance() throws {
        var installations = 0; var records: [String] = []
        let recorder = RecoveryInteractionTrace.Recorder(arguments: arguments, environment: environment,
            emit: { records.append($0) }, install: { installations += 1; return false })
        let model = result()
        recorder.begin(result: model); recorder.begin(result: model)
        recorder.end(resultID: UUID())
        XCTAssertEqual(recorder.activeResultID, model.id)
        recorder.end(resultID: model.id); recorder.end(resultID: model.id)
        recorder.begin(result: model)
        XCTAssertEqual(installations, 1)
        let rows = try decode(records)
        XCTAssertEqual(rows.compactMap { $0["kind"] as? String }, ["begin", "end", "begin"])
        XCTAssertEqual(rows.compactMap { $0["sequence"] as? Int }, [1, 2, 3])
        XCTAssertEqual(rows[0]["touch_hook_installed"] as? Bool, false)
    }

    private struct MarkerKey: TransactionKey { static let defaultValue = 0 }

    func testBindingPreservesTransactionAndEveryWriteWithoutGetterLogging() throws {
        var records: [String] = []; var value = false; var markers: [Int] = []
        let recorder = RecoveryInteractionTrace.Recorder(arguments: arguments, environment: environment,
            emit: { records.append($0) }, install: { false })
        let model = result(); recorder.begin(result: model)
        let original = Binding(get: { value }, set: { next, transaction in
            value = next; markers.append(transaction[MarkerKey.self])
        })
        let binding = recorder.binding(original, field: .model, resultID: model.id)
        var transaction = Transaction(); transaction[MarkerKey.self] = 47
        XCTAssertFalse(binding.wrappedValue); XCTAssertFalse(binding.wrappedValue)
        XCTAssertEqual(records.count, 1)
        binding.transaction(transaction).wrappedValue = true
        binding.transaction(transaction).wrappedValue = true
        binding.transaction(transaction).wrappedValue = false
        XCTAssertEqual(markers, [47, 47, 47]); XCTAssertFalse(value)
        let rows = try decode(records).filter { $0["kind"] as? String == "binding_set" }
        XCTAssertEqual(rows.compactMap { $0["old"] as? Bool }, [false, true, true])
        XCTAssertEqual(rows.compactMap { $0["new"] as? Bool }, [true, true, false])
    }

    func testSnapshotAndMessagesExcludeOCRTextAndLogOnlyActiveObservedState() throws {
        var records: [String] = []
        let recorder = RecoveryInteractionTrace.Recorder(arguments: arguments, environment: environment,
            emit: { records.append($0) }, install: { false })
        var model = result(); let before = RecoveryInteractionTrace.Snapshot(result: model)
        model.suggestions[0].value = "OTHER PRIVATE VALUE"
        XCTAssertEqual(before, RecoveryInteractionTrace.Snapshot(result: model))
        model.suggestions[0].isSelected = true
        let after = RecoveryInteractionTrace.Snapshot(result: model)
        recorder.stateChanged(from: before, to: after)
        XCTAssertTrue(records.isEmpty)
        recorder.begin(result: model); recorder.stateChanged(from: before, to: after)
        recorder.end(resultID: model.id); recorder.stateChanged(from: after, to: before)
        XCTAssertEqual(try decode(records).compactMap { $0["kind"] as? String }, ["begin", "state_observed", "end"])
        XCTAssertFalse(records.joined().contains("PRIVATE"))
    }

    func testRecordCapCannotStopWritesOrRenewAcrossScopes() throws {
        var records: [String] = []; var writes = 0; var value = false
        let recorder = RecoveryInteractionTrace.Recorder(arguments: arguments, environment: environment,
            emit: { records.append($0) }, install: { false })
        let model = result(); recorder.begin(result: model)
        let original = Binding(get: { value }, set: { value = $0; writes += 1 })
        let binding = recorder.binding(original, field: .model, resultID: model.id)
        for _ in 0..<150 { binding.wrappedValue.toggle() }
        recorder.end(resultID: model.id); recorder.begin(result: result())
        XCTAssertEqual(writes, 150); XCTAssertFalse(value)
        XCTAssertEqual(records.count, 128)
        XCTAssertEqual(try decode(records).last?["kind"] as? String, "record_limit")
        XCTAssertNil(recorder.touchResultIDForObservation())
        XCTAssertTrue(records.allSatisfy { $0.utf8.count <= 8192 })
    }

    func testObservedIdentityReplacementAdvancesScopeWithoutReinstalling() throws {
        var records: [String] = []; var installations = 0
        let recorder = RecoveryInteractionTrace.Recorder(arguments: arguments, environment: environment,
            emit: { records.append($0) }, install: { installations += 1; return true })
        let first = result(); let replacement = result()
        recorder.begin(result: first)
        recorder.stateChanged(from: .init(result: first), to: .init(result: replacement))
        recorder.end(resultID: first.id)
        XCTAssertEqual(recorder.activeResultID, replacement.id)
        recorder.end(resultID: replacement.id)
        let rows = try decode(records)
        XCTAssertEqual(rows.compactMap { $0["kind"] as? String }, ["begin", "state_observed", "end"])
        XCTAssertEqual(rows[1]["from_result_id"] as? String, first.id.uuidString)
        XCTAssertEqual(rows[1]["to_result_id"] as? String, replacement.id.uuidString)
        XCTAssertEqual(rows.compactMap { $0["sequence"] as? Int }, [1, 2, 3])
        XCTAssertEqual(installations, 1)
    }

    func testTouchBudgetReservesStateAndBoundsMetadataWithoutEventInjection() throws {
        var records: [String] = []; var value = false
        let recorder = RecoveryInteractionTrace.Recorder(arguments: arguments, environment: environment,
            emit: { records.append($0) }, install: { false })
        let model = result(); recorder.begin(result: model)
        let view = RecoveryInteractionTrace.ViewSample(className: "V",
            frame: CGRect(x: Double.infinity, y: 0, width: 61, height: 28), hidden: false,
            alpha: .nan, interactionEnabled: true, controlEnabled: true, switchOn: false)
        let touch = RecoveryInteractionTrace.TouchSample(phase: 0, timestamp: .infinity,
            locationInWindow: CGPoint(x: 310, y: 353), ancestors: Array(repeating: view, count: 12))
        let sample = RecoveryInteractionTrace.EventSample(resultID: model.id, observedUptime: .nan,
            touches: Array(repeating: touch, count: 8), totalTouchCount: 8)
        for _ in 0..<110 { recorder.eventWasForwarded(sample) }
        XCTAssertNil(recorder.touchResultIDForObservation())
        let beforeRepeatedAdmission = records.count
        XCTAssertNil(recorder.touchResultIDForObservation())
        XCTAssertEqual(records.count, beforeRepeatedAdmission)
        recorder.binding(Binding(get: { value }, set: { value = $0 }), field: .model, resultID: model.id).wrappedValue = true
        recorder.end(resultID: model.id)
        let rows = try decode(records)
        XCTAssertEqual(rows.filter { $0["kind"] as? String == "touch_limit" }.count, 1)
        XCTAssertEqual(rows.filter { $0["kind"] as? String == "binding_set" }.count, 1)
        XCTAssertEqual(rows.last?["kind"] as? String, "end")
        XCTAssertTrue(value); XCTAssertTrue(records.allSatisfy { $0.utf8.count <= 8192 })
        let event = try XCTUnwrap(rows.first { $0["kind"] as? String == "touch_association" })
        let touches = try XCTUnwrap(event["touches"] as? [[String: Any]])
        XCTAssertEqual(touches.count, 4)
        XCTAssertEqual(event["touches_truncated"] as? Bool, true)
        XCTAssertEqual(event["action_recipient_proven"] as? Bool, false)
        let ancestors = try XCTUnwrap(touches[0]["ancestors"] as? [[String: Any]])
        XCTAssertEqual(ancestors.count, 8)
        XCTAssertTrue(touches[0]["timestamp"] is NSNull)
        XCTAssertTrue(ancestors[0]["alpha"] is NSNull)
        let frame = try XCTUnwrap(ancestors[0]["frame_in_superview"] as? [Any])
        XCTAssertTrue(frame[0] is NSNull)
    }

    func testOversizedMetadataEmitsExplicitBoundedLimitRecord() throws {
        var records: [String] = []
        let recorder = RecoveryInteractionTrace.Recorder(arguments: arguments, environment: environment,
            emit: { records.append($0) }, install: { false })
        let model = result(); recorder.begin(result: model)
        let view = RecoveryInteractionTrace.ViewSample(className: String(repeating: "界", count: 200),
            frame: .zero, hidden: false, alpha: 1, interactionEnabled: true,
            controlEnabled: nil, switchOn: nil)
        let touch = RecoveryInteractionTrace.TouchSample(phase: 0, timestamp: 1,
            locationInWindow: .zero, ancestors: Array(repeating: view, count: 8))
        recorder.eventWasForwarded(RecoveryInteractionTrace.EventSample(resultID: model.id, observedUptime: 1,
            touches: Array(repeating: touch, count: 4), totalTouchCount: 4))
        let row = try XCTUnwrap(decode(records).last)
        XCTAssertEqual(row["kind"] as? String, "message_limit")
        XCTAssertEqual(row["diagnostic_incomplete"] as? Bool, true)
        XCTAssertTrue(records.allSatisfy { $0.utf8.count <= 8192 })
    }
}
#endif
