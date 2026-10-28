import CryptoKit
import Darwin
import Foundation
import XCTest

/// Coordination files belong only to the UI-test runner. The host captures
/// exports while the UI is paused; this helper never opens the app's container.
@MainActor
final class RecoveryJourneyBridge {
    enum Role: String { case sourceZIP = "source_zip", backup, targetZIP = "target_zip" }
    enum Phase: String { case before, after }

    private let journeyID: String
    private let sourceID: String
    private let targetID: String
    private let deviceID: String
    private let directory: URL
    private var completedBarriers = 0
    private var installationAcknowledged = false
    private var installationRequestSHA: String?
    private var photosIsolationAttempted = false
    private var photosIsolated = false

    init(journeyID: String, sourceID: String, targetID: String, deviceID: String) throws {
        guard Bundle.main.bundleIdentifier == "com.alvit.roominventory.uitests.xctrunner" else {
            throw BridgeError.invalid("not the UI-test runner")
        }
        let identifiers = [journeyID, sourceID, targetID]
        guard identifiers.allSatisfy({ UUID(uuidString: $0)?.uuidString == $0 }),
              Set(identifiers).count == 3 else {
            throw BridgeError.invalid("noncanonical or repeated run identifier")
        }
        guard UUID(uuidString: deviceID)?.uuidString == deviceID else {
            throw BridgeError.invalid("noncanonical owned device identifier")
        }
        self.deviceID = deviceID
        self.journeyID = journeyID
        self.sourceID = sourceID
        self.targetID = targetID
        let files = FileManager.default
        // No environment variable or caller-supplied filesystem path is used.
        let documents = try files.url(for: .documentDirectory, in: .userDomainMask,
                                      appropriateFor: nil, create: true)
        let root = documents.appendingPathComponent("RecoveryJourneyBridge", isDirectory: true)
        if try Self.entryType(root) == nil {
            try files.createDirectory(at: root, withIntermediateDirectories: false)
        }
        guard try Self.entryType(root) == .typeDirectory else {
            throw BridgeError.invalid("bridge root is not a directory")
        }
        directory = root.appendingPathComponent(journeyID, isDirectory: true)
        // Reusing a journey directory could consume an old host acknowledgement.
        guard try Self.entryType(directory) == nil else {
            throw BridgeError.invalid("journey directory already exists")
        }
        try files.createDirectory(at: directory, withIntermediateDirectories: false)
    }

    func synchronizeInstallation(test: XCTestCase) throws {
        guard !installationAcknowledged, completedBarriers == 0 else {
            throw BridgeError.invalid("installation handshake already consumed")
        }
        let requestURL = directory.appendingPathComponent("installation-request.json")
        let acknowledgementURL = directory.appendingPathComponent("installation-ack.json")
        guard try Self.entryType(requestURL) == nil,
              try Self.entryType(acknowledgementURL) == nil else {
            throw BridgeError.invalid("installation handshake file already exists")
        }
        let nonce = UUID().uuidString
        let request: [String: Any] = [
            "schema_version": 1, "journey_run_id": journeyID,
            "source_run_id": sourceID, "target_run_id": targetID,
            "simulator_udid": deviceID, "phase": "installation", "nonce": nonce,
            "app_bundle_id": "com.alvit.roominventory",
            "runner_bundle_id": "com.alvit.roominventory.uitests.xctrunner"
        ]
        let requestData = try JSONSerialization.data(withJSONObject: request, options: [.sortedKeys])
        try Self.publish(requestData, at: requestURL, nonce: nonce)
        Self.attach(requestData, name: "recovery-installation-request.json", test: test)
        // This uses the existing finite ACK wait inside the unchanged XCTest
        // execution allowance; no controller phase deadline is extended.
        try waitForAcknowledgement(request: request, requestData: requestData,
                                   requestURL: requestURL, acknowledgementURL: acknowledgementURL,
                                   attachmentName: "recovery-installation-ack.json", test: test)
        installationRequestSHA = SHA256.hash(data: requestData).map { String(format: "%02x", $0) }.joined()
        installationAcknowledged = true
    }

