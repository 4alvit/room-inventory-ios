// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "InventoryCore",
    defaultLocalization: "en",
    platforms: [.iOS(.v17), .macOS(.v13)],
    products: [.library(name: "InventoryCore", targets: ["InventoryCore"])],
    targets: [
        .target(name: "InventoryCore", resources: [.process("Resources")]),
        .testTarget(name: "InventoryCoreTests", dependencies: ["InventoryCore"])
    ]
)
