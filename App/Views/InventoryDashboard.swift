import SwiftUI
import InventoryCore
import UniformTypeIdentifiers

struct InventoryDashboard: View {
    @Environment(InventoryStore.self) private var store
    @Environment(ProStore.self) private var pro
    @State private var addingHome = false
    @State private var showingPro = false
    @State private var showingPrivacy = false
    @State private var renamingHome: InventoryHome?
    @State private var deletingHome: InventoryHome?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(UIL10n.text("Know what you have.")).font(.title2.bold())
                        Text(UIL10n.text("A clear record of your belongings, one room at a time.")).foregroundStyle(.secondary)
                        HStack(spacing: 16) {
                            Label(UIL10n.count("count.rooms", store.roomCount), systemImage: "door.left.hand.closed")
                            Label(UIL10n.count("count.items", store.itemCount), systemImage: "shippingbox")
                        }.font(.subheadline).foregroundStyle(InventoryTheme.accent)
                    }.padding(.vertical, 10)
                }
                if !store.hasLoaded && !store.isBusy {
                    Section {
                        ContentUnavailableView(UIL10n.text("Inventory could not be loaded"), systemImage: "externaldrive.badge.exclamationmark", description: Text(UIL10n.text("Your saved files have not been replaced. Try loading them again.")))
                        Button(UIL10n.text("Retry loading")) { Task { await store.load() } }
                    }
                } else if store.inventory.homes.isEmpty {
                    Section {
                        ContentUnavailableView(UIL10n.text("Start with a home"), systemImage: "house", description: Text(UIL10n.text("Add your home, choose a room, then photograph each item and its documents.")))
                        Button(UIL10n.text("Add your first home"), systemImage: "plus") { addingHome = true }
                            .disabled(!store.hasLoaded)
                            .accessibilityIdentifier("inventory.addFirstHome")
                    }
                } else {
                    Section(UIL10n.text("Your homes")) {
                        ForEach(store.inventory.homes) { home in
                            NavigationLink {
                                HomeInventoryView(homeID: home.id)
                            } label: {
                                HStack(spacing: 14) {
                                    Image(systemName: "house.fill").font(.title2).foregroundStyle(InventoryTheme.accent).accessibilityHidden(true)
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(home.name).font(.headline)
                                        Text(UIL10n.format("summary.counts", UIL10n.count("count.rooms", home.rooms.count), UIL10n.count("count.items", home.rooms.reduce(0) { $0 + $1.items.count }))).font(.subheadline).foregroundStyle(.secondary)
                                    }
                                }.padding(.vertical, 5)
                            }
                            .contextMenu {
                                Button(UIL10n.text("Rename home"), systemImage: "pencil") { renamingHome = home }
                                Button(UIL10n.text("Delete home"), systemImage: "trash", role: .destructive) { deletingHome = home }
                            }
                            .swipeActions {
                                Button(UIL10n.text("Delete"), role: .destructive) { deletingHome = home }
                                Button(UIL10n.text("Rename")) { renamingHome = home }.tint(InventoryTheme.accent)
                            }
                        }
                        Button(UIL10n.text("Add a home"), systemImage: "plus") { addingHome = true }
                    }
                }
                Section {
                    Button { showingPro = true } label: {
                        Label(pro.isPro ? UIL10n.text("Room Inventory Pro is active") : UIL10n.text("Explore Pro"), systemImage: pro.isPro ? "checkmark.seal.fill" : "sparkles")
                    }
                } footer: {
                    Text(UIL10n.text("The app stores photos and documents locally and does not upload them to an app server. Your device backup settings may include these files. Keep an exported backup somewhere safe. Records do not guarantee an insurance payment or a property valuation."))
                }
            }
            .navigationTitle(UIL10n.text("Room Inventory"))
            .scrollContentBackground(.hidden)
            .background(InventoryTheme.background)
            .overlay { if store.isBusy { ProgressView(UIL10n.text("Saving your inventory…")).padding(20).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16)) } }
            .disabled(store.isBusy)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { showingPrivacy = true } label: {
                        Label(UIL10n.text("privacy.entry"), systemImage: "hand.raised")
                    }
                    .accessibilityIdentifier("inventory.privacySupport")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    InventoryExportMenu().disabled(store.isBusy)
                }
            }
            .sheet(isPresented: $showingPrivacy) { PrivacySupportView() }
            .sheet(isPresented: $addingHome) {
                NameEntrySheet(title: UIL10n.text("Add a home"), placeholder: UIL10n.text("Home name"), explanation: UIL10n.text("For example, Main home or Apartment.")) { await store.addHome(name: $0) }
            }
            .sheet(isPresented: $showingPro) { ProUpgradeView() }
            .sheet(item: $renamingHome) { home in
                NameEntrySheet(title: UIL10n.text("Rename home"), placeholder: UIL10n.text("Home name"), explanation: UIL10n.text("Rooms and items stay in this home."), initialName: home.name, actionTitle: UIL10n.text("Save")) {
                    await store.renameHome(homeID: home.id, name: $0)
                }
            }
            .alert(UIL10n.text("Delete this home?"), isPresented: Binding(get: { deletingHome != nil }, set: { if !$0 { deletingHome = nil } })) {
                Button(UIL10n.text("Cancel"), role: .cancel) { deletingHome = nil }
                Button(UIL10n.text("Delete home"), role: .destructive) {
                    if let home = deletingHome { Task { await store.deleteHome(homeID: home.id) } }
                    deletingHome = nil
                }
            } message: { Text(UIL10n.text("All rooms, items, and file links in this home will be removed. Original files remain in local recovery storage until the app is deleted. Export a backup first if you want to keep this home's records.")) }
            .alert(UIL10n.text("Unable to complete"), isPresented: Binding(get: { store.errorMessage != nil }, set: { if !$0 { store.errorMessage = nil } })) {
                Button(UIL10n.text("OK"), role: .cancel) { store.errorMessage = nil }
            } message: { Text(store.errorMessage ?? "") }
            .alert(UIL10n.text("Inventory restored"), isPresented: Binding(get: { store.notice != nil }, set: { if !$0 { store.notice = nil } })) {
                Button(UIL10n.text("OK"), role: .cancel) { store.notice = nil }
            } message: { Text(store.notice ?? "") }
        }
    }
}

