import XCTest
@testable import RoomInventory

#if DEBUG
@MainActor
final class UnitTestHostTests: XCTestCase {
    private let session = "11111111-2222-4333-8444-555555555555"

    func testExactUnitBundleAndSessionIdentifyTheUnitHost() {
        for path in ["PlugIns/RoomInventoryTests.xctest",
                     "/Applications/RoomInventory.app/PlugIns/RoomInventoryTests.xctest"] {
            XCTAssertTrue(RoomInventoryApp.isUnitTestHost(environment: [
                "XCTestBundlePath": path, "XCTestSessionIdentifier": session]))
        }
        XCTAssertTrue(RoomInventoryApp.isUnitTestHost(environment: ProcessInfo.processInfo.environment))
    }

    func testUIRunnerAndOrdinaryLaunchesKeepTheApplicationRoot() {
        for path in ["PlugIns/RoomInventoryUITests.xctest", "OtherTests.xctest",
                     "RoomInventoryTests.xctest.extra", "RoomInventoryTests.xctest/Other", ""] {
            XCTAssertFalse(RoomInventoryApp.isUnitTestHost(environment: [
                "XCTestBundlePath": path, "XCTestSessionIdentifier": session]))
        }
        XCTAssertFalse(RoomInventoryApp.isUnitTestHost(environment: [:]))
        XCTAssertFalse(RoomInventoryApp.isUnitTestHost(environment: ["XCTestSessionIdentifier": session]))
    }

    func testUnitBundleAloneOrMalformedSessionKeepsTheApplicationRoot() {
        XCTAssertFalse(RoomInventoryApp.isUnitTestHost(environment: [
            "XCTestBundlePath": "PlugIns/RoomInventoryTests.xctest"]))
        for value in ["", "not-a-session", session + "\n"] {
            XCTAssertFalse(RoomInventoryApp.isUnitTestHost(environment: [
                "XCTestBundlePath": "PlugIns/RoomInventoryTests.xctest", "XCTestSessionIdentifier": value]))
        }
    }
}
#endif
