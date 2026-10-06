// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "F1Lap",
    platforms: [.macOS(.v15)],
    products: [
        .executable(name: "F1Lap", targets: ["F1LapApp"]),
        .library(name: "F1LapKit", targets: ["F1LapKit"]),
    ],
    targets: [
        .target(name: "F1LapKit"),
        .executableTarget(name: "F1LapApp", dependencies: ["F1LapKit"]),
        .testTarget(
            name: "F1LapKitTests",
            dependencies: ["F1LapKit"],
            resources: [.copy("Fixtures")]
        ),
    ]
)
