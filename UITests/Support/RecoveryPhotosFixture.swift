import CryptoKit
import Foundation
import Photos
import XCTest

/// Callback state is protected by this lock, including late callbacks after cancellation.
/// Only the small synthetic fixture can be buffered; no PhotoKit payload is written here.
final class PhotoFixtureRead: @unchecked Sendable {
    private let lock = NSLock()
    private let limit: Int
    private let deadline: ContinuousClock.Instant
    private var data = Data()
    private var finished = false
    private var failure: String?
    // XCTest permits background fulfillment; the lock admits it exactly once.
    let expectation = XCTestExpectation(description: "bounded Photos operation")
    func signal() { expectation.fulfill() }
    var isFinished: Bool {
        lock.lock(); defer { lock.unlock() }
        return finished
    }

    init(limit: Int, deadline: ContinuousClock.Instant) {
        self.limit = limit
        self.deadline = deadline
    }

    func receive(_ chunk: Data, at now: ContinuousClock.Instant = ContinuousClock().now) -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard !finished else { return false }
        if now >= deadline || chunk.count > limit - data.count {
            failure = now >= deadline ? "resource callback deadline" : "resource byte bound exceeded"
            finished = true
            return true
        }
        data.append(chunk)
        return false
    }

    func complete(error: Error?, at now: ContinuousClock.Instant = ContinuousClock().now) -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard !finished else { return false }
        finished = true
        if now >= deadline { failure = "PhotoKit callback deadline" }
        else if let error {
            let value = error as NSError
            failure = "PhotoKit callback failed: \(value.domain.prefix(128)) / \(value.code)"
        }
        return true
    }

    func result() throws -> Data {
        lock.lock(); defer { lock.unlock() }
        guard finished else { throw PhotoFixtureError.invalid("callback did not finish") }
        if let failure { throw PhotoFixtureError.invalid(failure) }
        return data
    }
}

enum PhotoFixtureError: Error, CustomStringConvertible {
    case invalid(String)
    var description: String {
        switch self { case let .invalid(value): "Recovery Photos fixture: \(value)" }
    }
}

/// The permission callback may arrive on a background queue or after the deadline.
final class PhotoFixtureAuthorization: @unchecked Sendable {
    private let lock = NSLock()
    private let completion: PhotoFixtureRead
    private var rawStatus: Int?
    var expectation: XCTestExpectation { completion.expectation }
    var isFinished: Bool { completion.isFinished }
    init(deadline: ContinuousClock.Instant) { completion = PhotoFixtureRead(limit: 0, deadline: deadline) }
    func complete(_ status: PHAuthorizationStatus, at now: ContinuousClock.Instant = ContinuousClock().now) -> Bool {
        lock.lock(); defer { lock.unlock() }
        let error: Error? = status == .authorized ? nil
            : PhotoFixtureError.invalid("authorization callback status \(status.rawValue)")
        guard completion.complete(error: error, at: now) else { return false }
        rawStatus = status.rawValue
        return true
    }
    func signal() { completion.signal() }
    func observedStatus() -> Int? { lock.lock(); defer { lock.unlock() }; return rawStatus }
    func result() throws { _ = try completion.result() }
}

@MainActor
final class RecoveryPhotosFixture {
    static let filename = "SyntheticRecoveryReceipt.png"
    static let bytes = 74_736
    static let digest = "3be0a311997c35182f58e2658f64afe06b437665dfb420f1dc595e23e24ea181"
    static let seconds = 20.0
    private static let assetLimit = 64

