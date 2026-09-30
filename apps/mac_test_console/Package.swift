// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "BeaconMacTestConsole",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "BeaconMacTestConsole", targets: ["BeaconMacTestConsole"])
    ],
    targets: [
        .executableTarget(
            name: "BeaconMacTestConsole",
            path: "Sources/BeaconMacTestConsole"
        ),
        .testTarget(
            name: "BeaconMacTestConsoleTests",
            dependencies: ["BeaconMacTestConsole"],
            path: "Tests/BeaconMacTestConsoleTests"
        )
    ]
)
