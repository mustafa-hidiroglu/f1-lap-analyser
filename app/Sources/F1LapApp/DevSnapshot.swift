import AppKit

/// Development aid: `F1LAP_SNAPSHOT=/path/shot.png` writes the main window to a PNG once the
/// model is idle with results, then quits. Draws the view hierarchy itself, so it needs no
/// screen-recording permission (used to check layouts from scripts). `F1LAP_SNAPSHOT_SIZE=1600x1000`
/// resizes the window first.
@MainActor
enum DevSnapshot {
    static func scheduleIfRequested(_ model: AppModel) {
        guard let path = ProcessInfo.processInfo.environment["F1LAP_SNAPSHOT"] else { return }
        Task {
            let deadline = ContinuousClock.now + .seconds(120)
            while ContinuousClock.now < deadline {
                try? await Task.sleep(for: .milliseconds(500))
                let done = model.tab == .compare ? model.comparison != nil : model.rating != nil
                if model.busy == nil, done || model.error != nil { break }
            }
            // `F1LAP_SNAPSHOT_SIDEBAR=reopen`: hide the sidebar, size the window, then show the
            // sidebar again — the case where a too-narrow window used to clip it.
            let reopen = ProcessInfo.processInfo.environment["F1LAP_SNAPSHOT_SIDEBAR"] == "reopen"
            let toggleSidebar = #selector(NSSplitViewController.toggleSidebar(_:))
            if reopen {
                NSApp.sendAction(toggleSidebar, to: nil, from: nil)
                try? await Task.sleep(for: .seconds(1))
            }
            if let size = ProcessInfo.processInfo.environment["F1LAP_SNAPSHOT_SIZE"]?
                .split(separator: "x").compactMap({ Double($0) }), size.count == 2 {
                NSApp.windows.first(where: \.isVisible)?
                    .setContentSize(NSSize(width: size[0], height: size[1]))
            }
            if reopen {
                try? await Task.sleep(for: .seconds(1))
                NSApp.sendAction(toggleSidebar, to: nil, from: nil)
            }
            try? await Task.sleep(for: .seconds(1))  // let charts lay out
            if let view = NSApp.windows.first(where: \.isVisible)?.contentView,
               let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) {
                // cacheDisplay skips the window background: paint it first, in the window's
                // appearance, or dark-mode text lands on a transparent (white) canvas.
                NSGraphicsContext.saveGraphicsState()
                NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
                view.effectiveAppearance.performAsCurrentDrawingAppearance {
                    NSColor.windowBackgroundColor.setFill()
                    NSRect(origin: .zero, size: rep.size).fill()
                }
                NSGraphicsContext.restoreGraphicsState()
                view.cacheDisplay(in: view.bounds, to: rep)
                try? rep.representation(using: .png, properties: [:])?
                    .write(to: URL(filePath: path))
            }
            NSApp.terminate(nil)
        }
    }
}
