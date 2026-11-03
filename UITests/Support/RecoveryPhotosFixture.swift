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

/// One change request and one terminal outcome, including delayed framework callbacks.
/// The request block and completion handler run on PhotoKit's serial queue.
final class PhotoFixtureSeedChange: @unchecked Sendable {
    private let lock = NSLock()
    private let deadline: ContinuousClock.Instant
    private let completion: PhotoFixtureRead
    private var attempts = 0
    private var identifier: String?
    var expectation: XCTestExpectation { completion.expectation }

    init(deadline: ContinuousClock.Instant) {
        self.deadline = deadline
        completion = PhotoFixtureRead(limit: 0, deadline: deadline)
    }

    func admit(at now: ContinuousClock.Instant = ContinuousClock().now) -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard !completion.isFinished else { return false }
        guard now < deadline, attempts == 0 else {
            finish(error: PhotoFixtureError.invalid("seed request late or repeated"), at: now)
            return false
        }
        attempts = 1
        return true
    }

    func created(_ value: String?, at now: ContinuousClock.Instant = ContinuousClock().now) {
        lock.lock(); defer { lock.unlock() }
        guard !completion.isFinished else { return }
        guard now < deadline, attempts == 1, identifier == nil,
              let value, Self.validIdentifier(value) else {
            finish(error: PhotoFixtureError.invalid("seed placeholder missing, repeated or late"), at: now)
            return
        }
        identifier = value
    }

    func fail(_ error: Error, at now: ContinuousClock.Instant = ContinuousClock().now) {
        lock.lock(); defer { lock.unlock() }
        finish(error: error, at: now)
    }

    func complete(success: Bool, error: Error?, at now: ContinuousClock.Instant = ContinuousClock().now) {
        lock.lock(); defer { lock.unlock() }
        let failure = error ?? (success && attempts == 1 && identifier != nil ? nil
            : PhotoFixtureError.invalid("seed change or placeholder unconfirmed"))
        finish(error: failure, at: now)
    }

    var mutationAttempts: Int { lock.lock(); defer { lock.unlock() }; return attempts }

    func result() throws -> String {
        lock.lock(); defer { lock.unlock() }
        _ = try completion.result()
        guard let identifier else { throw PhotoFixtureError.invalid("seed placeholder missing") }
        return identifier
    }

    private func finish(error: Error?, at now: ContinuousClock.Instant) {
        if completion.complete(error: error, at: now) { completion.signal() }
    }

    static func validIdentifier(_ value: String) -> Bool {
        !value.isEmpty && value.utf8.count <= 256 && !value.unicodeScalars.contains { $0.value < 32 }
    }
}

@MainActor
final class RecoveryPhotosFixture {
    nonisolated static let filename = "SyntheticRecoveryReceipt.png"
    nonisolated static let bundleFilename = "SyntheticRecoveryReceipt.data"
    nonisolated static let bytes = 74_736
    nonisolated static let digest = "3be0a311997c35182f58e2658f64afe06b437665dfb420f1dc595e23e24ea181"
    static let seconds = 20.0
    static let seedSeconds = 86.0
    private nonisolated static let assetLimit = 64

    static func seed(deviceID: String, report: inout [String: Any]) throws -> String {
        let clock = ContinuousClock()
        let started = clock.now
        let deadline = started.advanced(by: .seconds(seedSeconds))
        defer { report["elapsed_seconds"] = duration(started.duration(to: clock.now)) }
        #if !targetEnvironment(simulator)
        throw PhotoFixtureError.invalid("physical device is forbidden")
        #else
        let usage = try validateRunner(deviceID: deviceID)
        // Authorization retains its existing twenty-second ceiling inside this
        // nonrenewable seed window. A pregrant is not authorization proof.
        try authorize(deadline: min(deadline, clock.now.advanced(by: .seconds(seconds))),
                      usage: usage, report: &report)
        report["read_write_authorized"] = true
        let original = try bundledData(deadline: deadline)
        report["before_bytes"] = original.count
        report["before_sha256"] = hash(original)
        let before = try inventory(deadline: deadline, allowEmpty: true)
        let beforeIDs = before.map(\.localIdentifier).sorted()
        let existing = try namedFixtureCount(in: before, deadline: deadline)
        report["initial_asset_count"] = before.count
        report["initial_asset_ids"] = beforeIDs
        report["initial_asset_ids_sha256"] = idsDigest(beforeIDs)
        report["existing_fixture_count"] = existing
        guard permitsSeed(initialIDs: beforeIDs, existingFixtureCount: existing) else {
            throw PhotoFixtureError.invalid("preexisting fixture or over-bound seed inventory")
        }
        let change = PhotoFixtureSeedChange(deadline: deadline)
        report["change_requested"] = false
        report["change_completed"] = false
        defer { report["mutation_attempts"] = change.mutationAttempts }
        try check(deadline)
        PHPhotoLibrary.shared().performChanges({ @Sendable in
            do {
                // Do not let queued execution or a changed library authorize a
                // late or second creation. No PHAsset crosses queue boundaries.
                let current = try inventory(deadline: deadline, allowEmpty: true)
                guard current.map(\.localIdentifier).sorted() == beforeIDs,
                      try namedFixtureCount(in: current, deadline: deadline) == 0 else {
                    throw PhotoFixtureError.invalid("Photos inventory changed before seed admission")
                }
                guard change.admit() else { return }
                let request = PHAssetCreationRequest.forAsset()
                let options = PHAssetResourceCreationOptions()
                options.originalFilename = filename
                options.uniformTypeIdentifier = "public.png"
                request.addResource(with: .photo, data: original, options: options)
                change.created(request.placeholderForCreatedAsset?.localIdentifier)
            } catch {
                change.fail(error)
            }
        }, completionHandler: { @Sendable success, error in
            change.complete(success: success, error: error)
        })
        report["change_requested"] = true
        try wait(change.expectation, deadline: deadline)
        let createdID = try change.result()
        report["change_completed"] = true
        report["created_asset_id"] = createdID
        let after = try inventory(deadline: deadline)
        let afterIDs = after.map(\.localIdentifier).sorted()
        report["final_asset_count"] = after.count
        report["final_asset_ids"] = afterIDs
        report["final_asset_ids_sha256"] = idsDigest(afterIDs)
        guard confirmsSeed(initialIDs: beforeIDs, finalIDs: afterIDs, createdID: createdID) else {
            throw PhotoFixtureError.invalid("seed did not add exactly the placeholder asset")
        }
        let (asset, resource) = try fixtureResource(in: after, deadline: deadline)
        guard asset.localIdentifier == createdID else { throw PhotoFixtureError.invalid("created fixture identity differs") }
        let stored = try read(resource, deadline: deadline)
        report["after_bytes"] = stored.count
        report["after_sha256"] = hash(stored)
        guard acceptsOriginal(stored) else { throw PhotoFixtureError.invalid("created original bytes or hash differ") }
        try check(deadline)
        report["finished_within_deadline"] = true
        return createdID
        #endif
    }

