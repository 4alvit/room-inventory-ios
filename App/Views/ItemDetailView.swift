import SwiftUI
import InventoryCore
import ImageIO

struct ItemDetailView: View {
    let homeID: UUID
    let roomID: UUID
    let itemID: UUID
    @Environment(InventoryStore.self) private var store
    @State private var editing = false
    @State private var attaching = false
    @State private var selectedAttachment: InventoryAttachment?
    @State private var deletingAttachment: InventoryAttachment?
    @State private var pendingRecognition: InventoryAttachment?
    @State private var recognized: OCRResult?
    @State private var isRecognizing = false
    private var item: InventoryItem? { store.item(homeID: homeID, roomID: roomID, itemID: itemID) }

    var body: some View {
        List {
            if let item {
                Section(UIL10n.text("Item details")) {
                    detail(UIL10n.text("Model"), value: item.model)
                    detail(UIL10n.text("Serial number"), value: item.serialNumber)
                    detail(UIL10n.text("Purchase price"), value: InventoryDisplay.purchasePrice(item.purchasePrice))
                    detail(UIL10n.text("Purchase date"), value: InventoryDisplay.purchaseDate(item.purchaseDate))
                    if !item.notes.isEmpty { Text(item.notes).font(.body) }
                    Button(UIL10n.text("Edit details"), systemImage: "pencil") { editing = true }
                }
                Section {
                    ForEach(item.attachments) { attachment in
                        Button { selectedAttachment = attachment } label: {
                            HStack(spacing: 12) {
                                AttachmentThumbnail(attachment: attachment)
                                VStack(alignment: .leading, spacing: 4) {
                                    Label(attachment.kind.title, systemImage: attachment.kind.symbol).font(.headline)
                                    Text(attachment.originalName).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                                }
                                Spacer(minLength: 0)
                                Image(systemName: "chevron.right").font(.caption).foregroundStyle(.secondary)
                            }
                        }.foregroundStyle(.primary)
                        .contextMenu {
                            Button(UIL10n.text("Recognize text"), systemImage: "text.viewfinder") { recognize(attachment) }
                            Button(UIL10n.text("Remove file"), systemImage: "trash", role: .destructive) { deletingAttachment = attachment }
                        }
                        .swipeActions { Button(UIL10n.text("Remove"), role: .destructive) { deletingAttachment = attachment } }
                    }
                    Button(UIL10n.text("Add photo or document image"), systemImage: "camera.badge.ellipsis") { attaching = true }
                } header: { Text(UIL10n.text("Photos & documents")) } footer: {
                    Text(UIL10n.text("Capture the item, its model label, and its receipt. Text recognition happens on your device. Long-press a file to recognize its text again."))
                }
                Section {
                    if item.missingMaterials.isEmpty {
                        Label(UIL10n.text("All suggested details recorded"), systemImage: "checkmark.circle.fill").foregroundStyle(InventoryTheme.accent)
                    } else {
                        ForEach(item.missingMaterials, id: \.self) { Text($0).font(.subheadline).foregroundStyle(.secondary) }
                    }
                } header: { Text(UIL10n.text("Suggested next steps")) } footer: { Text(UIL10n.text("Only add details that apply to this item. These reminders are not requirements for an insurance claim.")) }
            } else {
                ContentUnavailableView(UIL10n.text("Item unavailable"), systemImage: "shippingbox", description: Text(UIL10n.text("Return to the room to see the current inventory.")))
            }
        }
        .navigationTitle(item?.name ?? UIL10n.text("Item"))
        .navigationBarTitleDisplayMode(.inline)
        .disabled(store.isBusy || isRecognizing)
        .overlay { if isRecognizing { ProgressView(UIL10n.text("Reading text on device…")).padding(20).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16)) } }
        .sheet(isPresented: $editing) {
            if let item { EditItemSheet(homeID: homeID, roomID: roomID, item: item) }
        }
        .sheet(isPresented: $attaching, onDismiss: {
            if let attachment = pendingRecognition { pendingRecognition = nil; recognize(attachment) }
        }) {
            AttachImageSheet(homeID: homeID, roomID: roomID, itemID: itemID) { attachment in
                if attachment.kind != .photo { pendingRecognition = attachment }
            }
        }
        .sheet(item: $selectedAttachment) { attachment in
            AttachmentPreview(attachment: attachment) {
                pendingRecognition = attachment
                selectedAttachment = nil
            }
            .onDisappear {
                if let pending = pendingRecognition { pendingRecognition = nil; recognize(pending) }
            }
        }
        .sheet(item: $recognized) { result in
            OCRReviewSheet(result: result, item: item) { suggestions in
                guard var updated = item else { return false }
                for suggestion in suggestions {
                    switch suggestion.field {
                    case .model: updated.model = suggestion.value
                    case .serialNumber: updated.serialNumber = suggestion.value
                    case .purchasePrice: updated.purchasePrice = suggestion.value
                    case .purchaseDate: updated.purchaseDate = suggestion.value
                    }
                }
                return await store.updateItem(homeID: homeID, roomID: roomID, item: updated)
            }
        }
        .alert(UIL10n.text("Remove this file?"), isPresented: Binding(get: { deletingAttachment != nil }, set: { if !$0 { deletingAttachment = nil } })) {
            Button(UIL10n.text("Cancel"), role: .cancel) { deletingAttachment = nil }
            Button(UIL10n.text("Remove"), role: .destructive) {
                if let attachment = deletingAttachment { Task { await store.removeAttachment(homeID: homeID, roomID: roomID, itemID: itemID, attachmentID: attachment.id) } }
                deletingAttachment = nil
            }
        } message: { Text(UIL10n.text("The file will no longer be linked to this item. Its original remains in local recovery storage until the app is deleted. Previously exported copies are not affected.")) }
    }

    private func detail(_ label: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            Text(value.isEmpty ? UIL10n.text("Not recorded") : value).foregroundStyle(value.isEmpty ? .secondary : .primary).textSelection(.enabled)
        }.padding(.vertical, 2)
    }

    private func recognize(_ attachment: InventoryAttachment) {
        guard !isRecognizing else { return }
        isRecognizing = true
        Task {
            defer { isRecognizing = false }
            do { recognized = try await OCRService.recognize(store.attachmentData(attachment)) }
            catch { store.errorMessage = UIL10n.format("ocr.failure", error.localizedDescription) }
        }
    }
}