    func isolatePhotosFixture(test: XCTestCase) throws {
        guard installationAcknowledged, !photosIsolationAttempted, completedBarriers == 0,
              let installationRequestSHA else {
            throw BridgeError.invalid("Photos isolation requires this owned installation acknowledgement exactly once")
        }
        photosIsolationAttempted = true
        let receiptURL = directory.appendingPathComponent("photos-isolation.json")
        guard try Self.entryType(receiptURL) == nil else { throw BridgeError.invalid("Photos receipt already exists") }
        var receipt: [String: Any] = [
            "schema_version": 1, "phase": "photos_isolation", "status": "failed",
            "journey_run_id": journeyID, "source_run_id": sourceID, "target_run_id": targetID,
            "simulator_udid": deviceID, "runner_bundle_id": "com.alvit.roominventory.uitests.xctrunner",
            "installation_request_sha256": installationRequestSHA,
            "fixture_filename": RecoveryPhotosFixture.filename, "fixture_bytes": RecoveryPhotosFixture.bytes,
            "fixture_sha256": RecoveryPhotosFixture.digest, "deadline_seconds": RecoveryPhotosFixture.seconds
        ]
        var primary: Error?
        do {
            try RecoveryPhotosFixture.isolate(deviceID: deviceID, report: &receipt)
            receipt["status"] = "passed"
        } catch {
            primary = error
            receipt["error"] = String(String(describing: error).prefix(512))
        }
        do {
            let data = try JSONSerialization.data(withJSONObject: receipt, options: [.sortedKeys])
            guard data.count <= 16_384 else { throw BridgeError.invalid("Photos receipt byte bound") }
            try Self.publish(data, at: receiptURL, nonce: UUID().uuidString)
            Self.attach(data, name: "recovery-photos-isolation.json", test: test)
        } catch {
            throw BridgeError.invalid("Photos isolation: \(String(describing: primary)); receipt publication: \(error)")
        }
        if let primary { throw primary }
        photosIsolated = true
    }

    func synchronize(role: Role, phase: Phase, test: XCTestCase) throws {
        guard installationAcknowledged, photosIsolated else {
            throw BridgeError.invalid("installation handshake or Photos isolation missing")
        }
        let sequence = completedBarriers + 1
        let roles: [Role] = [.sourceZIP, .sourceZIP, .backup, .backup, .targetZIP, .targetZIP]
        guard sequence <= roles.count, roles[sequence - 1] == role,
              phase == (sequence.isMultiple(of: 2) ? .after : .before) else {
            throw BridgeError.invalid("barrier order")
        }
        guard try Self.entryType(directory.deletingLastPathComponent()) == .typeDirectory,
              try Self.entryType(directory) == .typeDirectory else {
            throw BridgeError.invalid("bridge directory changed")
        }
        let suffix = String(format: "%02d.json", sequence)
        let requestURL = directory.appendingPathComponent("request-" + suffix)
        let acknowledgementURL = directory.appendingPathComponent("ack-" + suffix)
        guard try Self.entryType(requestURL) == nil,
              try Self.entryType(acknowledgementURL) == nil else {
            throw BridgeError.invalid("barrier file already exists")
        }
        let nonce = UUID().uuidString
        let request: [String: Any] = [
            "schema_version": 1, "journey_run_id": journeyID,
            "source_run_id": sourceID, "target_run_id": targetID,
            "sequence": sequence, "role": role.rawValue, "phase": phase.rawValue, "nonce": nonce
        ]
        let requestData = try JSONSerialization.data(withJSONObject: request, options: [.sortedKeys])
        try Self.publish(requestData, at: requestURL, nonce: nonce)
        Self.attach(requestData, name: "recovery-bridge-request-" + suffix, test: test)

        try waitForAcknowledgement(request: request, requestData: requestData,
                                   requestURL: requestURL, acknowledgementURL: acknowledgementURL,
                                   attachmentName: "recovery-bridge-ack-" + suffix, test: test)
        completedBarriers = sequence
    }

    func requireComplete() throws {
        guard installationAcknowledged, photosIsolated, completedBarriers == 6 else {
            throw BridgeError.invalid("incomplete host capture")
        }
    }