struct HomeInventoryView: View {
    let homeID: UUID
    @Environment(InventoryStore.self) private var store
    @Environment(ProStore.self) private var pro
    @State private var addingRoom = false
    @State private var showingPro = false
    @State private var renamingRoom: InventoryRoom?
    @State private var deletingRoom: InventoryRoom?
    private var home: InventoryHome? { store.home(homeID) }

    var body: some View {
        List {
            if let home {
                if home.rooms.isEmpty {
                    ContentUnavailableView(UIL10n.text("Choose your first room"), systemImage: "door.left.hand.closed", description: Text(UIL10n.text("Start small. A finished room is more useful than an unfinished house.")))
                }
                ForEach(home.rooms) { room in
                    NavigationLink { RoomInventoryView(homeID: homeID, roomID: room.id) } label: {
                        VStack(alignment: .leading, spacing: 5) {
                            Text(room.name).font(.headline)
                            Text(UIL10n.count("count.items", room.items.count)).font(.subheadline).foregroundStyle(.secondary)
                        }.padding(.vertical, 6)
                    }
                    .contextMenu {
                        Button(UIL10n.text("Rename room"), systemImage: "pencil") { renamingRoom = room }
                        Button(UIL10n.text("Delete room"), systemImage: "trash", role: .destructive) { deletingRoom = room }
                    }
                    .swipeActions {
                        Button(UIL10n.text("Delete"), role: .destructive) { deletingRoom = room }
                        Button(UIL10n.text("Rename")) { renamingRoom = room }.tint(InventoryTheme.accent)
                    }
                }
                Button(UIL10n.text("Add a room"), systemImage: "plus") { addRoom() }
                if !pro.isPro { Text(UIL10n.text("Free: one room and 10 items across all homes.")).font(.footnote).foregroundStyle(.secondary) }
            } else {
                ContentUnavailableView(UIL10n.text("Home unavailable"), systemImage: "house", description: Text(UIL10n.text("The inventory may have been replaced by a backup. Return to your homes.")))
            }
        }
        .navigationTitle(home?.name ?? UIL10n.text("Home"))
        .background(InventoryTheme.background)
        .disabled(store.isBusy)
        .sheet(isPresented: $addingRoom) {
            NameEntrySheet(title: UIL10n.text("Add a room"), placeholder: UIL10n.text("Room name"), explanation: UIL10n.text("For example, Living room or Office.")) {
                await store.addRoom(homeID: homeID, name: $0, isPro: pro.isPro)
            }
        }
        .sheet(isPresented: $showingPro) { ProUpgradeView() }
        .sheet(item: $renamingRoom) { room in
            NameEntrySheet(title: UIL10n.text("Rename room"), placeholder: UIL10n.text("Room name"), explanation: UIL10n.text("Items stay in this room."), initialName: room.name, actionTitle: UIL10n.text("Save")) {
                await store.renameRoom(homeID: homeID, roomID: room.id, name: $0)
            }
        }
        .alert(UIL10n.text("Delete this room?"), isPresented: Binding(get: { deletingRoom != nil }, set: { if !$0 { deletingRoom = nil } })) {
            Button(UIL10n.text("Cancel"), role: .cancel) { deletingRoom = nil }
            Button(UIL10n.text("Delete room"), role: .destructive) {
                if let room = deletingRoom { Task { await store.deleteRoom(homeID: homeID, roomID: room.id) } }
                deletingRoom = nil
            }
        } message: { Text(UIL10n.text("All items and file links in this room will be removed. Original files remain in local recovery storage until the app is deleted. Export a backup first if you want to keep this room's records.")) }
    }
    private func addRoom() { if store.canAddRoom(isPro: pro.isPro) { addingRoom = true } else { showingPro = true } }
}

