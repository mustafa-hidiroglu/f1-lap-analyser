import F1LapKit
import SwiftUI

struct ContentView: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        @Bindable var model = model
        NavigationSplitView {
            SessionSidebar()
                .navigationSplitViewColumnWidth(min: 220, ideal: 250, max: 340)
        } detail: {
            VStack(spacing: 0) {
                LapBar()
                Divider()
                Group {
                    switch model.tab {
                    case .compare: CompareView()
                    case .rating: RatingView()
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                StatusBar()
            }
            // An honest minimum: everything in the detail column fits (or wraps) in this width, so
            // the window's minimum is sidebar + detail and opening the sidebar never clips it.
            .frame(minWidth: AppLayout.detailMinWidth, minHeight: 640)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Picker("View", selection: $model.tab) {
                        ForEach(AppModel.Tab.allCases) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented)
                }
            }
        }
    }
}

// MARK: - Sidebar: season, event, session

struct SessionSidebar: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        VStack(alignment: .leading, spacing: 0) {
            Picker("Season", selection: $model.year) {
                ForEach(AppModel.seasons, id: \.self) { Text(String($0)).tag($0) }
            }
            .pickerStyle(.menu)
            .padding(10)
            .onChange(of: model.year) {
                if model.otherYear == model.year { model.otherYear = nil }
                Task { await model.loadSchedule() }
            }

            List(selection: $model.eventRound) {
                ForEach(model.events) { event in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(event.name).lineLimit(1)
                        Text("R\(event.round) · \(event.location) · \(event.date)")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    .tag(event.round)
                }
            }

            if let event = model.event {
                Divider()
                Picker("Session", selection: $model.sessionName) {
                    Text("Choose…").tag(String?.none)
                    ForEach(event.sessions, id: \.self) { Text($0).tag(Optional($0)) }
                }
                .padding(10)
            }
        }
    }
}

// MARK: - Lap pickers

struct LapBar: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        // One row when it fits; otherwise the compared lap drops onto a second row, so the bar
        // never forces the detail column wider than the window.
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 16) {
                referencePicker
                comparedPicker
                Spacer(minLength: 0)
                compareButton
            }
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 16) {
                    referencePicker
                    Spacer(minLength: 0)
                    compareButton
                }
                comparedPicker
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .disabled(model.info == nil)
    }

    private var referencePicker: some View {
        @Bindable var model = model
        return LapPicker(title: "Reference", color: Palette.reference, info: model.info,
                         choice: $model.reference)
    }

    private var comparedPicker: some View {
        @Bindable var model = model
        return LapPicker(title: "Compared", color: Palette.other, info: model.otherSessionInfo,
                         choice: $model.other) {
            Picker("Season", selection: $model.otherYear) {
                Text("Same session").tag(Int?.none)
                Divider()
                ForEach(AppModel.seasons.filter { $0 != model.year }, id: \.self) {
                    Text(String($0)).tag(Optional($0))
                }
            }
            .labelsHidden()
            .frame(width: 130)
            .help("Compare against the same event in another season")
        }
    }

    private var compareButton: some View {
        Button("Compare", systemImage: "chart.xyaxis.line") { model.compare() }
            .keyboardShortcut(.return, modifiers: .command)
            .disabled(!model.canCompare)
    }
}

struct LapPicker<Accessory: View>: View {
    @Environment(AppModel.self) private var model
    let title: String
    let color: Color
    let info: SessionInfo?
    @Binding var choice: LapChoice
    @ViewBuilder var accessory: Accessory

    init(title: String, color: Color, info: SessionInfo?, choice: Binding<LapChoice>,
         @ViewBuilder accessory: () -> Accessory = { EmptyView() }) {
        self.title = title
        self.color = color
        self.info = info
        _choice = choice
        self.accessory = accessory()
    }

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(color).frame(width: 9, height: 9)
            Text(title).foregroundStyle(.secondary).fixedSize()
            accessory
            Picker(title, selection: $choice.pick) {
                Text("Driver").tag(LapChoice.Pick?.none)
                Text("★ Fastest").tag(Optional(LapChoice.Pick.sessionFastest))
                Divider()
                ForEach(info?.drivers ?? []) { d in
                    Text(d.position.map { "P\($0)  \(d.code)" } ?? d.code)
                        .tag(Optional(LapChoice.Pick.driver(d.code)))
                }
            }
            .labelsHidden()
            .frame(width: 110)
            .help("★ Fastest: the session's fastest valid lap, whoever set it")
            .onChange(of: choice.pick) { choice.lap = nil }
            // The session-fastest pick fixes the lap, so this only shows who set it.
            Picker("Lap", selection: $choice.lap) {
                if choice.pick == .sessionFastest {
                    let best = info?.fastestLap()
                    Text(best.map { "\($0.driver)  L\($0.lap)  \(Fmt.lapTime($0.timeS))" }
                         ?? (info == nil ? "Loading…" : "No valid lap"))
                        .tag(Int?.none)
                } else {
                    Text("Fastest").tag(Int?.none)
                    ForEach(model.laps(of: choice.driver, in: info)) { lap in
                        Text("L\(lap.lap)  \(Fmt.lapTime(lap.timeS))\(lap.valid ? "" : "  ✕")"
                             + (lap.personalBest ? "  ★" : ""))
                            .tag(Optional(lap.lap))
                    }
                }
            }
            .labelsHidden()
            .frame(width: 160)
            .disabled(choice.pick == .sessionFastest)
        }
    }
}

// MARK: - Status

struct StatusBar: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if model.busy != nil || model.error != nil {
            HStack(spacing: 8) {
                if let busy = model.busy {
                    if let p = model.progress, let done = p.done, let total = p.total, total > 0 {
                        ProgressView(value: Double(done), total: Double(total))
                            .frame(width: 120)
                        Text("\(p.message) — \(done)/\(total)").monospacedDigit()
                    } else {
                        ProgressView().controlSize(.small)
                        Text(model.progress?.message ?? busy)
                    }
                } else if let error = model.error {
                    Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.yellow)
                    Text(error).lineLimit(2).textSelection(.enabled)
                    Spacer()
                    Button("Dismiss") { model.error = nil }.buttonStyle(.borderless)
                }
                Spacer()
            }
            .font(.callout)
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(.bar)
        }
    }
}

enum AppLayout {
    /// Narrowest the detail column gets: the Compare tab's chart pane (440) and track pane (300)
    /// minimums plus the divider; everything else in the column fits or wraps in that.
    static let detailMinWidth: CGFloat = 760
}

struct Placeholder: View {
    let text: String
    var body: some View {
        ContentUnavailableView(text, systemImage: "flag.checkered")
    }
}
