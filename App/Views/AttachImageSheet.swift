import SwiftUI
import UIKit
import PhotosUI
import UniformTypeIdentifiers
import AVFoundation
import ImageIO
import InventoryCore

struct AttachImageSheet: View {
    let homeID: UUID
    let roomID: UUID
    let itemID: UUID
    let onImported: (InventoryAttachment) -> Void
    @Environment(InventoryStore.self) private var store
    @Environment(ProStore.self) private var pro
    @Environment(\.dismiss) private var dismiss
    @State private var kind: AttachmentKind = .photo
    @State private var selectedPhotos: [PhotosPickerItem] = []
    @State private var batch = BatchImageImport()
    @State private var importKind: AttachmentKind = .photo
    @State private var singleSelection = false
    @State private var singleAttachment: InventoryAttachment?
    @State private var importingFile = false
    @State private var showingCamera = false
    @State private var showingPro = false
    @State private var errorMessage: String?
    @State private var importTask: Task<Void, Never>?

    var body: some View {
        NavigationStack {
            Form {
                if batch.entries.isEmpty { Section {
                    Picker(UIL10n.text("File purpose"), selection: $kind) {
                        Text(UIL10n.text("Item photo")).tag(AttachmentKind.photo)
                        Text(UIL10n.text("Model / serial label")).tag(AttachmentKind.label)
                        Text(UIL10n.text("Receipt")).tag(AttachmentKind.receipt)
                    }
                    .accessibilityIdentifier("import.purpose")
                } header: { Text(UIL10n.text("What are you adding?")) } footer: {
                    Text(kind == .photo ? UIL10n.text("Photograph the whole item so it is easy to identify later.") : UIL10n.text("Fill the frame with clear, well-lit text. A single image opens text review after saving. For a batch, open each saved image to recognize its text."))
                }
                Section {
                    Button(UIL10n.text("Take a photo"), systemImage: "camera") { requestCamera() }
                    PhotosPicker(selection: $selectedPhotos, maxSelectionCount: pro.isPro ? BatchImageImport.maximumSelectionCount : 1,
                                 matching: .images, preferredItemEncoding: .current, photoLibrary: .shared()) {
                        Label(UIL10n.text("Choose from Photos"), systemImage: "photo.on.rectangle")
                    }
                    .accessibilityHint(pro.isPro ? UIL10n.text("Select up to 10 images for this item.") : UIL10n.text("Select one image for this item."))
                    .accessibilityIdentifier("import.photos")
                    Button(pro.isPro ? UIL10n.text("Import images from Files") : UIL10n.text("Import image from Files"), systemImage: "folder") { importingFile = true }
                } footer: {
                    Text(UIL10n.text("JPEG, PNG, or HEIC images up to 20 MB and 64 megapixels, with each side no longer than 16,384 pixels. Imported bytes are kept with this item and included in backups. Camera photos are saved as JPEGs. Photograph PDF receipts or import an image of the receipt."))
                }
                Section {
                    if pro.isPro {
                        Label(UIL10n.text("Import up to 10 images together"), systemImage: "photo.stack")
                        Text(UIL10n.text("All selected images use the chosen purpose and belong to this item. They are saved one at a time; the inventory's 80 MiB original-file limit still applies."))
                            .font(.footnote).foregroundStyle(.secondary)
                    } else {
                        Text(UIL10n.text("Free imports one image at a time. Pro can import up to 10 images together for one item."))
                        Button(UIL10n.text("Explore Pro batch import"), systemImage: "sparkles") { showingPro = true }
                            .accessibilityIdentifier("import.explorePro")
                    }
                }
                .disabled(batch.isRunning || store.isBusy)
                }
                if !batch.entries.isEmpty {
                    Section {
                        if batch.isRunning {
                            ProgressView(value: Double(batch.completedCount), total: Double(batch.entries.count)) {
                                Text(UIL10n.format("import.progress", UIL10n.number(batch.completedCount + 1), UIL10n.number(batch.entries.count)))
                            }
                            if let current = batch.currentName { Text(current).font(.caption).foregroundStyle(.secondary) }
                        } else {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(UIL10n.count("count.saved", batch.savedCount))
                                Text(UIL10n.count("count.failed", batch.failedCount))
                            }.font(.headline)
                                .accessibilityElement(children: .combine)
                                .accessibilityIdentifier("import.result")
                        }
                        ForEach(batch.entries) { entry in
                            VStack(alignment: .leading, spacing: 4) {
                                Text(entry.name).font(.subheadline)
                                statusLabel(entry.status).font(.caption)
                            }.accessibilityElement(children: .combine)
                        }
                    } header: { Text(UIL10n.text("Import results")) } footer: {
                        Text(UIL10n.text("Saved images remain attached even if another image fails. Open an individual saved image to recognize and review its text; batch import does not apply OCR values."))
                    }
                    if !batch.isRunning {
                        Section {
                            if batch.failedCount > 0 {
                                Button(UIL10n.text("Retry failed images only"), systemImage: "arrow.clockwise") { retryFailures() }
                                    .disabled(store.isBusy || (!pro.isPro && !singleSelection))
                                    .accessibilityIdentifier("import.retryFailed")
                                if !pro.isPro && !singleSelection {
                                    Text(UIL10n.text("Pro access is needed to retry a batch. Saved images remain available; import remaining images one at a time or restore Pro."))
                                        .font(.footnote).foregroundStyle(.secondary)
                                }
                            }
                            Button(UIL10n.text("Choose more images"), systemImage: "plus") {
                                batch.reset(); errorMessage = nil; singleAttachment = nil
                            }.disabled(store.isBusy)
                        }
                    }
                }
                if let errorMessage { Section { Label(errorMessage, systemImage: "exclamationmark.triangle").foregroundStyle(.red) } }
            }
            .disabled(store.isBusy && !batch.isRunning)
            .navigationTitle(UIL10n.text("Add a file")).navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) {
                Button(batch.entries.isEmpty ? UIL10n.text("Cancel") : UIL10n.text("Done")) { dismiss() }.disabled(batch.isRunning)
            } }
            .interactiveDismissDisabled(batch.isRunning)
            .onChange(of: selectedPhotos) { _, selection in
                guard !selection.isEmpty else { return }
                selectedPhotos = []
                let sources = selection.enumerated().map { index, photo in
                    BatchImageImport.Source(name: UIL10n.format("photo.number", UIL10n.number(index + 1))) {
                        guard let image = try await photo.loadTransferable(type: ImageInput.TransferredImage.self) else { throw InventoryUIError.invalidImage }
                        return .init(data: image.data, originalName: nil)
                    }
                }
                begin(sources)
            }
            .fileImporter(isPresented: $importingFile, allowedContentTypes: [.image], allowsMultipleSelection: pro.isPro) { result in
                do {
                    let urls = try result.get()
                    guard !urls.isEmpty else { return }
                    begin(urls.map { url in
                        BatchImageImport.Source(name: url.lastPathComponent) {
                            let worker = Task.detached(priority: .userInitiated) { try ImageInput.readFile(url) }
                            let data = try await withTaskCancellationHandler {
                                try await worker.value
                            } onCancel: { worker.cancel() }
                            return .init(data: data, originalName: url.lastPathComponent)
                        }
                    })
                } catch {
                    if (error as? CocoaError)?.code != .userCancelled {
                        errorMessage = error.localizedDescription
                    }
                }
            }
            .sheet(isPresented: $showingPro) { ProUpgradeView() }
            .onDisappear { importTask?.cancel() }
            .fullScreenCover(isPresented: $showingCamera) {
                CameraCapture { data in
                    showingCamera = false
                    guard let data else { return }
                    let name = "Camera-\(UUID().uuidString.prefix(8)).jpg"
                    begin([.init(name: name) { .init(data: data, originalName: name) }])
                }.ignoresSafeArea()
            }
        }
    }

    private func requestCamera() {
        guard UIImagePickerController.isSourceTypeAvailable(.camera) else {
            errorMessage = UIL10n.text("A camera is not available on this device. Choose an image from Photos or Files.")
            return
        }
        Task {
            let allowed = await AVCaptureDevice.requestAccess(for: .video)
            if allowed { showingCamera = true }
            else { errorMessage = UIL10n.text("Camera access is turned off. Enable it in Settings, or choose an image from Photos or Files.") }
        }
    }

    private func begin(_ sources: [BatchImageImport.Source]) {
        guard !batch.isRunning, !store.isBusy else { return }
        errorMessage = nil
        importKind = kind
        singleSelection = sources.count == 1
        singleAttachment = nil
        importTask = Task {
            defer { importTask = nil }
            do {
                try await batch.start(sources, isPro: { pro.isPro }, prepare: prepare, save: save)
                finishSingleImport()
            } catch { errorMessage = error.localizedDescription }
        }
    }

    private func retryFailures() {
        guard !batch.isRunning, !store.isBusy, pro.isPro || singleSelection else { return }
        errorMessage = nil
        importTask = Task {
            defer { importTask = nil }
            do { try await batch.retryFailed(isPro: { pro.isPro }, prepare: prepare, save: save); finishSingleImport() }
            catch { errorMessage = error.localizedDescription }
        }
    }

    private func finishSingleImport() {
        if !Task.isCancelled, singleSelection, batch.savedCount == 1, let attachment = singleAttachment {
            onImported(attachment)
            dismiss()
        }
    }

    private func prepare(_ payload: BatchImageImport.Payload) async throws {
        try await ImageInput.validateForImport(payload.data)
    }

    private func save(_ payload: BatchImageImport.Payload) async throws {
        // No suspension between the final access/cancellation check and the
        // atomic store commit. Pixel decoding completed in prepare above.
        try Task.checkCancellation()
        try requireImportAccess()
        let metadata = try ImageInput.inspect(payload.data)
        let name = payload.originalName ?? "Photo-\(UUID().uuidString.prefix(8)).\(metadata.fileExtension)"
        guard let attachment = await store.addAttachment(homeID: homeID, roomID: roomID, itemID: itemID,
                                                         data: payload.data, originalName: name,
                                                         mediaType: metadata.mediaType, kind: importKind) else {
            let message = store.errorMessage ?? UIL10n.text("The image could not be saved. Please try again.")
            store.errorMessage = nil
            throw BatchImageImportError.saveFailed(message)
        }
        if singleSelection { singleAttachment = attachment }
    }

    private func requireImportAccess() throws {
        guard singleSelection || pro.isPro else {
            throw BatchImageImportError.proRequired
        }
    }

    @ViewBuilder private func statusLabel(_ status: BatchImageImport.Status) -> some View {
        switch status {
        case .waiting: Label(UIL10n.text("Waiting"), systemImage: "clock").foregroundStyle(.secondary)
        case .importing: Label(UIL10n.text("Importing"), systemImage: "arrow.down.circle").foregroundStyle(.secondary)
        case .saved: Label(UIL10n.text("Saved"), systemImage: "checkmark.circle.fill").foregroundStyle(InventoryTheme.accent)
        case .failed(let reason): Label(reason, systemImage: "exclamationmark.triangle").foregroundStyle(.red)
        }
    }

}

private struct CameraCapture: UIViewControllerRepresentable {
    let completion: (Data?) -> Void
    func makeUIViewController(context: Context) -> UIImagePickerController {
        let controller = UIImagePickerController()
        controller.sourceType = .camera
        controller.cameraCaptureMode = .photo
        controller.delegate = context.coordinator
        return controller
    }
    func updateUIViewController(_ controller: UIImagePickerController, context: Context) {}
    func makeCoordinator() -> Coordinator { Coordinator(completion: completion) }

    @MainActor final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let completion: (Data?) -> Void
        init(completion: @escaping (Data?) -> Void) { self.completion = completion }
        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { completion(nil) }
        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            completion((info[.originalImage] as? UIImage)?.jpegData(compressionQuality: 0.92))
        }
    }
}
