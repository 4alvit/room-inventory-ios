import SwiftUI
import UIKit

enum InventoryTheme {
    static let accent = Color(red: 0.08, green: 0.40, blue: 0.37)
    static let background = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark ? .systemGroupedBackground : UIColor(red: 0.965, green: 0.956, blue: 0.933, alpha: 1)
    })
}

struct NameEntrySheet: View {
    let title: String
    let placeholder: String
    let explanation: String
    let actionTitle: String
    let initialName: String
    let save: (String) async -> Bool
    @Environment(InventoryStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var saving = false
    @State private var errorMessage: String?
    @State private var discarding = false
    @FocusState private var focused: Bool

    init(title: String, placeholder: String, explanation: String, initialName: String = "", actionTitle: String = UIL10n.text("Add"), save: @escaping (String) async -> Bool) {
        self.title = title; self.placeholder = placeholder; self.explanation = explanation
        self.actionTitle = actionTitle; self.initialName = initialName; self.save = save
        _name = State(initialValue: initialName)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField(placeholder, text: $name).focused($focused).submitLabel(.done)
                        .accessibilityIdentifier("entry.name")
                        .onSubmit { submit() }
                } footer: { Text(explanation) }
                if let errorMessage { Section { Text(errorMessage).foregroundStyle(.red) } }
            }
            .disabled(saving)
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(UIL10n.text("Cancel")) {
                        if name != initialName { discarding = true } else { dismiss() }
                    }.disabled(saving)
                        .accessibilityIdentifier("entry.cancel")
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(actionTitle) { submit() }.disabled(saving || name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        .accessibilityIdentifier("entry.save")
                }
            }
            .interactiveDismissDisabled(saving || name != initialName)
            .confirmationDialog(UIL10n.text("Discard unsaved changes?"), isPresented: $discarding, titleVisibility: .visible) {
                Button(UIL10n.text("Discard changes"), role: .destructive) { dismiss() }
                Button(UIL10n.text("Keep editing"), role: .cancel) {}
            }
            .task { focused = true }
        }
    }
    private func submit() {
        guard !saving, !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        saving = true
        Task {
            if await save(name) { dismiss() }
            else {
                errorMessage = store.errorMessage ?? UIL10n.text("This could not be saved. Check available storage and your plan limit, then try again.")
                store.errorMessage = nil
            }
            saving = false
        }
    }
}

struct ExportShareSheet: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> UIActivityViewController {
        let controller = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        // Identify the real share controller without changing its accessibility grouping.
        controller.view.accessibilityIdentifier = "inventory.exportShare"
        return controller
    }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}

struct SharedExport: Identifiable {
    let id = UUID()
    let url: URL
}

struct ProUpgradeView: View {
    @Environment(ProStore.self) private var pro
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    Image(systemName: "house.and.flag.fill").font(.system(size: 48)).foregroundStyle(InventoryTheme.accent).accessibilityHidden(true)
                    Text(UIL10n.text("A place for every thing.")).font(.largeTitle.bold())
                    Text(UIL10n.text("Room Inventory Pro")).font(.title2.weight(.semibold))
                    Label(UIL10n.text("More rooms and items"), systemImage: "square.grid.2x2")
                    Label(UIL10n.text("Import up to 10 images at once"), systemImage: "photo.stack")
                    Label(UIL10n.text("Choose rooms and details for PDF reports"), systemImage: "slider.horizontal.3")
                    Label(UIL10n.text("One purchase, no subscription"), systemImage: "checkmark.seal")
                    Label(UIL10n.text("No account or app server"), systemImage: "iphone")
                    Text(UIL10n.text("Free includes one room and 10 items across all homes. Your current inventory can include up to 80 MiB of original files, including with Pro. Removed originals kept for recovery may use additional device storage. Viewing, editing, restoring backups, and basic exports remain available without Pro. Device backups may include your locally stored files."))
                        .font(.subheadline).foregroundStyle(.secondary)
                    if pro.isPro {
                        Label(UIL10n.text("Pro is unlocked"), systemImage: "checkmark.circle.fill").font(.headline).foregroundStyle(InventoryTheme.accent)
                    } else {
                        Button {
                            Task { await pro.purchase() }
                        } label: {
                            Text(pro.displayPrice.map { UIL10n.format("pro.unlock.price", $0) } ?? UIL10n.text("Price unavailable"))
                                .fixedSize(horizontal: false, vertical: true)
                                .frame(maxWidth: .infinity).padding(.vertical, 8)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(pro.isBusy || pro.displayPrice == nil)
                    }
                    if let message = pro.message { Text(message).font(.subheadline).foregroundStyle(.secondary).accessibilityLabel(UIL10n.format("pro.store.status", message)) }
                    if pro.isBusy { ProgressView(UIL10n.text("Connecting to the App Store…")) }
                    VStack(alignment: .leading, spacing: 16) {
                        Button(UIL10n.text("Restore purchases")) { Task { await pro.restore() } }
                        Button(UIL10n.text("Refresh price")) { Task { await pro.load() } }
                    }.font(.subheadline).disabled(pro.isBusy)
                    Text(UIL10n.text("Payment is handled by Apple. The App Store confirms your local price before you pay. A pending purchase unlocks Pro only after Apple approves it."))
                        .font(.footnote).foregroundStyle(.secondary)
                }.padding(24)
            }
            .background(InventoryTheme.background)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button(UIL10n.text("Done")) { dismiss() } } }
            .task { await pro.load() }
        }
    }
}