    private func waitForAcknowledgement(
        request: [String: Any], requestData: Data, requestURL: URL,
        acknowledgementURL: URL, attachmentName: String, test: XCTestCase
    ) throws {
        // A condition wait, not an arbitrary sleep. The host publishes ACKs
        // atomically only after durable capture; malformed ACKs fail immediately.
        let arrived = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            // attributesOfItem uses lstat, so even a dangling symlink wakes the
            // wait and is rejected by the no-follow reader below.
            do { return try Self.entryType(acknowledgementURL) != nil }
            catch { return true }
        }, object: nil)
        guard XCTWaiter.wait(for: [arrived], timeout: 20) == .completed else {
            throw BridgeError.invalid("host acknowledgement timed out")
        }
        let acknowledgementData = try Self.readRegularFile(acknowledgementURL)
        Self.attach(acknowledgementData, name: attachmentName, test: test)
        var expected = request
        expected["request_sha256"] = SHA256.hash(data: requestData).map { String(format: "%02x", $0) }.joined()
        expected["success"] = true
        let expectedData = try JSONSerialization.data(withJSONObject: expected, options: [.sortedKeys])
        // Wire format: sorted keys, compact UTF-8, optional single trailing LF.
        // Exact bytes also reject duplicate/unknown keys, escaped alternatives,
        // wrong JSON types and a truthy value in place of the boolean true.
        let canonicalData = acknowledgementData.last == 0x0A
            ? Data(acknowledgementData.dropLast()) : acknowledgementData
        guard canonicalData == expectedData else {
            throw BridgeError.invalid("host acknowledgement does not bind this request")
        }
        guard try Self.readRegularFile(requestURL) == requestData else {
            throw BridgeError.invalid("request changed during host capture")
        }
    }

    private nonisolated static func entryType(_ url: URL) throws -> FileAttributeType? {
        do {
            let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
            guard let type = attributes[.type] as? FileAttributeType else {
                throw BridgeError.invalid("missing filesystem entry type")
            }
            return type
        } catch let error as NSError where error.domain == NSCocoaErrorDomain &&
            [NSFileNoSuchFileError, NSFileReadNoSuchFileError].contains(error.code) {
            return nil
        } catch {
            throw BridgeError.invalid("cannot inspect bridge entry")
        }
    }

    private static func publish(_ data: Data, at destination: URL, nonce: String) throws {
        let temporary = destination.deletingLastPathComponent()
            .appendingPathComponent("." + destination.lastPathComponent + "." + nonce + ".tmp")
        // A hard link publishes complete bytes atomically and fails if the final
        // name exists. Renaming or an atomic overwrite would permit stale reuse.
        try data.write(to: temporary, options: [.withoutOverwriting])
        defer { try? FileManager.default.removeItem(at: temporary) }
        do { try FileManager.default.linkItem(at: temporary, to: destination) }
        catch { throw BridgeError.invalid("cannot publish a new request") }
    }

    private static func readRegularFile(_ url: URL) throws -> Data {
        let descriptor = url.path.withCString { Darwin.open($0, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC) }
        guard descriptor >= 0 else { throw BridgeError.invalid("cannot open acknowledgement or request") }
        defer { Darwin.close(descriptor) }
        var metadata = stat()
        guard Darwin.fstat(descriptor, &metadata) == 0,
              (metadata.st_mode & mode_t(S_IFMT)) == mode_t(S_IFREG),
              metadata.st_size > 0, metadata.st_size <= 16_384 else {
            throw BridgeError.invalid("bridge file is not a bounded regular file")
        }
        var result = Data()
        var buffer = [UInt8](repeating: 0, count: 4_096)
        var interruptedReads = 0
        while result.count <= 16_384 {
            let count = buffer.withUnsafeMutableBytes { Darwin.read(descriptor, $0.baseAddress, $0.count) }
            if count == 0 { break }
            if count < 0 {
                if errno == EINTR && interruptedReads < 8 {
                    interruptedReads += 1
                    continue
                }
                throw BridgeError.invalid("cannot read bridge file")
            }
            result.append(contentsOf: buffer.prefix(count))
        }
        guard result.count == metadata.st_size, result.count <= 16_384 else {
            throw BridgeError.invalid("bridge file changed size or exceeded limit")
        }
        return result
    }

    private static func attach(_ data: Data, name: String, test: XCTestCase) {
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = name
        attachment.lifetime = .keepAlways
        test.add(attachment)
    }
}

private enum BridgeError: Error, CustomStringConvertible {
    case invalid(String)

    var description: String {
        switch self { case let .invalid(reason): "Recovery runner bridge: \(reason)" }
    }
}
