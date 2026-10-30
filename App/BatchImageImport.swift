import Foundation
import Observation

enum BatchImageImportError: LocalizedError {
    case busy, emptySelection, tooManyImages(Int), duplicateSelection, proRequired, saveFailed(String)

    var errorDescription: String? {
        switch self {
        case .busy: ServiceL10n.text("batch.busy")
        case .emptySelection: ServiceL10n.text("batch.empty")
        case .tooManyImages(let limit): ServiceL10n.plural("batch.tooMany", count: limit)
        case .duplicateSelection: ServiceL10n.text("batch.duplicate")
        case .proRequired: ServiceL10n.text("batch.proRequired")
        case .saveFailed(let message): message
        }
    }
}

/// Processes one payload at a time. A failed retry never repeats a completed save.
@MainActor @Observable
final class BatchImageImport {
    static let maximumSelectionCount = 10

    struct Payload: Sendable {
        let data: Data
        let originalName: String?
    }

    struct Source: Identifiable {
        let id: UUID
        let name: String
        let load: @MainActor () async throws -> Payload

        init(id: UUID = UUID(), name: String, load: @escaping @MainActor () async throws -> Payload) {
            self.id = id
            self.name = name
            self.load = load
        }
    }

    enum Status: Equatable {
        case waiting, importing, saved, failed(String)
    }

    struct Entry: Identifiable {
        let id: UUID
        let name: String
        var status: Status
    }

    private(set) var entries: [Entry] = []
    private(set) var isRunning = false
    @ObservationIgnored private var sources: [Source] = []

    var savedCount: Int { entries.filter { $0.status == .saved }.count }
    var failedCount: Int { entries.filter { if case .failed = $0.status { return true }; return false }.count }
    var completedCount: Int { savedCount + failedCount }
    var currentName: String? { entries.first { $0.status == .importing }?.name }

    func start(_ selection: [Source], isPro: @MainActor () -> Bool,
               prepare: @MainActor (Payload) async throws -> Void = { _ in },
               save: @MainActor (Payload) async throws -> Void) async throws {
        guard !isRunning else { throw BatchImageImportError.busy }
        let limit = isPro() ? Self.maximumSelectionCount : 1
        guard !selection.isEmpty else { throw BatchImageImportError.emptySelection }
        guard selection.count <= limit else { throw BatchImageImportError.tooManyImages(limit) }
        guard Set(selection.map(\.id)).count == selection.count else { throw BatchImageImportError.duplicateSelection }
        sources = selection
        entries = selection.map { Entry(id: $0.id, name: $0.name, status: .waiting) }
        await process(indices: Array(entries.indices), isPro: isPro, prepare: prepare, save: save)
    }

    func retryFailed(isPro: @MainActor () -> Bool,
                     prepare: @MainActor (Payload) async throws -> Void = { _ in },
                     save: @MainActor (Payload) async throws -> Void) async throws {
        guard !isRunning else { throw BatchImageImportError.busy }
        let indices = entries.indices.filter { if case .failed = entries[$0].status { return true }; return false }
        for index in indices { entries[index].status = .waiting }
        await process(indices: indices, isPro: isPro, prepare: prepare, save: save)
    }

    func reset() {
        guard !isRunning else { return }
        sources = []
        entries = []
    }

    private func process(indices: [Int], isPro: @MainActor () -> Bool,
                         prepare: @MainActor (Payload) async throws -> Void,
                         save: @MainActor (Payload) async throws -> Void) async {
        isRunning = true
        defer { isRunning = false }
        for index in indices {
            entries[index].status = .importing
            do {
                try Task.checkCancellation()
                guard sources.count == 1 || isPro() else { throw BatchImageImportError.proRequired }
                let payload = try await sources[index].load()
                try Task.checkCancellation()
                guard sources.count == 1 || isPro() else { throw BatchImageImportError.proRequired }
                // Preparation may suspend for decoding. Recheck before entering
                // the atomic save, which must finish even if cancelled later.
                try await prepare(payload)
                try Task.checkCancellation()
                guard sources.count == 1 || isPro() else { throw BatchImageImportError.proRequired }
                try await save(payload)
                // Once save returns successfully, cancellation cannot undo it.
                entries[index].status = .saved
            } catch {
                entries[index].status = .failed(error is CancellationError ? ServiceL10n.text("batch.interrupted") : error.localizedDescription)
            }
        }
    }
}