struct RoomInventoryView: View {
    let homeID: UUID
    let roomID: UUID
    @Environment(InventoryStore.self) private var store
    @Environment(ProStore.self) private var pro
    @State private var addingItem = false
    @State private var showingPro = false
    @State private var deletingItem: InventoryItem?
    private var room: InventoryRoom? { store.room(homeID: homeID, roomID: roomID) }

    var body: some View {
        List {
            if let room {
                if room.items.isEmpty {
                    ContentUnavailableView(UIL10n.text("Give your things a record"), systemImage: "shippingbox", description: Text(UIL10n.text("Add an item, take its photo, then capture its label and receipt when you have them.")))
                }
                Section {
                    ForEach(room.items) { item in
                        NavigationLink { ItemDetailView(homeID: homeID, roomID: roomID, itemID: item.id) } label: {
                            HStack(spacing: 12) {
                                Image(systemName: "shippingbox.fill").font(.title2).foregroundStyle(InventoryTheme.accent).accessibilityHidden(true)
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(item.name).font(.headline)
                                    if !item.model.isEmpty { Text(item.model).font(.subheadline).foregroundStyle(.secondary) }
                                    Text(UIL10n.format("summary.counts", UIL10n.count("count.files", item.attachments.count), UIL10n.count("count.details", item.missingMaterials.count))).font(.caption).foregroundStyle(.secondary)
                                }
                            }.padding(.vertical, 6)
                        }
                        .swipeActions { Button(UIL10n.text("Delete"), role: .destructive) { deletingItem = item } }
                    }
                    Button(UIL10n.text("Add an item"), systemImage: "plus") { addItem() }
                } footer: { Text(UIL10n.text("Suggested details are reminders. Some items do not have a receipt or serial number.")) }
            } else { ContentUnavailableView(UIL10n.text("Room unavailable"), systemImage: "door.left.hand.closed", description: Text(UIL10n.text("Return to your homes to see the current inventory."))) }
        }
        .navigationTitle(room?.name ?? UIL10n.text("Room"))
        .disabled(store.isBusy)
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button(UIL10n.text("Add item"), systemImage: "plus") { addItem() }.disabled(room == nil) } }
        .sheet(isPresented: $addingItem) {
            NameEntrySheet(title: UIL10n.text("Add an item"), placeholder: UIL10n.text("Item name"), explanation: UIL10n.text("Use a name you will recognize, such as Office monitor.")) {
                await store.addItem(homeID: homeID, roomID: roomID, name: $0, isPro: pro.isPro)
            }
        }
        .sheet(isPresented: $showingPro) { ProUpgradeView() }
        .alert(UIL10n.text("Delete this item?"), isPresented: Binding(get: { deletingItem != nil }, set: { if !$0 { deletingItem = nil } })) {
            Button(UIL10n.text("Cancel"), role: .cancel) { deletingItem = nil }
            Button(UIL10n.text("Delete"), role: .destructive) {
                if let item = deletingItem { Task { await store.deleteItem(homeID: homeID, roomID: roomID, itemID: item.id) } }
                deletingItem = nil
            }
        } message: { Text(UIL10n.text("This removes the item and its file links from your inventory. Original files remain in local recovery storage until the app is deleted. Existing exported backups are not changed.")) }
    }
    private func addItem() { if store.canAddItem(isPro: pro.isPro) { addingItem = true } else { showingPro = true } }
}

