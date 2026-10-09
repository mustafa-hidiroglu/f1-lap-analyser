import F1LapKit
import Foundation

struct Pt: Sendable {
    let d: Double
    let v: Double
    /// Series key, so two laps in one chart are drawn as separate lines rather than one polyline.
    var lap = ""
}

/// Trace columns thinned for plotting (~1500 points per series) plus the full-resolution
/// track outline, built once per comparison off the main actor.
struct PlotTraces: Sendable {
    let lengthM: Double
    let delta: [Pt]
    let ref: [String: [Pt]]
    let oth: [String: [Pt]]
    /// Track outline on the reference line, with the local delta slope (s per 100 m) per point.
    let track: [(x: Double, y: Double, d: Double, gain: Double)]

    static let channels = ["speed", "throttle", "brake", "gear"]

    @concurrent
    static func prepare(_ t: Traces, grid: Grid) async -> PlotTraces {
        let distance = t["distance"]
        let n = distance.count
        let stride = max(1, n / 1500)
        func thin(_ column: [Double], lap: String = "") -> [Pt] {
            Swift.stride(from: 0, to: min(n, column.count), by: stride).compactMap {
                column[$0].isFinite ? Pt(d: distance[$0], v: column[$0], lap: lap) : nil
            }
        }
        var ref: [String: [Pt]] = [:]
        var oth: [String: [Pt]] = [:]
        for c in channels {
            ref[c] = thin(t["ref.\(c)"], lap: "ref")
            oth[c] = thin(t["oth.\(c)"], lap: "oth")
        }

        let x = t["ref.x"], y = t["ref.y"], delta = t["delta"]
        var track: [(Double, Double, Double, Double)] = []
        if x.count == n, y.count == n, delta.count == n, n > 0 {
            let step = max(1, Int((5 / grid.stepM).rounded()))   // 5 m outline
            let half = max(1, Int((25 / grid.stepM).rounded()))  // ±25 m slope window
            for i in Swift.stride(from: 0, to: n, by: step) where x[i].isFinite && y[i].isFinite {
                let a = max(0, i - half), b = min(n - 1, i + half)
                let slope = (delta[b] - delta[a]) / max(distance[b] - distance[a], 1) * 100
                track.append((x[i], y[i], distance[i], slope.isFinite ? slope : 0))
            }
        }
        return PlotTraces(
            lengthM: grid.lengthM, delta: thin(delta), ref: ref, oth: oth,
            track: track.map { (x: $0.0, y: $0.1, d: $0.2, gain: $0.3) })
    }
}

/// The rated lap against the perfect lap, thinned for plotting.
struct PerfectPlot: Sendable {
    let lengthM: Double
    let sim: [Pt]
    let lap: [Pt]
    let delta: [Pt]
    /// Both laps as cars on the racing line; nil when the trace file has no x/y.
    let replay: GhostReplay?
    /// The replay's line thinned to ~5 m, for drawing the track.
    let outline: [(x: Double, y: Double)]

    @concurrent
    static func prepare(_ t: Traces) async -> PerfectPlot {
        let distance = t["distance"]
        let n = distance.count
        let stride = max(1, n / 1500)
        func thin(_ column: [Double], lap: String) -> [Pt] {
            Swift.stride(from: 0, to: min(n, column.count), by: stride).compactMap {
                column[$0].isFinite ? Pt(d: distance[$0], v: column[$0], lap: lap) : nil
            }
        }
        let replay = GhostReplay(t)
        var outline: [(x: Double, y: Double)] = []
        if let r = replay {
            var last = -Double.infinity
            for i in r.distance.indices where r.distance[i] - last >= 5 || i == r.distance.count - 1 {
                outline.append((r.x[i], r.y[i]))
                last = r.distance[i]
            }
        }
        return PerfectPlot(
            lengthM: distance.last ?? 0, sim: thin(t["sim.speed"], lap: "Perfect"),
            lap: thin(t["lap.speed"], lap: "Lap"), delta: thin(t["delta"], lap: "Delta"),
            replay: replay, outline: outline)
    }
}
