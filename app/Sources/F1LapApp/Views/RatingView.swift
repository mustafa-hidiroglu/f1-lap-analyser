import Charts
import F1LapKit
import SwiftUI

struct RatingView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Picker("Rate", selection: $model.ratedSide) {
                    ForEach(AppModel.Side.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .frame(width: 240)
                Spacer()
                Button("Rate", systemImage: "gauge.with.dots.needle.67percent") { model.rate() }
                    .disabled(model.key == nil)
            }
            .padding(12)
            Divider()
            if let r = model.rating {
                ScrollView {
                    VStack(alignment: .leading, spacing: 24) {
                        if let perfect = r.perfect {
                            PerfectReport(p: perfect, plot: model.perfectPlot,
                                          rotationDeg: r.circuit.rotationDeg,
                                          driver: r.driver + (r.lapNumber.map { " L\($0)" } ?? ""))
                            Divider()
                        }
                        RatingReport(r: r)
                    }
                    .padding(14)
                }
            } else {
                Placeholder(text: model.info == nil ? "Pick an event and session" : "Press Rate")
            }
        }
    }
}

private struct RatingReport: View {
    let r: Rating

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            FlowLayout(spacing: 32, lineSpacing: 12) {
                Gauge(value: r.score, in: 0...100) {
                    Text("Score")
                } currentValueLabel: {
                    Text(String(format: "%.0f", r.score)).monospacedDigit()
                }
                .gaugeStyle(.accessoryCircular)
                .tint(Gradient(colors: [.red, .yellow, .green]))
                .scaleEffect(1.5)
                .frame(width: 80, height: 80)

                stat("\(r.driver)\(r.lapNumber.map { " L\($0)" } ?? "")", Fmt.lapTime(r.lapTimeS))
                stat("Theoretical best", Fmt.lapTime(r.theoreticalBestS))
                stat("Left on the table", Fmt.delta(r.timeLeftS))
                stat("Session ultimate", Fmt.lapTime(r.ultimateS))
                stat("Gap to ultimate", Fmt.delta(r.gapToUltimateS))
            }
            Text("Against \(r.laps) valid laps from \(r.drivers) drivers; segments cut on \(Fmt.lap(r.reference)). Score = mean corner percentile vs other drivers' bests.")
                .font(.caption).foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 4) {
                Text("Time lost per segment (s)").font(.caption).foregroundStyle(.secondary)
                Chart(r.segments) { s in
                    BarMark(x: .value("Segment", s.name), y: .value("Lost", s.lostToFieldS))
                        .foregroundStyle(by: .value("vs", "Field best"))
                        .position(by: .value("vs", "Field best"))
                    BarMark(x: .value("Segment", s.name), y: .value("Lost", s.lostToOwnBestS))
                        .foregroundStyle(by: .value("vs", "Own best"))
                        .position(by: .value("vs", "Own best"))
                }
                .chartForegroundStyleScale(["Field best": Color.red, "Own best": Color.orange])
                .frame(height: 200)
            }

            Grid(alignment: .trailing, horizontalSpacing: 18, verticalSpacing: 6) {
                GridRow {
                    ForEach(["Segment", "Time", "Own best", "Lost", "Field best", "By", "Lost", "Rank",
                             "Pctl"], id: \.self) { Text($0).font(.caption).foregroundStyle(.secondary) }
                }
                Divider()
                ForEach(r.segments) { s in
                    GridRow {
                        Text(s.name).gridColumnAlignment(.leading)
                        Text(String(format: "%.3f", s.timeS))
                        Text(String(format: "%.3f", s.ownBestS)
                             + (s.ownBestLap.map { " (L\($0))" } ?? ""))
                        Text(Fmt.delta(s.lostToOwnBestS)).foregroundStyle(lossColor(s.lostToOwnBestS))
                        Text(String(format: "%.3f", s.fieldBestS))
                        Text(s.fieldBestBy).gridColumnAlignment(.leading)
                        Text(Fmt.delta(s.lostToFieldS)).foregroundStyle(lossColor(s.lostToFieldS))
                        Text("\(s.rank)/\(r.drivers)")
                        Text(String(format: "%.0f", s.percentile))
                    }
                    .monospacedDigit()
                }
            }
            .font(.callout)
        }
    }

    private func lossColor(_ s: Double) -> Color { s > 0.0005 ? .red : .secondary }

    private func stat(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.title3.monospacedDigit().weight(.semibold))
        }
    }
}

