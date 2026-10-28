import XCTest

final class RecoveryPhotosReadTests: XCTestCase {
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
