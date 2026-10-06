import AppKit
import F1LapKit
import SwiftUI

@main
struct F1LapApp: App {
    @NSApplicationDelegateAdaptor private var delegate: AppDelegate
    @State private var model = AppModel(service: F1LapService(client: SidecarClient(config: .located())))

    var body: some Scene {
        WindowGroup("F1 Lap Analyser") {
            ContentView()
                .environment(model)
                .frame(minWidth: 1100, minHeight: 720)
                .task {
                    DevSnapshot.scheduleIfRequested(model)
                    await model.start()
                }
        }
        .commands {
            CommandGroup(after: .newItem) {
                Button("Compare") { model.compare() }
                    .keyboardShortcut(.return, modifiers: .command)
                    .disabled(!model.canCompare)
            }
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Launched as a bare SwiftPM executable (no .app bundle): become a regular, focused app.
        NSApp.setActivationPolicy(.regular)
        NSApp.activate()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

extension SidecarConfig {
    /// `F1LAP_REPO` if set, else the checkout this file was built from (personal use: the app runs
    /// the repository's virtualenv rather than a bundled interpreter).
    static func located() -> SidecarConfig {
        let repo = ProcessInfo.processInfo.environment["F1LAP_REPO"].map { URL(filePath: $0) }
            ?? URL(filePath: #filePath)  // app/Sources/F1LapApp/F1LapApp.swift
                .deletingLastPathComponent().deletingLastPathComponent()
                .deletingLastPathComponent().deletingLastPathComponent()
        return .repository(repo)
    }
}
