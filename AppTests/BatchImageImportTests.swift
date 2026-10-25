import XCTest
@testable import RoomInventory

@MainActor
final class BatchImageImportTests: XCTestCase {
    private enum Failure: LocalizedError, Equatable {
        case provider, storage
        var errorDescription: String? { self == .provider ? "Provider unavailable" : "Storage unavailable" }
    }

    private func payload(_ value: String) -> BatchImageImport.Payload {
        .init(data: Data(value.utf8), originalName: value)
    }

    func testSelectionLimitsRejectBeforeAnyProviderOrSaveRuns() async throws {
        let importer = BatchImageImport()
        var loads = 0
        var saves = 0
        let sources = (0..<11).map { index in
            BatchImageImport.Source(name: "Image \(index)") { loads += 1; return self.payload("\(index)") }
        }
        for (selection, isPro) in [(Array(sources.prefix(2)), false), (sources, true)] {
            do {
                try await importer.start(selection, isPro: { isPro }) { _ in saves += 1 }
                XCTFail("Over-limit selection was accepted")
            } catch BatchImageImportError.tooManyImages(let limit) {
                XCTAssertEqual(limit, isPro ? 10 : 1)
            }
        }
        XCTAssertEqual(loads, 0)
        XCTAssertEqual(saves, 0)
        XCTAssertTrue(importer.entries.isEmpty)
        XCTAssertFalse(importer.isRunning)
    }

    func testPartialProviderFailureRetriesOnlyFailedSource() async throws {
        let importer = BatchImageImport()
        var loads = [0, 0, 0]
        var saved: [String] = []
        let sources = (0..<3).map { index in
            BatchImageImport.Source(name: "Image \(index)") {
                loads[index] += 1
                if index == 1 && loads[index] == 1 { throw Failure.provider }
                return self.payload("\(index)")
            }
        }
        try await importer.start(sources, isPro: { true }) { saved.append($0.originalName!) }
        XCTAssertEqual(saved, ["0", "2"])
        XCTAssertEqual(importer.savedCount, 2)
        XCTAssertEqual(importer.failedCount, 1)
        XCTAssertEqual(importer.completedCount, 3)
        let identifiers = importer.entries.map(\.id)

        try await importer.retryFailed(isPro: { true }) { saved.append($0.originalName!) }
        XCTAssertEqual(saved, ["0", "2", "1"])
        XCTAssertEqual(loads, [1, 2, 1])
        XCTAssertEqual(importer.entries.map(\.id), identifiers)
        XCTAssertEqual(importer.entries.map(\.name), ["Image 0", "Image 1", "Image 2"])
        XCTAssertEqual(importer.savedCount, 3)
        XCTAssertEqual(importer.failedCount, 0)
        // Repeating Retry after success is an intentional no-op.
        try await importer.retryFailed(isPro: { true }) { _ in XCTFail("Saved image was duplicated") }
    }

    func testStorageFailureDoesNotRollbackEarlierSaveOrRepeatItOnRetry() async throws {
        let importer = BatchImageImport()
        var calls: [String] = []
        var stored: [String] = []
        let sources = ["first", "second"].map { name in
            BatchImageImport.Source(name: name) { self.payload(name) }
        }
        try await importer.start(sources, isPro: { true }) { value in
            let name = value.originalName!
            calls.append(name)
            if name == "second" { throw Failure.storage }
            stored.append(name)
        }
        XCTAssertEqual(stored, ["first"])
        XCTAssertEqual(importer.entries[0].status, .saved)
        XCTAssertEqual(importer.entries[1].status, .failed("Storage unavailable"))

        try await importer.retryFailed(isPro: { true }) { value in calls.append(value.originalName!); stored.append(value.originalName!) }
        XCTAssertEqual(calls, ["first", "second", "second"])
        XCTAssertEqual(stored, ["first", "second"])
        XCTAssertEqual(importer.savedCount, 2)
    }

