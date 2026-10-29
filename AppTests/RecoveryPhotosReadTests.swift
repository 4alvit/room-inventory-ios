import XCTest
import Photos

final class RecoveryPhotosReadTests: XCTestCase {
    func testAuthorizationPolicyRequestsOnlyUndeterminedAndNeverTreatsLimitedAsFull() {
        XCTAssertEqual(RecoveryPhotosFixture.authorizationAction(.authorized), .proceed)
        XCTAssertEqual(RecoveryPhotosFixture.authorizationAction(.notDetermined), .request)
        let rejected: [PHAuthorizationStatus] = [.denied, .restricted, .limited]
        for status in rejected {
            XCTAssertEqual(RecoveryPhotosFixture.authorizationAction(status), .reject)
        }
    }

    func testAuthorizationCallbackIsBoundedAndCannotReplaceFirstOutcome() throws {
        let start = ContinuousClock().now
        let deadline = start.advanced(by: .seconds(20))
        let denied = PhotoFixtureAuthorization(deadline: deadline)
        XCTAssertTrue(denied.complete(.denied, at: start))
        XCTAssertFalse(denied.complete(.authorized, at: start))
        XCTAssertEqual(denied.observedStatus(), PHAuthorizationStatus.denied.rawValue)
        XCTAssertThrowsError(try denied.result())
        let late = PhotoFixtureAuthorization(deadline: deadline)
        XCTAssertTrue(late.complete(.authorized, at: deadline))
        XCTAssertThrowsError(try late.result())
        let allowed = PhotoFixtureAuthorization(deadline: deadline)
        XCTAssertThrowsError(try allowed.result())
        XCTAssertTrue(allowed.complete(.authorized, at: start))
        XCTAssertFalse(allowed.complete(.denied, at: deadline))
        XCTAssertEqual(allowed.observedStatus(), PHAuthorizationStatus.authorized.rawValue)
        XCTAssertNoThrow(try allowed.result())
    }

    func testAuthorizedCallbackWithoutPromptIsDistinctFromIncompleteInteraction() {
        for interacted in [false, true] {
            XCTAssertTrue(RecoveryPhotosFixture.authorizationRequestCompleted(callbackRaw: 3, after: .authorized,
                promptSeen: interacted, promptAccepted: interacted))
        }
        let failures: [(Int?, PHAuthorizationStatus, Bool, Bool)] = [
            (nil, .authorized, false, false), (2, .authorized, false, false),
            (3, .limited, false, false), (3, .denied, true, true),
            (3, .authorized, true, false), (3, .authorized, false, true)
        ]
        for (raw, after, seen, accepted) in failures {
            XCTAssertFalse(RecoveryPhotosFixture.authorizationRequestCompleted(callbackRaw: raw, after: after,
                promptSeen: seen, promptAccepted: accepted))
        }
    }

    func testOnlyUnambiguousExactRunnerPhotosFullAccessPromptPermitsInteraction() {
        let name = "RoomInventoryUITests-Runner"
        let usage = "Access is necessary for automated testing."
        let title = "“\(name)” Would Like Full Access to Your Photo Library"
        let buttons = ["Select Photos…", "Allow Full Access", "Don’t Allow"]
        XCTAssertTrue(RecoveryPhotosFixture.permitsAuthorizationPrompt(
            texts: [title, usage], buttons: buttons, runnerName: name, usage: usage, alertCount: 1))
        XCTAssertTrue(RecoveryPhotosFixture.permitsAuthorizationPrompt(
            texts: ["\"\(name)\" Would Like to Access Your Photos", usage], buttons: buttons,
            runnerName: name, usage: usage, alertCount: 1))
        for (texts, controls, count) in [
            ([title, usage], buttons, 2),
            ([title, title, usage], buttons, 1),
            (["“Other App” Would Like Full Access to Your Photo Library", usage], buttons, 1),
            ([title.replacingOccurrences(of: name, with: name + " Extra"), usage], buttons, 1),
            ([title, "Unrelated purpose"], buttons, 1),
            ([title, usage], ["Allow Full Access", "Allow Full Access", "Don’t Allow"], 1),
            ([title, usage], ["Select Photos…", "Don’t Allow"], 1),
            ([title, usage], ["Allow Full Access", "Continue"], 1),
            ([title, usage, String(repeating: "x", count: 2049)], buttons, 1)
        ] {
            XCTAssertFalse(RecoveryPhotosFixture.permitsAuthorizationPrompt(
                texts: texts, buttons: controls, runnerName: name, usage: usage, alertCount: count))
        }
    }

