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
                ScrollView { RatingReport(r: r).padding(14) }
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
            HStack(alignment: .center, spacing: 32) {
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