    static func isolate(deviceID: String, report: inout [String: Any]) throws {
        let clock = ContinuousClock()
        let started = clock.now
        let deadline = started.advanced(by: .seconds(seconds))
        defer { report["elapsed_seconds"] = duration(started.duration(to: clock.now)) }
        #if !targetEnvironment(simulator)
        throw PhotoFixtureError.invalid("physical device is forbidden")
        #else
        let environment = ProcessInfo.processInfo.environment
        guard environment["RUN_INVENTORY_RECOVERY_JOURNEY"] == "1",
              environment["SIMULATOR_UDID"] == deviceID,
              Bundle.main.bundleIdentifier == "com.alvit.roominventory.uitests.xctrunner" else {
            throw PhotoFixtureError.invalid("actual owned Simulator/runner binding missing")
        }
        guard let usage = Bundle.main.object(forInfoDictionaryKey: "NSPhotoLibraryUsageDescription") as? String,
              !usage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw PhotoFixtureError.invalid("actual runner lacks Photos usage metadata")
        }
        try authorize(deadline: deadline, usage: usage, report: &report)
        report["read_write_authorized"] = true
        let before = try inventory(deadline: deadline)
        report["initial_asset_count"] = before.count
        let beforeIDs = before.map(\.localIdentifier).sorted()
        report["initial_asset_ids_sha256"] = idsDigest(beforeIDs)
        let (fixture, resource) = try fixtureResource(in: before, deadline: deadline)
        report["fixture_asset_id"] = fixture.localIdentifier
        let original = try read(resource, deadline: deadline)
        report["before_bytes"] = original.count
        report["before_sha256"] = hash(original)
        guard original.count == bytes, hash(original) == digest else {
            throw PhotoFixtureError.invalid("seeded original bytes or hash differ")
        }
        // Re-read before changing anything: no stale snapshot may authorize removal.
        guard try inventory(deadline: deadline).map(\.localIdentifier).sorted() == beforeIDs else {
            throw PhotoFixtureError.invalid("Photos inventory changed before isolation")
        }
        let removedIDs = beforeIDs.filter { $0 != fixture.localIdentifier }
        report["removed_asset_count"] = removedIDs.count
        report["removed_asset_ids_sha256"] = idsDigest(removedIDs)
        report["change_requested"] = !removedIDs.isEmpty
        report["confirmation_seen"] = false
        report["confirmation_accepted"] = false
        report["confirmation_text"] = ""
        if !removedIDs.isEmpty {
            try remove(removedIDs, deadline: deadline, report: &report)
        }
        report["change_completed"] = true
        let after = try inventory(deadline: deadline)
        report["final_asset_count"] = after.count
        guard after.count == 1, after[0].localIdentifier == fixture.localIdentifier else {
            throw PhotoFixtureError.invalid("isolation did not leave exactly the same fixture")
        }
        let (_, finalResource) = try fixtureResource(in: after, deadline: deadline)
        let final = try read(finalResource, deadline: deadline)
        report["after_bytes"] = final.count
        report["after_sha256"] = hash(final)
        guard final.count == bytes, hash(final) == digest else {
            throw PhotoFixtureError.invalid("fixture changed during isolation")
        }
        try check(deadline)
        report["finished_within_deadline"] = true
        #endif
    }

    enum AuthorizationAction: Equatable { case proceed, request, reject }
    nonisolated static func authorizationAction(_ status: PHAuthorizationStatus) -> AuthorizationAction {
        switch status {
        case .authorized: .proceed
        case .notDetermined: .request
        default: .reject
        }
    }

    nonisolated static func authorizationRequestCompleted(callbackRaw: Int?, after: PHAuthorizationStatus,
                                                          promptSeen: Bool, promptAccepted: Bool) -> Bool {
        callbackRaw == PHAuthorizationStatus.authorized.rawValue && after == .authorized
            && promptSeen == promptAccepted
    }

    nonisolated static func permitsAuthorizationPrompt(texts: [String], buttons: [String],
                                                       runnerName: String, usage: String, alertCount: Int) -> Bool {
        guard alertCount == 1, (2...8).contains(texts.count), (2...3).contains(buttons.count),
              Set(buttons).count == buttons.count, !runnerName.isEmpty, runnerName.utf8.count <= 128,
              !usage.isEmpty, usage.utf8.count <= 1024,
              texts.allSatisfy({ $0.utf8.count <= 1024 }), texts.joined(separator: "\n").utf8.count <= 2048,
              texts.filter({ $0 == usage }).count == 1,
              buttons.filter({ $0 == "Allow Full Access" }).count == 1,
              buttons.contains("Don’t Allow") || buttons.contains("Don't Allow") else { return false }
        let name = NSRegularExpression.escapedPattern(for: runnerName)
        let title = "^[“\"]" + name + "[”\"] Would Like (?:(?:Full )?Access to|to Access) (?:Your )?(?:Photos|Photo Library)$"
        return texts.filter({ $0.range(of: title, options: [.regularExpression, .caseInsensitive]) != nil }).count == 1
    }

    private static func authorize(deadline: ContinuousClock.Instant, usage: String, report: inout [String: Any]) throws {
        try check(deadline)
        let before = PHPhotoLibrary.authorizationStatus(for: .readWrite)
        var authorization: [String: Any] = ["before_raw": before.rawValue, "requested": false,
            "callback_raw": NSNull(), "prompt_seen": false, "prompt_accepted": false,
            "prompt_runner": "", "prompt_text": "", "prompt_button": ""]
        var callback: PhotoFixtureAuthorization?
        defer {
            authorization["after_raw"] = PHPhotoLibrary.authorizationStatus(for: .readWrite).rawValue
            if let raw = callback?.observedStatus() { authorization["callback_raw"] = raw }
            report["authorization"] = authorization
        }
        switch authorizationAction(before) {
        case .proceed: return
        case .reject: throw PhotoFixtureError.invalid("runner Photos read/write status \(before.rawValue)")
        case .request: break
        }
        let completed = PhotoFixtureAuthorization(deadline: deadline)
        callback = completed
        authorization["requested"] = true
        try check(deadline)
        // Return immediately; do not await on the main actor before interacting
        // with the permission sheet. Callback storage is independently locked.
        PHPhotoLibrary.requestAuthorization(for: .readWrite) { @Sendable status in
            if completed.complete(status) { completed.signal() }
        }
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let runnerName = (Bundle.main.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String)
            ?? (Bundle.main.object(forInfoDictionaryKey: "CFBundleName") as? String) ?? ""
        for _ in 0..<20 {
            try check(deadline)
            if completed.isFinished { break }
            let alert = springboard.alerts.firstMatch
            let remaining = min(1, duration(ContinuousClock().now.duration(to: deadline)))
            guard remaining > 0 else { throw PhotoFixtureError.invalid("authorization observation deadline") }
            let present = alert.waitForExistence(timeout: remaining)
            try check(deadline)
            if completed.isFinished { break }
            guard present else { continue }
            authorization["prompt_seen"] = true
            let alertCount = springboard.alerts.count
            try check(deadline)
            guard alertCount == 1 else {
                throw PhotoFixtureError.invalid("ambiguous Photos authorization prompt")
            }
            // Read one immutable hierarchy. Index-bound XCUIElement proxies
            // re-resolve against a live sheet and can outlive a transient child.
            let snapshot = try alert.snapshot()
            try check(deadline)
            var pending = Array(snapshot.children.reversed())
            var visited = 0
            var texts: [String] = []
            var buttons: [String] = []
            guard pending.count <= 64 else {
                throw PhotoFixtureError.invalid("Photos authorization snapshot node bound")
            }
            while let node = pending.popLast() {
                try check(deadline)
                visited += 1
                if node.elementType == .staticText || node.elementType == .button {
                    let label = node.label
                    guard label.utf8.count <= 1024 else {
                        throw PhotoFixtureError.invalid("Photos authorization snapshot label bound")
                    }
                    if node.elementType == .staticText { texts.append(label) }
                    else { buttons.append(label) }
                    guard texts.count <= 8, buttons.count <= 3 else {
                        throw PhotoFixtureError.invalid("ambiguous Photos authorization prompt")
                    }
                }
                let children = node.children
                guard children.count <= 64 - visited - pending.count else {
                    throw PhotoFixtureError.invalid("Photos authorization snapshot node bound")
                }
                pending.append(contentsOf: children.reversed())
            }
            try check(deadline)
            guard (2...8).contains(texts.count), (2...3).contains(buttons.count) else {
                throw PhotoFixtureError.invalid("ambiguous Photos authorization prompt")
            }
            guard permitsAuthorizationPrompt(texts: texts, buttons: buttons, runnerName: runnerName,
                                             usage: usage, alertCount: alertCount) else {
                throw PhotoFixtureError.invalid("Photos authorization prompt is not this runner's full-access request")
            }
            authorization["prompt_runner"] = runnerName
            authorization["prompt_text"] = texts.joined(separator: "\n")
            authorization["prompt_button"] = "Allow Full Access"
            let allow = alert.buttons["Allow Full Access"]
            guard allow.isEnabled else { throw PhotoFixtureError.invalid("Photos full-access control disabled") }
            try check(deadline)
            guard allow.isHittable else { throw PhotoFixtureError.invalid("Photos full-access control unreachable") }
            try check(deadline)
            allow.tap()
            try check(deadline)
            authorization["prompt_accepted"] = true
            break
        }
        try wait(completed.expectation, deadline: deadline)
        try completed.result()
        // The OS can honor an existing grant without presenting a prompt. The
        // callback and fresh readback prove authorization, not a UI interaction.
        guard authorizationRequestCompleted(callbackRaw: completed.observedStatus(),
              after: PHPhotoLibrary.authorizationStatus(for: .readWrite),
              promptSeen: authorization["prompt_seen"] as? Bool == true,
              promptAccepted: authorization["prompt_accepted"] as? Bool == true) else {
            throw PhotoFixtureError.invalid("runner full Photos authorization is unconfirmed")
        }
        try check(deadline)
    }

    private static func inventory(deadline: ContinuousClock.Instant) throws -> [PHAsset] {
        try check(deadline)
        guard PHPhotoLibrary.authorizationStatus(for: .readWrite) == .authorized else {
            throw PhotoFixtureError.invalid("Photos authorization changed")
        }
        let options = PHFetchOptions()
        options.fetchLimit = assetLimit + 1
        options.includeHiddenAssets = true
        options.includeAllBurstAssets = true
        let fetched = PHAsset.fetchAssets(with: options)
        try check(deadline)
        guard fetched.count > 0, fetched.count <= assetLimit else {
            throw PhotoFixtureError.invalid("empty or over-bound Photos inventory (\(fetched.count))")
        }
        let assets = (0..<fetched.count).map { fetched.object(at: $0) }
        let identifiers = assets.map(\.localIdentifier)
        guard Set(identifiers).count == assets.count,
              identifiers.allSatisfy({ !$0.isEmpty && $0.utf8.count <= 256 }),
              assets.allSatisfy({ $0.sourceType == .typeUserLibrary }) else {
            throw PhotoFixtureError.invalid("foreign, duplicate or malformed Photos assets")
        }
        try check(deadline)
        return assets
    }

    private static func fixtureResource(in assets: [PHAsset], deadline: ContinuousClock.Instant) throws -> (PHAsset, PHAssetResource) {
        var matches: [(PHAsset, PHAssetResource)] = []
        for asset in assets {
            try check(deadline)
            let resources = PHAssetResource.assetResources(for: asset)
            try check(deadline)
            guard resources.count <= 8 else { throw PhotoFixtureError.invalid("asset resource bound") }
            for resource in resources where resource.originalFilename == filename {
                guard asset.mediaType == .image, asset.pixelWidth == 1400, asset.pixelHeight == 1800,
                      resource.type == .photo, resource.assetLocalIdentifier == asset.localIdentifier else {
                    throw PhotoFixtureError.invalid("fixture resource identity differs")
                }
                matches.append((asset, resource))
            }
        }
        guard matches.count == 1 else { throw PhotoFixtureError.invalid("missing or duplicate named fixture") }
        return matches[0]
    }

    private static func read(_ resource: PHAssetResource, deadline: ContinuousClock.Instant) throws -> Data {
        try check(deadline)
        let received = PhotoFixtureRead(limit: bytes, deadline: deadline)
        let options = PHAssetResourceRequestOptions()
        options.isNetworkAccessAllowed = false
        let manager = PHAssetResourceManager.default()
        try check(deadline)
        let requestID = manager.requestData(for: resource, options: options, dataReceivedHandler: { @Sendable chunk in
            if received.receive(chunk) { received.signal() }
        }, completionHandler: { @Sendable error in
            if received.complete(error: error) { received.signal() }
        })
        defer { manager.cancelDataRequest(requestID) }
        try wait(received.expectation, deadline: deadline)
        return try received.result()
    }

    private static func remove(_ identifiers: [String], deadline: ContinuousClock.Instant, report: inout [String: Any]) throws {
        try check(deadline)
        let completed = PhotoFixtureRead(limit: 0, deadline: deadline)
        try check(deadline)
        PHPhotoLibrary.shared().performChanges({ @Sendable in
            // The framework schedules this block; admission is checked again here.
            guard ContinuousClock().now < deadline else {
                if completed.complete(error: PhotoFixtureError.invalid("change admission deadline")) { completed.signal() }
                return
            }
            let assets = PHAsset.fetchAssets(withLocalIdentifiers: identifiers, options: nil)
            guard assets.count == identifiers.count else {
                if completed.complete(error: PhotoFixtureError.invalid("removal count changed")) { completed.signal() }
                return
            }
            let observed = (0..<assets.count).map { assets.object(at: $0).localIdentifier }.sorted()
            guard observed == identifiers, ContinuousClock().now < deadline else {
                if completed.complete(error: PhotoFixtureError.invalid("removal inventory changed")) { completed.signal() }
                return
            }
            PHAssetChangeRequest.deleteAssets(assets)
        }, completionHandler: { @Sendable success, error in
            let failure: Error? = error ?? (success ? nil : PhotoFixtureError.invalid("Photos change failed"))
            if completed.complete(error: failure) { completed.signal() }
        })
        // PhotoKit can require separate per-change consent even with full access.
        // Observe only SpringBoard; never dismiss an unrelated system alert.
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let runnerName = (Bundle.main.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String)
            ?? (Bundle.main.object(forInfoDictionaryKey: "CFBundleName") as? String) ?? ""
        for _ in 0..<20 {
            try check(deadline)
            if completed.isFinished { break }
            let alert = springboard.alerts.firstMatch
            let timeout = min(1, duration(ContinuousClock().now.duration(to: deadline)))
            guard timeout > 0 else { throw PhotoFixtureError.invalid("confirmation observation deadline") }
            let present = alert.waitForExistence(timeout: timeout)
            try check(deadline)
            if completed.isFinished { break }
            guard present else { continue }
            report["confirmation_seen"] = true
            let alertCount = springboard.alerts.count
            try check(deadline)
            let textCount = alert.staticTexts.count
            try check(deadline)
            let buttonCount = alert.buttons.count
            try check(deadline)
            guard alertCount == 1, textCount <= 8, buttonCount == 2 else {
                throw PhotoFixtureError.invalid("unexpected Photos confirmation structure")
            }
            let text = alert.staticTexts.allElementsBoundByIndex.map(\.label).joined(separator: "\n")
            report["confirmation_text"] = String(text.prefix(512))
            try check(deadline)
            guard permitsConfirmation(text: text, runnerName: runnerName,
                                      runnerBundleID: Bundle.main.bundleIdentifier ?? "",
                                      removed: identifiers.count) else {
                throw PhotoFixtureError.invalid("Photos confirmation does not name this runner and removal count")
            }
            let deleteExists = alert.buttons["Delete"].exists
            try check(deadline)
            let cancelExists = alert.buttons["Cancel"].exists
            try check(deadline)
            let denyExists = alert.buttons["Don’t Allow"].exists
            try check(deadline)
            let asciiDenyExists = alert.buttons["Don't Allow"].exists
            try check(deadline)
            guard deleteExists, cancelExists || denyExists || asciiDenyExists else {
                throw PhotoFixtureError.invalid("Photos confirmation lacks Delete and a denial control")
            }
            report["confirmation_text"] = text
            try check(deadline)
            guard alert.buttons["Delete"].isHittable else { throw PhotoFixtureError.invalid("Photos confirmation unreachable") }
            try check(deadline)
            alert.buttons["Delete"].tap()
            try check(deadline)
            report["confirmation_accepted"] = true
            break
        }
        try wait(completed.expectation, deadline: deadline)
        _ = try completed.result()
    }

    nonisolated static func permitsConfirmation(text: String, runnerName: String,
                                                runnerBundleID: String, removed: Int) -> Bool {
        guard (1..<64).contains(removed), text.utf8.count <= 2048,
              runnerBundleID == "com.alvit.roominventory.uitests.xctrunner",
              runnerName == "RoomInventoryUITests-Runner" else { return false }
        // PhotoKit's deletion sheet on the admitted iOS 18.5 Simulator names the
        // XCTest carrier, while its full-access sheet names this actual runner.
        // This fixed alias is used only after isolate's owned-device, exact-runner,
        // authorization and unchanged fixture/asset-ID checks; it is not caller input.
        let noun = removed == 1 ? "photo" : "photos"
        var titles = Set(["\(runnerName) Would Like to Delete \(removed) \(noun.capitalized)"])
        for name in [runnerName, "com.apple.XCTRunner"] {
            titles.insert("Allow “\(name)” to delete \(removed) \(noun)?")
            titles.insert("Allow \"\(name)\" to delete \(removed) \(noun)?")
        }
        let lines = text.components(separatedBy: "\n")
        guard (1...8).contains(lines.count), let title = lines.first, titles.contains(title) else { return false }
        return lines.filter { titles.contains($0) }.count == 1
    }

    private static func wait(_ expectation: XCTestExpectation, deadline: ContinuousClock.Instant) throws {
        try check(deadline)
        let remaining = duration(ContinuousClock().now.duration(to: deadline))
        guard remaining > 0, XCTWaiter.wait(for: [expectation], timeout: remaining) == .completed else {
            throw PhotoFixtureError.invalid("PhotoKit callback did not finish before isolation deadline")
        }
        try check(deadline)
    }

    private static func check(_ deadline: ContinuousClock.Instant) throws {
        guard ContinuousClock().now < deadline else { throw PhotoFixtureError.invalid("isolation deadline") }
    }
    private static func duration(_ value: Duration) -> Double {
        let parts = value.components
        return Double(parts.seconds) + Double(parts.attoseconds) / 1e18
    }
    private static func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    private static func idsDigest(_ ids: [String]) -> String { hash(Data(ids.joined(separator: "\n").utf8)) }
}
