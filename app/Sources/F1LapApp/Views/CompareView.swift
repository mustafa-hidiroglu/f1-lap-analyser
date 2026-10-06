import Charts
import F1LapKit
import SwiftUI

struct CompareView: View {
    @Environment(AppModel.self) private var model
    /// Distance under the pointer, shared by every chart and the track map.
    @State private var cursor: Double?
    /// Visible distance window, shared so all charts zoom and scroll together.
    @State private var window: ClosedRange<Double>?
    @State private var selectedCorner: String?

    var body: some View {
        if let c = model.comparison {
            HSplitView {
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        Summary(result: c.result)
                        TraceCharts(c: c, cursor: $cursor, window: $window)
                    }
                    .padding(14)
                }
                .frame(minWidth: 560)
                VSplitView {
                    TrackMap(traces: c.traces, circuit: c.result.circuit, cursor: cursor,
                             window: window)
                        .frame(minHeight: 260)
                    CornerTable(result: c.result, selection: $selectedCorner)
                        .frame(minHeight: 200)
                }
                .frame(minWidth: 340, idealWidth: 420)
            }
            .onChange(of: selectedCorner) {
                guard let name = selectedCorner,
                      let corner = c.result.corners.first(where: { $0.name == name })
                else { return }
                let pad = (corner.endM - corner.startM) * 0.1
                window = max(0, corner.startM - pad)...min(c.traces.lengthM, corner.endM + pad)
            }
        } else if model.info == nil {
            Placeholder(text: "Pick an event and session")
        } else {
            Placeholder(text: "Choose two laps and press Compare (⌘↩)")
        }
    }
}

// MARK: - Summary

private struct Summary: View {
    let result: CompareResult

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 28) {
            stat(Fmt.lap(result.reference), Fmt.lapTime(result.reference.lapTimeS), Palette.reference)
            stat(Fmt.lap(result.other), Fmt.lapTime(result.other.lapTimeS), Palette.other)
            stat("Delta", Fmt.delta(result.lapTimeDeltaS ?? result.finalDeltaS),
                 Palette.delta(result.lapTimeDeltaS ?? result.finalDeltaS))
            stat("Best gain", "\(Fmt.delta(result.maxGainS)) @ \(Int(result.maxGainAtM)) m", .secondary)
            stat("Worst loss", "\(Fmt.delta(result.maxLossS)) @ \(Int(result.maxLossAtM)) m", .secondary)
        }
    }

    private func stat(_ title: String, _ value: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.title3.monospacedDigit().weight(.semibold)).foregroundStyle(color)
        }
    }
}

// MARK: - Synced traces

private struct TraceCharts: View {
    let c: Comparison
    @Binding var cursor: Double?
    @Binding var window: ClosedRange<Double>?

    var body: some View {
        let t = c.traces
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Pointer: \(cursor.map { "\(Int($0)) m" } ?? "—")")
                    .monospacedDigit().foregroundStyle(.secondary)
                Spacer()
                if window != nil {
                    Button("Show full lap", systemImage: "arrow.up.left.and.arrow.down.right") {
                        window = nil
                    }
                }
            }
            .font(.caption)
            panel("Delta (s)", height: 110) {
                LinePlot(t.delta, x: .value("Distance", \.d), y: .value("Delta", \.v))
                    .foregroundStyle(.purple)
                RuleMark(y: .value("Zero", 0)).foregroundStyle(Color.gray.opacity(0.4))
            }
            panel("Speed (km/h)", height: 210, corners: true, yDomain: 0...speedTop) { pair("speed") }
            panel("Throttle (%)", height: 90) { pair("throttle") }
            panel("Brake", height: 60) { pair("brake") }
            panel("Gear", height: 80) { pair("gear") }
        }
    }

    /// Fixed speed ceiling: the corner rules' top annotations otherwise inflate the automatic domain.
    private var speedTop: Double {
        let peak = ((c.traces.ref["speed"] ?? []) + (c.traces.oth["speed"] ?? [])).map(\.v).max() ?? 300
        return (peak / 50).rounded(.up) * 50
    }

    @ChartContentBuilder
    private func pair(_ channel: String) -> some ChartContent {
        LinePlot(
            c.traces.ref[channel] ?? [], x: .value("Distance", \.d), y: .value(channel, \.v),
            series: .value("Lap", \.lap))
            .foregroundStyle(Palette.reference)
        LinePlot(
            c.traces.oth[channel] ?? [], x: .value("Distance", \.d), y: .value(channel, \.v),
            series: .value("Lap", \.lap))
            .foregroundStyle(Palette.other)
    }

    private func panel(
        _ title: String, height: CGFloat, corners: Bool = false, yDomain: ClosedRange<Double>? = nil,
        @ChartContentBuilder content: () -> some ChartContent
    ) -> some View {
        let domain = window ?? 0...c.traces.lengthM
        return VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Chart {
                content()
                if corners {
                    ForEach(c.result.circuit.corners.filter { domain.contains($0.distanceM) }) { corner in
                        RuleMark(x: .value("Corner", corner.distanceM))
                            .foregroundStyle(Color.gray.opacity(0.35))
                            .annotation(position: .top, spacing: 0) {
                                Text(corner.label).font(.caption2).foregroundStyle(.secondary)
                            }
                    }
                }
                if let cursor {
                    RuleMark(x: .value("Pointer", cursor)).foregroundStyle(.primary.opacity(0.5))
                }
            }
            .chartXScale(domain: domain)
            .modifier(FixedYDomain(domain: yDomain))
            .chartXSelection(value: $cursor)
            .chartXAxis { AxisMarks(values: .automatic(desiredCount: 8)) }
            .chartGesture { proxy in
                // Drag to zoom into a distance range; the pointer still tracks on hover.
                DragGesture(minimumDistance: 8)
                    .onEnded { g in
                        guard let a: Double = proxy.value(atX: g.startLocation.x),
                              let b: Double = proxy.value(atX: g.location.x), abs(b - a) > 20
                        else { return }
                        window = max(0, min(a, b))...min(c.traces.lengthM, max(a, b))
                    }
            }
            .frame(height: height)
        }
    }
}

