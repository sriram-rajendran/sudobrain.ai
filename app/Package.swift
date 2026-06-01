// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "SudoBrain",
    platforms: [
        .macOS(.v13)
    ],
    targets: [
        .executableTarget(
            name: "SudoBrain",
            path: "SudoBrain",
            exclude: ["Info.plist"],
            resources: [
                .process("Assets.xcassets"),
            ]
        ),
    ]
)