    nonisolated static func permitsSeed(initialIDs: [String], existingFixtureCount: Int) -> Bool {
        initialIDs.count < assetLimit && Set(initialIDs).count == initialIDs.count
            && initialIDs.allSatisfy(PhotoFixtureSeedChange.validIdentifier) && existingFixtureCount == 0
    }

    nonisolated static func confirmsSeed(initialIDs: [String], finalIDs: [String], createdID: String) -> Bool {
        permitsSeed(initialIDs: initialIDs, existingFixtureCount: 0)
            && PhotoFixtureSeedChange.validIdentifier(createdID) && !initialIDs.contains(createdID)
            && finalIDs.count == initialIDs.count + 1 && Set(finalIDs).count == finalIDs.count
            && Set(finalIDs) == Set(initialIDs + [createdID])
    }

    nonisolated static func acceptsOriginal(_ data: Data) -> Bool { data.count == bytes && hash(data) == digest }

    static func isolate(deviceID: String, createdID: String, expectedAssetIDs: [String], report: inout [String: Any]) throws {
        let clock = ContinuousClock()
        let started = clock.now
        let deadline = started.advanced(by: .seconds(seconds))
        defer { report["elapsed_seconds"] = duration(started.duration(to: clock.now)) }
        #if !targetEnvironment(simulator)
        throw PhotoFixtureError.invalid("physical device is forbidden")
        #else
        let usage = try validateRunner(deviceID: deviceID)
        try authorize(deadline: deadline, usage: usage, report: &report)
        report["read_write_authorized"] = true
        let before = try inventory(deadline: deadline)
        report["initial_asset_count"] = before.count
        let beforeIDs = before.map(\.localIdentifier).sorted()
        report["initial_asset_ids_sha256"] = idsDigest(beforeIDs)
        guard beforeIDs == expectedAssetIDs else {
            throw PhotoFixtureError.invalid("Photos inventory changed between seed and isolation")
        }
        let (fixture, resource) = try fixtureResource(in: before, deadline: deadline)
        guard fixture.localIdentifier == createdID else {
            throw PhotoFixtureError.invalid("isolation fixture is not this run's created asset")
        }
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

    private static func validateRunner(deviceID: String) throws -> String {
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
        return usage
    }

    private static func bundledData(deadline: ContinuousClock.Instant) throws -> Data {
        try check(deadline)
        guard let url = Bundle(for: RecoveryPhotosFixture.self).url(forResource: "SyntheticRecoveryReceipt", withExtension: "data") else {
            throw PhotoFixtureError.invalid("raw bundled fixture missing")
        }
        let values = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true, values.fileSize == bytes else {
            throw PhotoFixtureError.invalid("raw bundled fixture is not the exact bounded regular file")
        }
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var data = Data()
        while data.count <= bytes {
            try check(deadline)
            let chunk = try handle.read(upToCount: bytes + 1 - data.count) ?? Data()
            if chunk.isEmpty { break }
            data.append(chunk)
        }
        try check(deadline)
        guard acceptsOriginal(data) else { throw PhotoFixtureError.invalid("raw bundled fixture bytes or hash differ") }
        return data
    }

    private nonisolated static func namedFixtureCount(in assets: [PHAsset], deadline: ContinuousClock.Instant) throws -> Int {
        var count = 0
        for asset in assets {
            try check(deadline)
            let resources = PHAssetResource.assetResources(for: asset)
            try check(deadline)
            guard resources.count <= 8 else { throw PhotoFixtureError.invalid("asset resource bound") }
            count += resources.filter { $0.originalFilename == filename }.count
        }
        return count
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
        let title = "^[“\"]" + name + "[”\"] Would Like (?:(?:Full )?Access to|to Access) (?:Your )?(?:Photos|Photo Library)\\.?$"
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

    private nonisolated static func inventory(deadline: ContinuousClock.Instant, allowEmpty: Bool = false) throws -> [PHAsset] {
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
        guard (allowEmpty || fetched.count > 0), fetched.count <= assetLimit else {
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

    private nonisolated static func check(_ deadline: ContinuousClock.Instant) throws {
        guard ContinuousClock().now < deadline else { throw PhotoFixtureError.invalid("isolation deadline") }
    }
    private static func duration(_ value: Duration) -> Double {
        let parts = value.components
        return Double(parts.seconds) + Double(parts.attoseconds) / 1e18
    }
    private nonisolated static func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    private static func idsDigest(_ ids: [String]) -> String { hash(Data(ids.joined(separator: "\n").utf8)) }
}
