import SwiftUI

@main
struct RoomInventoryApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @State private var store: InventoryStore
    @State private var pro = ProStore()

    init() {
        #if DEBUG
        // Test launches get a fixed, UUID-only child of this app's temporary
        // directory. Reusing the UUID preserves data across a test relaunch.
        // No arbitrary path and no reset of the user's regular inventory.
        if ProcessInfo.processInfo.arguments.contains("--ui-testing"),
           let value = ProcessInfo.processInfo.environment["UITEST_RUN_ID"],
           let runID = UUID(uuidString: value) {
            let root = FileManager.default.temporaryDirectory
                .appendingPathComponent("RoomInventoryUITests", isDirectory: true)
                .appendingPathComponent(runID.uuidString, isDirectory: true)
            _store = State(initialValue: InventoryStore(rootURL: root))
            return
        }
        #endif
        _store = State(initialValue: InventoryStore())
    }

    var body: some Scene {
        WindowGroup {
            InventoryDashboard()
                .environment(store)
                .environment(pro)
                .tint(InventoryTheme.accent)
                .task { await store.load(); await pro.load() }
                .onChange(of: scenePhase) { _, phase in
                    if phase == .active { Task { await pro.load() } }
                }
        }
    }
}
