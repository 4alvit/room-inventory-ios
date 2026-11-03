import Foundation
import XCTest

final class RecoveryPhotosSeedTests: XCTestCase {
    func testRawBundledFixtureHasExactOriginalBytesAndRejectsChanges() throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "SyntheticRecoveryReceipt", withExtension: "data"))
        let original = try Data(contentsOf: url)
        XCTAssertTrue(RecoveryPhotosFixture.acceptsOriginal(original))
        var changed = original
        changed[0] ^= 1
        XCTAssertFalse(RecoveryPhotosFixture.acceptsOriginal(changed))
        XCTAssertFalse(RecoveryPhotosFixture.acceptsOriginal(original.dropLast()))
        XCTAssertFalse(RecoveryPhotosFixture.acceptsOriginal(original + Data([0])))
    }

    func testOnlyBoundedUniquePrecreationInventoryWithoutNamedFixtureIsAdmitted() {
        XCTAssertTrue(RecoveryPhotosFixture.permitsSeed(initialIDs: [], existingFixtureCount: 0))
        XCTAssertTrue(RecoveryPhotosFixture.permitsSeed(initialIDs: (0..<63).map { "asset-\($0)" }, existingFixtureCount: 0))
        for ids in [["same", "same"], [""], ["new\nline"], [String(repeating: "x", count: 257)],
                    (0..<64).map({ "asset-\($0)" })] {
            XCTAssertFalse(RecoveryPhotosFixture.permitsSeed(initialIDs: ids, existingFixtureCount: 0))
        }
        for count in [-1, 1, 2] {
            XCTAssertFalse(RecoveryPhotosFixture.permitsSeed(initialIDs: ["prior"], existingFixtureCount: count))
        }
    }

    func testFreshInventoryMustPreserveEveryPriorIDAndAddOnlyPlaceholder() {
        XCTAssertTrue(RecoveryPhotosFixture.confirmsSeed(initialIDs: [], finalIDs: ["created"], createdID: "created"))
        XCTAssertTrue(RecoveryPhotosFixture.confirmsSeed(initialIDs: ["prior"], finalIDs: ["created", "prior"], createdID: "created"))
        for (before, after, created) in [
            (["prior"], ["created"], "created"),
            (["prior"], ["prior", "foreign"], "created"),
            (["prior"], ["prior", "created", "extra"], "created"),
            (["prior"], ["prior", "prior"], "prior"),
            (["prior", "prior"], ["prior", "prior", "created"], "created"),
            ([], [""], ""), ([], ["bad\nID"], "bad\nID")
        ] {
            XCTAssertFalse(RecoveryPhotosFixture.confirmsSeed(initialIDs: before, finalIDs: after, createdID: created))
        }
    }

    func testChangeRequiresAdmissionPlaceholderAndCompletionInThatOrder() throws {
        let start = ContinuousClock().now
        let change = PhotoFixtureSeedChange(deadline: start.advanced(by: .seconds(86)))
        XCTAssertThrowsError(try change.result())
        XCTAssertTrue(change.admit(at: start))
        change.created("created", at: start)
        XCTAssertThrowsError(try change.result())
        change.complete(success: true, error: nil, at: start)
        XCTAssertEqual(try change.result(), "created")
        XCTAssertEqual(change.mutationAttempts, 1)
        change.complete(success: false, error: NSError(domain: "late", code: 1), at: start)
        XCTAssertEqual(try change.result(), "created")
        XCTAssertFalse(change.admit(at: start))
        XCTAssertEqual(change.mutationAttempts, 1)
    }

    func testRepeatedAdmissionBeforeCompletionCannotCreateSecondRequest() {
        let start = ContinuousClock().now
        let change = PhotoFixtureSeedChange(deadline: start.advanced(by: .seconds(86)))
        XCTAssertTrue(change.admit(at: start))
        XCTAssertFalse(change.admit(at: start))
        change.created("created", at: start)
        change.complete(success: true, error: nil, at: start)
        XCTAssertThrowsError(try change.result())
        XCTAssertEqual(change.mutationAttempts, 1)
    }

    func testAdmissionAtOrAfterOriginalDeadlineNeverMutates() {
        let start = ContinuousClock().now
        let deadline = start.advanced(by: .seconds(86))
        for time in [deadline, deadline.advanced(by: .seconds(1))] {
            let change = PhotoFixtureSeedChange(deadline: deadline)
            XCTAssertFalse(change.admit(at: time))
            change.complete(success: true, error: nil, at: start)
            XCTAssertThrowsError(try change.result())
            XCTAssertEqual(change.mutationAttempts, 0)
        }
    }

    func testLatePlaceholderCannotBeBlessedByEarlierTimestampCompletion() {
        let start = ContinuousClock().now
        let deadline = start.advanced(by: .seconds(86))
        let change = PhotoFixtureSeedChange(deadline: deadline)
        XCTAssertTrue(change.admit(at: start))
        change.created("created", at: deadline)
        change.complete(success: true, error: nil, at: start)
        XCTAssertThrowsError(try change.result())
        XCTAssertEqual(change.mutationAttempts, 1)
    }

    func testCompletionAtDeadlineRemainsFailureAfterAnyLaterCallback() {
        let start = ContinuousClock().now
        let deadline = start.advanced(by: .seconds(86))
        let change = PhotoFixtureSeedChange(deadline: deadline)
        XCTAssertTrue(change.admit(at: start))
        change.created("created", at: start)
        change.complete(success: true, error: nil, at: deadline)
        change.complete(success: true, error: nil, at: start)
        XCTAssertThrowsError(try change.result())
    }

    func testMissingOrMalformedPlaceholderFailsEvenWithSuccessfulCallback() {
        let start = ContinuousClock().now
        let invalid: [String?] = [nil, "", "bad\nID", String(repeating: "x", count: 257)]
        for identifier in invalid {
            let change = PhotoFixtureSeedChange(deadline: start.advanced(by: .seconds(86)))
            XCTAssertTrue(change.admit(at: start))
            change.created(identifier, at: start)
            change.complete(success: true, error: nil, at: start)
            XCTAssertThrowsError(try change.result())
        }
    }

    func testCallbackWithoutAdmissionOrPlaceholderCannotReportSuccess() {
        let start = ContinuousClock().now
        for admitted in [false, true] {
            let change = PhotoFixtureSeedChange(deadline: start.advanced(by: .seconds(86)))
            if admitted { XCTAssertTrue(change.admit(at: start)) }
            change.complete(success: true, error: nil, at: start)
            XCTAssertThrowsError(try change.result())
            XCTAssertFalse(change.admit(at: start))
        }
    }

    func testFailedCallbackOrChangeBlockErrorRemainsSticky() {
        let start = ContinuousClock().now
        for mode in 0..<3 {
            let change = PhotoFixtureSeedChange(deadline: start.advanced(by: .seconds(86)))
            XCTAssertTrue(change.admit(at: start))
            change.created("created", at: start)
            let error = NSError(domain: "synthetic-seed-failure", code: 1)
            if mode == 0 { change.fail(error, at: start) }
            else { change.complete(success: mode == 1, error: mode == 1 ? error : nil, at: start) }
            change.complete(success: true, error: nil, at: start)
            XCTAssertThrowsError(try change.result())
            XCTAssertEqual(change.mutationAttempts, 1)
        }
    }

    func testEarlyChangeBlockFailureCannotBeOverwrittenByFrameworkNoOpSuccess() {
        let start = ContinuousClock().now
        let change = PhotoFixtureSeedChange(deadline: start.advanced(by: .seconds(86)))
        change.fail(NSError(domain: "inventory-changed-before-request", code: 1), at: start)
        XCTAssertFalse(change.admit(at: start))
        change.complete(success: true, error: nil, at: start)
        XCTAssertThrowsError(try change.result())
        XCTAssertEqual(change.mutationAttempts, 0)
    }
}