private struct EditItemSheet: View {
    let homeID: UUID
    let roomID: UUID
    let item: InventoryItem
    @Environment(InventoryStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var draft: InventoryItem
    @State private var discarding = false
    @State private var saveError: String?

    init(homeID: UUID, roomID: UUID, item: InventoryItem) {
        self.homeID = homeID; self.roomID = roomID; self.item = item
        _draft = State(initialValue: item)
    }
    var body: some View {
        NavigationStack {
            Form {
                Section(UIL10n.text("Item")) {
                    TextField(UIL10n.text("Name"), text: $draft.name)
                    TextField(UIL10n.text("Model"), text: $draft.model).textInputAutocapitalization(.never).autocorrectionDisabled()
                    TextField(UIL10n.text("Serial number"), text: $draft.serialNumber).textInputAutocapitalization(.never).autocorrectionDisabled()
                }
                Section {
                    TextField(UIL10n.text("Purchase price, e.g. USD 199.00"), text: $draft.purchasePrice)
                    TextField(UIL10n.text("Purchase date, YYYY-MM-DD"), text: $draft.purchaseDate).textInputAutocapitalization(.never).autocorrectionDisabled()
                } header: { Text(UIL10n.text("Purchase")) } footer: { Text(UIL10n.text("Include a currency with the price. Leave unknown details blank.")) }
                Section(UIL10n.text("Notes")) { TextField(UIL10n.text("Details worth keeping"), text: $draft.notes, axis: .vertical).lineLimit(3...8) }
                if let saveError { Section { Text(saveError).foregroundStyle(.red) } }
            }
            .navigationTitle(UIL10n.text("Edit item")).navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(UIL10n.text("Cancel")) { if draft != item { discarding = true } else { dismiss() } }.disabled(store.isBusy) }
                ToolbarItem(placement: .confirmationAction) {
                    Button(UIL10n.text("Save")) {
                        Task {
                            if await store.updateItem(homeID: homeID, roomID: roomID, item: draft) { dismiss() }
                            else { saveError = store.errorMessage ?? UIL10n.text("Your changes could not be saved. Try again."); store.errorMessage = nil }
                        }
                    }.disabled(store.isBusy || draft.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .disabled(store.isBusy)
            .interactiveDismissDisabled(draft != item || store.isBusy)
            .confirmationDialog(UIL10n.text("Discard unsaved changes?"), isPresented: $discarding, titleVisibility: .visible) {
                Button(UIL10n.text("Discard changes"), role: .destructive) { dismiss() }
                Button(UIL10n.text("Keep editing"), role: .cancel) {}
            }
        }
    }
}

struct OCRReviewSheet: View {
    let item: InventoryItem?
    let apply: ([OCRSuggestion]) async -> Bool
    @Environment(\.dismiss) private var dismiss
    @State private var result: OCRResult
    @State private var applying = false
    @State private var failed = false

    init(result: OCRResult, item: InventoryItem?, apply: @escaping ([OCRSuggestion]) async -> Bool) {
        self.item = item; self.apply = apply; _result = State(initialValue: result)
    }
    private var selected: [OCRSuggestion] { result.suggestions.filter { $0.isSelected && !$0.value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty } }
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(UIL10n.text("Check the original before saving. Recognition can make mistakes. Select only the values you want to use; selected values replace the corresponding item details."))
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                if result.suggestions.isEmpty {
                    Section {
                        Text(result.text.isEmpty ? UIL10n.text("No readable text was found. Try a sharper, well-lit photo or enter details manually.") : UIL10n.text("Text was found, but no model, serial number, price, or date could be identified. Copy the text below and edit the item manually."))
                    }
                } else {
                    Section(UIL10n.text("Suggested values — select to apply")) {
                        ForEach($result.suggestions) { $suggestion in
                            VStack(alignment: .leading, spacing: 8) {
                                Toggle(UIL10n.format("ocr.use.field", suggestion.field.title), isOn: $suggestion.isSelected)
                                TextField(suggestion.field.title, text: $suggestion.value).textInputAutocapitalization(.never).autocorrectionDisabled()
                                if let old = existing(suggestion.field), !old.isEmpty { Text(UIL10n.format("ocr.current.value", old)).font(.caption).foregroundStyle(.secondary) }
                            }.padding(.vertical, 4)
                        }
                    }
                }
                if !result.text.isEmpty { Section(UIL10n.text("Recognized text")) { Text(result.text).font(.body.monospaced()).textSelection(.enabled) } }
                if failed { Text(UIL10n.text("Changes could not be saved. Your original details are still available. Try again.")).foregroundStyle(.red) }
            }
            .navigationTitle(UIL10n.text("Review recognized text")).navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(UIL10n.text("Close")) { dismiss() }.disabled(applying) }
                ToolbarItem(placement: .confirmationAction) {
                    Button(UIL10n.count("count.apply", selected.count)) {
                        applying = true
                        Task { if await apply(selected) { dismiss() } else { failed = true }; applying = false }
                    }.disabled(selected.isEmpty || applying)
                }
            }
            .disabled(applying).interactiveDismissDisabled(applying)
        }
    }
    private func existing(_ field: OCRField) -> String? {
        switch field { case .model: item?.model; case .serialNumber: item?.serialNumber; case .purchasePrice: item?.purchasePrice; case .purchaseDate: item?.purchaseDate }
    }
}

