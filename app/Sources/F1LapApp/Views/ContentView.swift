import F1LapKit
import SwiftUI

struct ContentView: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        @Bindable var model = model
        NavigationSplitView {
            SessionSidebar()
                .navigationSplitViewColumnWidth(min: 220, ideal: 250)
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
        @Bindable var model = model
        HStack(spacing: 16) {
            LapPicker(title: "Reference", color: Palette.reference, info: model.info,
                      choice: $model.reference)
            LapPicker(title: "Compared", color: Palette.other, info: model.otherSessionInfo,
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
            Spacer()
            Button("Compare", systemImage: "chart.xyaxis.line") { model.compare() }
                .keyboardShortcut(.return, modifiers: .command)
                .disabled(!model.canCompare)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .disabled(model.info == nil)
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
            Picker(title, selection: $choice.driver) {
                Text("Driver").tag(String?.none)
                ForEach(info?.drivers ?? []) { d in
                    Text(d.position.map { "P\($0)  \(d.code)" } ?? d.code).tag(Optional(d.code))
                }
            }
            .labelsHidden()
            .frame(width: 110)
            .onChange(of: choice.driver) { choice.lap = nil }
            Picker("Lap", selection: $choice.lap) {
                Text("Fastest").tag(Int?.none)
                ForEach(model.laps(of: choice.driver, in: info)) { lap in
                    Text("L\(lap.lap)  \(Fmt.lapTime(lap.timeS))\(lap.valid ? "" : "  ✕")"
                         + (lap.personalBest ? "  ★" : ""))
                        .tag(Optional(lap.lap))
                }
            }
            .labelsHidden()
            .frame(width: 160)
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

struct Placeholder: View {
    let text: String
    var body: some View {
        ContentUnavailableView(text, systemImage: "flag.checkered")
    }
}
