import Darwin
import Foundation

/// Publishes complete runner messages without replacing an existing destination.
enum RecoveryBridgePublication {
    static func publish(_ data: Data, at destination: URL, nonce: String) throws {
        let temporary = destination.deletingLastPathComponent()
            .appendingPathComponent("." + destination.lastPathComponent + "." + nonce + ".tmp")
        // Do not remove an existing temporary file if exclusive creation fails.
        try data.write(to: temporary, options: [.withoutOverwriting])
        let failure: Int32? = temporary.path.withCString { source in
            destination.path.withCString { target in
                Darwin.renamex_np(source, target, UInt32(RENAME_EXCL)) == 0 ? nil : errno
            }
        }
        if let failure {
            // Only this call's completed temporary file belongs to this cleanup.
            // There is no overwrite fallback or publication retry.
            try? FileManager.default.removeItem(at: temporary)
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(failure))
        }
        // Exclusive rename removes the temporary name in the same operation.
        // No later unlink changes the published inode's link count or ctime.
    }
}