private enum ImagePreview {
    static func thumbnail(_ data: Data, maxSize: Int) throws -> UIImage {
        UIImage(cgImage: try ImageInput.thumbnail(data, maxDimension: maxSize))
    }
}

private struct AttachmentThumbnail: View {
    let attachment: InventoryAttachment
    @Environment(InventoryStore.self) private var store
    @State private var image: UIImage?
    var body: some View {
        Group {
            if let image { Image(uiImage: image).resizable().scaledToFill() }
            else { Image(systemName: attachment.kind.symbol).font(.title3).foregroundStyle(.secondary) }
        }
        .frame(width: 54, height: 54).background(.quaternary).clipShape(RoundedRectangle(cornerRadius: 10)).accessibilityHidden(true)
        .task(id: attachment.id) { if let data = try? await store.attachmentData(attachment) { image = try? ImagePreview.thumbnail(data, maxSize: 180) } }
    }
}

private struct AttachmentPreview: View {
    let attachment: InventoryAttachment
    let recognize: () -> Void
    @Environment(InventoryStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var image: UIImage?
    @State private var error: String?
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let image { Image(uiImage: image).resizable().scaledToFit().accessibilityLabel(attachment.kind.title) }
                    else if let error { ContentUnavailableView(UIL10n.text("Preview unavailable"), systemImage: "exclamationmark.triangle", description: Text(error)) }
                    else { ProgressView(UIL10n.text("Loading original…")) }
                    Text(attachment.originalName).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                    Button(UIL10n.text("Recognize text"), systemImage: "text.viewfinder", action: recognize).buttonStyle(.borderedProminent).disabled(image == nil)
                }.padding()
            }
            .navigationTitle(attachment.kind.title).navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button(UIL10n.text("Done")) { dismiss() } } }
            .task {
                do {
                    let data = try await store.attachmentData(attachment)
                    image = try ImagePreview.thumbnail(data, maxSize: 2400)
                } catch { self.error = UIL10n.format("preview.failure", error.localizedDescription) }
            }
        }
    }
}