    func testProcessingIsSequentialAndExposesCurrentProgress() async throws {
        let importer = BatchImageImport()
        var events: [String] = []
        let sources = (0..<3).map { index in
            BatchImageImport.Source(name: "Image \(index)") {
                XCTAssertTrue(importer.isRunning)
                XCTAssertEqual(importer.completedCount, index)
                XCTAssertEqual(importer.currentName, "Image \(index)")
                events.append("load\(index)")
                await Task.yield()
                return self.payload("\(index)")
            }
        }
        try await importer.start(sources, isPro: { true }) { value in
            events.append("save\(value.originalName!)")
            await Task.yield()
        }
        XCTAssertEqual(events, ["load0", "save0", "load1", "save1", "load2", "save2"])
        XCTAssertEqual(importer.completedCount, 3)
        XCTAssertNil(importer.currentName)
        XCTAssertFalse(importer.isRunning)
    }

    func testRevocationWhileProviderLoadsKeepsSavedImageAndBlocksRemainingSaves() async throws {
        let importer = BatchImageImport()
        var isPro = true
        var loads = [0, 0, 0]
        var saved: [String] = []
        let sources = (0..<3).map { index in
            BatchImageImport.Source(name: "Image \(index)") {
                loads[index] += 1
                if index == 1 { isPro = false }
                return self.payload("\(index)")
            }
        }
        try await importer.start(sources, isPro: { isPro }) { saved.append($0.originalName!) }
        XCTAssertEqual(saved, ["0"])
        XCTAssertEqual(loads, [1, 1, 0])
        XCTAssertEqual(importer.savedCount, 1)
        XCTAssertEqual(importer.failedCount, 2)
        try await importer.retryFailed(isPro: { isPro }) { _ in XCTFail("Revoked batch saved an image") }
        XCTAssertEqual(loads, [1, 1, 0])
        XCTAssertEqual(importer.savedCount, 1)
    }

    func testReentrantSelectionCannotDiscardInFlightResults() async throws {
        let importer = BatchImageImport()
        let replacement = BatchImageImport.Source(name: "replacement") { self.payload("replacement") }
        let source = BatchImageImport.Source(name: "original") {
            do {
                try await importer.start([replacement], isPro: { false }) { _ in XCTFail("Unexpected replacement save") }
                XCTFail("Concurrent import was accepted")
            } catch BatchImageImportError.busy { }
            importer.reset()
            XCTAssertEqual(importer.entries.first?.name, "original")
            return self.payload("original")
        }
        var saved: [String] = []
        try await importer.start([source], isPro: { false }) { saved.append($0.originalName!) }
        XCTAssertEqual(saved, ["original"])
        XCTAssertEqual(importer.savedCount, 1)
        importer.reset()
        XCTAssertTrue(importer.entries.isEmpty)
    }

    func testCancellationKeepsSavedImageAndRetryProcessesOnlyUnfinishedImages() async throws {
        let importer = BatchImageImport()
        let suspended = XCTestExpectation(description: "Second provider suspended")
        var continuation: CheckedContinuation<Void, Never>?
        var loads = [0, 0, 0]
        var saved: [String] = []
        let sources = (0..<3).map { index in
            BatchImageImport.Source(name: "Image \(index)") {
                loads[index] += 1
                if index == 1 && loads[index] == 1 {
                    await withCheckedContinuation { pending in
                        continuation = pending
                        suspended.fulfill()
                    }
                }
                return self.payload("\(index)")
            }
        }
        let task = Task {
            try await importer.start(sources, isPro: { true }) { saved.append($0.originalName!) }
        }
        defer {
            task.cancel()
            continuation?.resume()
        }
        let waitResult = await XCTWaiter.fulfillment(of: [suspended], timeout: 3)
        XCTAssertEqual(waitResult, .completed)
        guard waitResult == .completed else { return }
        XCTAssertEqual(saved, ["0"])
        XCTAssertEqual(importer.savedCount, 1)

        task.cancel()
        continuation?.resume()
        continuation = nil
        try await task.value

        XCTAssertEqual(saved, ["0"], "A cancelled provider must not reach save")
        XCTAssertEqual(loads, [1, 1, 0], "Cancellation must stop loading subsequent sources")
        XCTAssertEqual(importer.entries[0].status, .saved)
        XCTAssertEqual(importer.failedCount, 2)
        XCTAssertEqual(importer.completedCount, 3, "Unfinished entries must remain visible as failed")
        XCTAssertFalse(importer.isRunning)

        try await importer.retryFailed(isPro: { true }) { saved.append($0.originalName!) }
        XCTAssertEqual(saved, ["0", "1", "2"])
        XCTAssertEqual(loads, [1, 2, 1], "Retry must not reload the already saved original")
        XCTAssertEqual(importer.savedCount, 3)
        XCTAssertEqual(importer.failedCount, 0)
    }