private struct FixedYDomain: ViewModifier {
    let domain: ClosedRange<Double>?

    func body(content: Content) -> some View {
        if let domain { content.chartYScale(domain: domain) } else { content }
    }
}

// MARK: - Track map

struct TrackMap: View {
    let traces: PlotTraces
    let circuit: CircuitInfo
    let cursor: Double?
    let window: ClosedRange<Double>?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("Track — coloured by delta").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Label("gaining", systemImage: "circle.fill").foregroundStyle(.green)
                Label("losing", systemImage: "circle.fill").foregroundStyle(.red)
            }
            .font(.caption2)
            .labelStyle(.titleAndIcon)
            if traces.track.isEmpty {
                Placeholder(text: "No position data")
            } else {
                Canvas { ctx, size in draw(ctx, size) }
                    .accessibilityLabel("Track map")
            }
        }
        .padding(10)
    }

    private func draw(_ ctx: GraphicsContext, _ size: CGSize) {
        let pts = traces.track
        let rot = circuit.rotationDeg * .pi / 180
        let rotated = pts.map { p in
            CGPoint(x: p.x * cos(rot) - p.y * sin(rot), y: p.x * sin(rot) + p.y * cos(rot))
        }
        let xs = rotated.map(\.x), ys = rotated.map(\.y)
        guard let minX = xs.min(), let maxX = xs.max(), let minY = ys.min(), let maxY = ys.max()
        else { return }
        let inset = 18.0
        let scale = min((size.width - 2 * inset) / max(maxX - minX, 1),
                        (size.height - 2 * inset) / max(maxY - minY, 1))
        let ox = (size.width - (maxX - minX) * scale) / 2
        let oy = (size.height - (maxY - minY) * scale) / 2
        func map(_ p: CGPoint) -> CGPoint {  // y up
            CGPoint(x: ox + (p.x - minX) * scale, y: size.height - oy - (p.y - minY) * scale)
        }

        // Saturates at 0.02 s lost or gained per 100 m.
        for i in 1..<rotated.count {
            let gain = pts[i].gain
            let strength = min(1, abs(gain) / 0.02)
            let base: Color = gain < 0 ? .green : .red
            let inWindow = window.map { $0.contains(pts[i].d) } ?? true
            var seg = Path()
            seg.move(to: map(rotated[i - 1]))
            seg.addLine(to: map(rotated[i]))
            ctx.stroke(seg, with: .color(base.mix(with: .gray, by: 1 - strength)
                .opacity(inWindow ? 1 : 0.25)),
                       style: StrokeStyle(lineWidth: inWindow ? 5 : 3, lineCap: .round))
        }

        for corner in circuit.corners {
            guard let i = nearest(corner.distanceM) else { continue }
            let p = map(rotated[i])
            ctx.draw(Text(corner.label).font(.caption2.bold()).foregroundStyle(.secondary),
                     at: CGPoint(x: p.x + 10, y: p.y - 10))
        }
        if let cursor, let i = nearest(cursor) {
            let p = map(rotated[i])
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - 6, y: p.y - 6, width: 12, height: 12)),
                     with: .color(.primary))
        }
        if let start = rotated.first {  // start/finish
            let p = map(start)
            ctx.fill(Path(CGRect(x: p.x - 2, y: p.y - 8, width: 4, height: 16)), with: .color(.primary))
        }
    }

    private func nearest(_ d: Double) -> Int? {
        let pts = traces.track
        guard !pts.isEmpty else { return nil }
        var lo = 0, hi = pts.count - 1
        while lo < hi {
            let mid = (lo + hi) / 2
            if pts[mid].d < d { lo = mid + 1 } else { hi = mid }
        }
        return lo
    }
}

// MARK: - Corner table

private struct CornerTable: View {
    let result: CompareResult
    @Binding var selection: String?

    var body: some View {
        let sectors = Dictionary(result.sectors.map { ($0.name, $0) }, uniquingKeysWith: { a, _ in a })
        Table(result.corners, selection: $selection) {
            TableColumn("Corner") { Text($0.name) }.width(min: 50, ideal: 60)
            TableColumn("Δ") { deltaCell($0.deltaS) }.width(ideal: 58)
            TableColumn("Brake") { deltaCell($0.phaseDeltaS["braking"]) }.width(ideal: 52)
            TableColumn("Mid") { deltaCell($0.phaseDeltaS["mid"]) }.width(ideal: 52)
            TableColumn("Exit") { deltaCell($0.phaseDeltaS["exit"]) }.width(ideal: 52)
            TableColumn("Min km/h") { corner in
                let s = sectors[corner.name]
                Text("\(Fmt.speed(s?.refMinSpeed)) / \(Fmt.speed(s?.otherMinSpeed))")
                    .monospacedDigit()
            }
            .width(ideal: 80)
        }
        .help("Δ = compared − reference: negative means the compared lap is faster. Select a row to zoom the traces.")
    }

    private func deltaCell(_ s: Double?) -> some View {
        Text(Fmt.delta(s)).monospacedDigit().foregroundStyle(Palette.delta(s ?? 0))
    }
}
