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
            HStack {
                Text("Season").foregroundStyle(.secondary)
                Spacer()
                Stepper(String(model.year), value: $model.year, in: 2018...2030)
                    .monospacedDigit()
            }
            .padding(10)
            .onChange(of: model.year) { Task { await model.loadSchedule() } }

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
            LapPicker(title: "Reference", color: Palette.reference, choice: $model.reference)
            LapPicker(title: "Compared", color: Palette.other, choice: $model.other)
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

struct LapPicker: View {
    @Environment(AppModel.self) private var model
    let title: String
    let color: Color
    @Binding var choice: LapChoice

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(color).frame(width: 9, height: 9)
            Text(title).foregroundStyle(.secondary)
            Picker(title, selection: $choice.driver) {
                Text("Driver").tag(String?.none)
                ForEach(model.info?.drivers ?? []) { d in
                    Text(d.position.map { "P\($0)  \(d.code)" } ?? d.code).tag(Optional(d.code))
                }
            }
            .labelsHidden()
            .frame(width: 110)
            .onChange(of: choice.driver) { choice.lap = nil }
            Picker("Lap", selection: $choice.lap) {
                Text("Fastest").tag(Int?.none)
                ForEach(model.laps(of: choice.driver)) { lap in
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
                    ProgressView().controlSize(.small)
                    Text(busy)
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