    func testCancellationDuringPreparationCannotCommitAndRetryKeepsEarlierSave() async throws {
        let importer = BatchImageImport()
        let suspended = XCTestExpectation(description: "Second image preparation suspended")
        var continuation: CheckedContinuation<Void, Never>?
        var saved: [String] = []
        var prepared: [String] = []
        let sources = ["first", "second", "third"].map { name in
            BatchImageImport.Source(name: name) { self.payload(name) }
        }
        let task = Task {
            try await importer.start(sources, isPro: { true }, prepare: { payload in
                prepared.append(payload.originalName!)
                if payload.originalName == "second" {
                    await withCheckedContinuation { pending in
                        continuation = pending
                        suspended.fulfill()
                    }
                }
            }, save: { saved.append($0.originalName!) })
        }
        defer { task.cancel(); continuation?.resume() }
        let result = await XCTWaiter.fulfillment(of: [suspended], timeout: 3)
        XCTAssertEqual(result, .completed)
        guard result == .completed else { return }
        task.cancel()
        continuation?.resume()
        continuation = nil
        try await task.value

        XCTAssertEqual(saved, ["first"], "Cancelled preparation must never enter persistence")
        XCTAssertEqual(prepared, ["first", "second"])
        XCTAssertEqual(importer.entries[0].status, .saved)
        XCTAssertEqual(importer.failedCount, 2)
        try await importer.retryFailed(isPro: { true }, prepare: { prepared.append($0.originalName!) },
                                       save: { saved.append($0.originalName!) })
        XCTAssertEqual(saved, ["first", "second", "third"])
        XCTAssertEqual(prepared, ["first", "second", "second", "third"])
        XCTAssertEqual(importer.savedCount, 3)
    }

    func testCancellationAfterCommitStartsStillRecordsSuccessAndDoesNotDuplicateIt() async throws {
        let importer = BatchImageImport()
        let suspended = XCTestExpectation(description: "Atomic save started")
        var continuation: CheckedContinuation<Void, Never>?
        var saved: [String] = []
        let sources = ["first", "second"].map { name in
            BatchImageImport.Source(name: name) { self.payload(name) }
        }
        let task = Task {
            try await importer.start(sources, isPro: { true }) { payload in
                await withCheckedContinuation { pending in
                    continuation = pending
                    suspended.fulfill()
                }
                saved.append(payload.originalName!)
            }
        }
        defer { task.cancel(); continuation?.resume() }
        let result = await XCTWaiter.fulfillment(of: [suspended], timeout: 3)
        XCTAssertEqual(result, .completed)
        guard result == .completed else { return }
        task.cancel()
        continuation?.resume()
        continuation = nil
        try await task.value

        XCTAssertEqual(saved, ["first"])
        XCTAssertEqual(importer.entries[0].status, .saved, "An atomic commit that succeeded remains a success")
        XCTAssertEqual(importer.failedCount, 1)
        try await importer.retryFailed(isPro: { true }) { saved.append($0.originalName!) }
        XCTAssertEqual(saved, ["first", "second"])
        XCTAssertEqual(importer.savedCount, 2)
    }
}