struct InventoryExportMenu: View {
    @Environment(InventoryStore.self) private var store
    @Environment(ProStore.self) private var pro
    @State private var export: SharedExport?
    @State private var importing = false
    @State private var pendingBackup: URL?
    @State private var isPreparing = false
    @State private var showingCustomReport = false
    @State private var showingPro = false

    var body: some View {
        Menu {
            Section(UIL10n.text("Export all homes")) {
                Button(UIL10n.text("Inventory package · ZIP"), systemImage: "archivebox") { prepare(.package) }
                Button(UIL10n.text("Report · PDF"), systemImage: "doc.richtext") { prepare(.pdf) }
                Button(UIL10n.text("Item table · CSV"), systemImage: "tablecells") { prepare(.csv) }
                Button(UIL10n.text("Restorable backup + originals"), systemImage: "externaldrive") { prepare(.backup) }
            }.disabled(!store.hasLoaded)
            Section {
                Button(UIL10n.text("Custom PDF report · Pro"), systemImage: "slider.horizontal.3") {
                    if pro.isPro { showingCustomReport = true }
                    else { showingPro = true }
                }.disabled(!store.hasLoaded)
            }
            Section { Button(UIL10n.text("Restore a backup"), systemImage: "arrow.clockwise") { importing = true }.disabled(store.repository == nil) }
        } label: {
            Label(isPreparing ? UIL10n.text("Preparing export") : UIL10n.text("Export and backup"), systemImage: isPreparing ? "hourglass" : "square.and.arrow.up")
        }
        .disabled(store.isBusy || isPreparing)
        .accessibilityIdentifier("inventory.exportMenu")
        .sheet(item: $export) { ExportShareSheet(url: $0.url) }
        .sheet(isPresented: $showingCustomReport) { CustomReportSheet(inventory: store.inventory) }
        .sheet(isPresented: $showingPro) { ProUpgradeView() }
        .fileImporter(isPresented: $importing, allowedContentTypes: [.data], allowsMultipleSelection: false) { result in
            do { pendingBackup = try result.get().first }
            catch { store.errorMessage = error.localizedDescription }
        }
        .alert(UIL10n.text("Replace the current inventory?"), isPresented: Binding(get: { pendingBackup != nil }, set: { if !$0 { pendingBackup = nil } })) {
            Button(UIL10n.text("Cancel"), role: .cancel) { pendingBackup = nil }
            Button(UIL10n.text("Restore backup"), role: .destructive) {
                if let url = pendingBackup { Task { await store.restore(url: url) } }
                pendingBackup = nil
            }
        } message: { Text(UIL10n.text("A valid backup replaces all homes, rooms, items, and file links on this device. Export your current inventory as a backup first if you want to keep it. An invalid backup leaves your current inventory intact.")) }
    }
    private enum Format { case package, pdf, csv, backup }
    private func prepare(_ format: Format) {
        guard !isPreparing, !store.isBusy else { return }
        isPreparing = true
        Task { @MainActor in
            await Task.yield()
            defer { isPreparing = false }
            do {
                guard let repository = store.repository else { throw InventoryUIError.unavailable }
                let url: URL
                switch format {
                case .package: url = try await ExportService.bundleURL(inventory: store.inventory, repository: repository)
                case .pdf: url = try await ExportService.pdfURL(inventory: store.inventory)
                case .csv: url = try await ExportService.csvURL(inventory: store.inventory)
                case .backup: url = try await ExportService.backupURL(inventory: store.inventory, repository: repository)
                }
                export = SharedExport(url: url)
            } catch { store.errorMessage = error.localizedDescription }
        }
    }
}