// MARK: - vs the perfect lap

private struct PerfectReport: View {
    let p: PerfectLap
    let plot: PerfectPlot?
    let rotationDeg: Double
    /// The rated lap's label, e.g. "LEC L12".
    let driver: String

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("vs the perfect lap").font(.headline)
            if let error = p.error {
                Label("No perfect lap for this session: \(error)", systemImage: "info.circle")
                    .foregroundStyle(.secondary)
            } else {
                FlowLayout(spacing: 32, lineSpacing: 12) {
                    stat("Perfect lap", Fmt.lapTime(p.simLapTimeS))
                    stat("Gap", Fmt.delta(p.gapS))
                    stat("Best laps' gap", Fmt.delta(p.typicalGapS))
                    stat("Left on the table", Fmt.delta(max((p.gapS ?? 0) - (p.typicalGapS ?? 0), 0)))
                }
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array((p.summary ?? []).enumerated()), id: \.offset) { i, line in
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Image(systemName: i == 0 ? "flag.checkered" : "arrow.turn.down.right")
                                .foregroundStyle(i == 0 ? Color.primary : .secondary)
                                .frame(width: 16)
                            Text(line).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .textSelection(.enabled)
                if let plot, let replay = plot.replay {
                    GhostReplayView(replay: replay, outline: plot.outline,
                                    rotationDeg: rotationDeg, driver: driver,
                                    lapTimeS: p.lapTimeS, simLapTimeS: p.simLapTimeS, gapS: p.gapS)
                        .id(p.traces?.path)  // fresh playback state per rating
                }
                if let plot { SpeedVsPerfect(plot: plot, corners: p.corners ?? []) }
                CornerReasons(corners: p.corners ?? [])
            }
        }
    }

    private func stat(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.title3.monospacedDigit().weight(.semibold))
        }
    }
}

private struct SpeedVsPerfect: View {
    let plot: PerfectPlot
    let corners: [PerfectCorner]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Speed vs the perfect lap (km/h)").font(.caption).foregroundStyle(.secondary)
            Chart {
                LinePlot(plot.sim, x: .value("Distance", \.d), y: .value("Speed", \.v),
                         series: .value("Lap", \.lap))
                    .foregroundStyle(by: .value("Lap", "Perfect"))
                LinePlot(plot.lap, x: .value("Distance", \.d), y: .value("Speed", \.v),
                         series: .value("Lap", \.lap))
                    .foregroundStyle(by: .value("Lap", "This lap"))
                ForEach(corners.filter { $0.excessS > 0.1 }) { c in
                    RectangleMark(xStart: .value("From", c.startM), xEnd: .value("To", c.endM))
                        .foregroundStyle(Color.red.opacity(min(0.06 + c.excessS * 0.4, 0.3)))
                }
            }
            .chartForegroundStyleScale(["Perfect": Color.green, "This lap": Palette.reference])
            .chartXScale(domain: 0...max(plot.lengthM, 1))
            .frame(height: 200)
            Text("Shaded: corners where this lap lost over 0.1 s more than the session's best laps.")
                .font(.caption2).foregroundStyle(.secondary)
        }
    }
}

private struct CornerReasons: View {
    let corners: [PerfectCorner]

    var body: some View {
        Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 8) {
            GridRow {
                ForEach(["Corner", "Lost", "Best laps", "Excess", "Why"], id: \.self) {
                    Text($0).font(.caption).foregroundStyle(.secondary)
                }
            }
            Divider()
            ForEach(corners) { c in
                GridRow(alignment: .firstTextBaseline) {
                    Text(c.name)
                    Text(Fmt.delta(c.lostS)).monospacedDigit()
                    Text(Fmt.delta(c.typicalLostS)).monospacedDigit().foregroundStyle(.secondary)
                    Text(Fmt.delta(c.excessS)).monospacedDigit()
                        .foregroundStyle(c.excessS > 0.05 ? .red : .secondary)
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(c.findings, id: \.self) { f in
                            Text(f.text.hasPrefix("\(c.name): ")
                                 ? String(f.text.dropFirst(c.name.count + 2)) : f.text)
                                .foregroundStyle(f.costS == nil ? .secondary : .primary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .gridColumnAlignment(.leading)
                }
                .font(.callout)
            }
        }
    }
}
