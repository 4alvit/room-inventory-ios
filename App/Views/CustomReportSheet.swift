import SwiftUI
import InventoryCore

struct CustomReportSheet: View {
    @Environment(InventoryStore.self) private var store
    @Environment(ProStore.self) private var pro
    @Environment(\.dismiss) private var dismiss
    @State private var options: InventoryReportOptions
    @State private var isPreparing = false
    @State private var export: SharedExport?
    @State private var errorMessage: String?

    init(inventory: Inventory) {
        _options = State(initialValue: InventoryReportOptions(roomIDs: Set(inventory.homes.flatMap { $0.rooms.map(\.id) })))
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(UIL10n.text("Choose rooms and details for this PDF. These choices do not change your saved inventory. The PDF is not encrypted and does not include image files."))
                }
                ForEach(store.inventory.homes) { home in
                    Section(home.name) {
                        ForEach(home.rooms) { room in
                            Toggle(room.name, isOn: Binding(
                                get: { options.roomIDs.contains(room.id) },
                                set: { included in
                                    if included { options.roomIDs.insert(room.id) }
                                    else { options.roomIDs.remove(room.id) }
                                }
                            ))
                        }
                    }
                }
                Section(UIL10n.text("Include details")) {
                    Toggle(UIL10n.text("Serial numbers"), isOn: $options.includeSerialNumbers)
                    Toggle(UIL10n.text("Purchase prices and dates"), isOn: $options.includePurchaseDetails)
                    Toggle(UIL10n.text("Notes"), isOn: $options.includeNotes)
                    Toggle(UIL10n.text("Attachment names and paths"), isOn: $options.includeAttachmentList)
                }
                Section {
                    if selectedInventory.homes.isEmpty { Text(UIL10n.text("Select at least one room to create a report.")) }
                    if !pro.isPro { Text(UIL10n.text("Custom reports require Pro. The standard PDF remains available from Export and backup.")) }
                    if let errorMessage { Text(errorMessage).foregroundStyle(.red) }
                    if isPreparing { ProgressView(UIL10n.text("Creating your PDF…")) }
                    Button(UIL10n.text("Create PDF")) { createReport() }
                        .disabled(!pro.isPro || selectedInventory.homes.isEmpty || store.isBusy || isPreparing)
                        .accessibilityIdentifier("report.create")
                }
            }
            .disabled(isPreparing)
            .navigationTitle(UIL10n.text("Custom PDF report"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button(UIL10n.text("Done")) { dismiss() }.disabled(isPreparing) } }
            .interactiveDismissDisabled(isPreparing)
            .sheet(item: $export) { ExportShareSheet(url: $0.url) }
        }
    }

    private var selectedInventory: Inventory { options.applying(to: store.inventory) }

    private func createReport() {
        guard pro.isPro, !store.isBusy, !isPreparing else { return }
        let selected = selectedInventory
        guard !selected.homes.isEmpty else { return }
        isPreparing = true
        errorMessage = nil
        Task {
            defer { isPreparing = false }
            do { export = SharedExport(url: try await ExportService.pdfURL(inventory: selected)) }
            catch { errorMessage = error.localizedDescription }
        }
    }
}
