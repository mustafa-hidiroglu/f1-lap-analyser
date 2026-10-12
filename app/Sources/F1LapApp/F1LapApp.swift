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
                .task {
                    DevSnapshot.scheduleIfRequested(model)
                    await model.start()
                }
        }
        // The window's minimum follows the content: the sidebar (when shown) plus the detail
        // column's minimum, instead of a fixed width the content did not actually fit in.
        .windowResizability(.contentMinSize)
        .defaultSize(width: 1280, height: 820)
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
    /// `F1LAP_REPO` if set, else the interpreter embedded in the .app by `bundle.sh`, else the
    /// checkout this file was built from (a bare `swift run`).
    static func located() -> SidecarConfig {
        let env = ProcessInfo.processInfo.environment["F1LAP_REPO"].map { URL(filePath: $0) }
        if env == nil, let resources = Bundle.main.resourceURL,
           let bundled = SidecarConfig.bundled(resources: resources) {
            return bundled
        }
        let repo = env
            ?? URL(filePath: #filePath)  // app/Sources/F1LapApp/F1LapApp.swift
                .deletingLastPathComponent().deletingLastPathComponent()
                .deletingLastPathComponent().deletingLastPathComponent()
        return .repository(repo)
    }
}