    func testBoundedChunksFinishOnceAndLateCallbacksCannotChangeBytes() throws {
        let start = ContinuousClock().now
        let read = PhotoFixtureRead(limit: 3, deadline: start.advanced(by: .seconds(20)))
        XCTAssertFalse(read.receive(Data([1, 2]), at: start))
        XCTAssertFalse(read.receive(Data([3]), at: start))
        XCTAssertTrue(read.complete(error: nil, at: start))
        XCTAssertFalse(read.receive(Data([4]), at: start))
        XCTAssertFalse(read.complete(error: NSError(domain: "late", code: 1), at: start))
        XCTAssertEqual(try read.result(), Data([1, 2, 3]))
    }

    func testOversizedChunkFailsWithoutAcceptingPartialResource() {
        let start = ContinuousClock().now
        let read = PhotoFixtureRead(limit: 3, deadline: start.advanced(by: .seconds(20)))
        XCTAssertFalse(read.receive(Data([1, 2]), at: start))
        XCTAssertTrue(read.receive(Data([3, 4]), at: start))
        XCTAssertFalse(read.complete(error: nil, at: start))
        XCTAssertThrowsError(try read.result())
    }

    func testCallbackAtOriginalDeadlineCannotBeAccepted() {
        let start = ContinuousClock().now
        let deadline = start.advanced(by: .seconds(20))
        let read = PhotoFixtureRead(limit: 3, deadline: deadline)
        XCTAssertFalse(read.receive(Data([1, 2, 3]), at: start))
        XCTAssertTrue(read.complete(error: nil, at: deadline))
        XCTAssertThrowsError(try read.result())
        XCTAssertFalse(read.complete(error: nil, at: start))
    }

    func testLateDataAndUnfinishedReadAreFailures() {
        let start = ContinuousClock().now
        let read = PhotoFixtureRead(limit: 3, deadline: start)
        XCTAssertThrowsError(try read.result())
        XCTAssertTrue(read.receive(Data([1]), at: start))
        XCTAssertThrowsError(try read.result())
    }

    func testChangeCallbackFailureIsSticky() {
        let start = ContinuousClock().now
        let read = PhotoFixtureRead(limit: 0, deadline: start.advanced(by: .seconds(20)))
        XCTAssertTrue(read.complete(error: NSError(domain: "PhotoKit control", code: 1), at: start))
        XCTAssertFalse(read.complete(error: nil, at: start))
        XCTAssertThrowsError(try read.result())
    }

    func testOnlyExpectedOwnedRunnerAndRemovalCountPermitConfirmation() {
        XCTAssertTrue(RecoveryPhotosFixture.permitsConfirmation(
            text: "RoomInventoryUITests-Runner Would Like to Delete 6 Photos",
            runnerName: "RoomInventoryUITests-Runner", removed: 6))
        for (text, name, count) in [
            ("Other App Would Like to Delete 6 Photos", "RoomInventoryUITests-Runner", 6),
            ("RoomInventoryUITests-Runner Would Like to Delete 7 Photos", "RoomInventoryUITests-Runner", 6),
            ("RoomInventoryUITests-Runner Would Like to Access 6 Photos", "RoomInventoryUITests-Runner", 6),
            ("RoomInventoryUITests-Runner Would Like to Delete 6 Photos", "", 6),
            ("RoomInventoryUITests-Runner Would Like to Delete 64 Photos", "RoomInventoryUITests-Runner", 64)
        ] {
            XCTAssertFalse(RecoveryPhotosFixture.permitsConfirmation(text: text, runnerName: name, removed: count))
        }
    }
}
