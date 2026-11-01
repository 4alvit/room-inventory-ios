import XCTest

final class RecoveryPhotosAppearanceWindowTests: XCTestCase {
    func testSystemPickerAppearingAfterTwentySecondsIsAccepted() throws {
        var now = 100.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        now = 101
        XCTAssertTrue(try window.wait { remaining in
            XCTAssertEqual(remaining, 29)
            now = 121
            return true
        })
        XCTAssertEqual(try window.remaining(), 9)
    }

    func testExactOrLateSuccessfulQueryCannotAuthorizeSelection() {
        for elapsed in [30.0, 30.001] {
            var now = 0.0
            let window = RecoveryPhotosAppearanceWindow(clock: { now })
            var selected = false
            XCTAssertThrowsError(try {
                let appeared = try window.wait { _ in now = elapsed; return true }
                selected = appeared
            }()) { XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .expired) }
            XCTAssertFalse(selected)
        }
    }

    func testExpiredWindowDoesNotStartAnotherQuery() {
        var now = 0.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        now = 30
        var queries = 0
        XCTAssertThrowsError(try window.wait { _ in queries += 1; return true }) {
            XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .expired)
        }
        XCTAssertEqual(queries, 0)
    }

    func testFalseResultIsPreservedWithoutRenewingBudget() throws {
        var now = 0.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        XCTAssertFalse(try window.wait { remaining in
            XCTAssertEqual(remaining, 30)
            now = 20
            return false
        })
        XCTAssertEqual(try window.remaining(), 10)
    }

    func testQueryFailureIsPreservedAndCannotAuthorizeSelection() {
        enum QueryFailure: Error { case unavailable }
        var now = 0.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        var selected = false
        XCTAssertThrowsError(try {
            _ = try window.wait { _ in
                now = 31
                throw QueryFailure.unavailable
            }
            selected = true
        }()) { XCTAssertTrue($0 is QueryFailure) }
        XCTAssertFalse(selected)
    }
}
