import Foundation

/// The rated lap and the perfect lap as two cars on one racing line, replayed in time.
///
/// Built from the perfect-lap trace file: both laps' elapsed time on a shared distance grid plus
/// the x/y line. Rows with a missing value, or where either clock does not move forward, are
/// dropped so every lookup is a binary search over strictly increasing times. Speed and pedals
/// are optional (older sidecars lack throttle): without speed a car has no markers and no
/// speed, and the rated car without pedals has no phase.
public struct GhostReplay: Sendable {
    public let distance: [Double]
    public let simTime: [Double]
    public let lapTime: [Double]
    public let x: [Double]
    public let y: [Double]
    public let sim: Channels
    public let lap: Channels
    /// x/y units per metre of lap distance (FastF1 positions are in 1/10 m).
    public let unitsPerMetre: Double

    /// What a car is doing at a point of the lap.
    ///
    /// The rated car's phase is its pedals. The perfect car's is read off its speed instead: the
    /// simulation has no pedal model (its brake almost never binds, and its "throttle" drops to
    /// a placeholder on any speed loss, drag included), so a pedal claim for it would be made up.
    public enum Phase: Sendable, Equatable {
        /// Rated car: on the brake. Perfect car: decelerating at `brakingG` or more.
        case braking
        /// Rated car: off full throttle without braking (a lift, a coast or part throttle).
        case partial
        /// Rated car: throttle at `fullThrottlePct` or more.
        case fullThrottle
        /// Perfect car: gaining speed.
        case accelerating
        /// Perfect car: neither braking nor gaining speed (top speed, mid-corner, a gentle slowdown).
        case steady
    }

    /// A point on the line: a braking point, an apex or a return to full throttle.
    public struct Marker: Sendable, Equatable {
        /// Row in the replay's columns.
        public let row: Int
        public let distanceM: Double
        public let x: Double
        public let y: Double
    }

    /// One car's speed and pedals on the kept rows, plus its braking zones read off the speed
    /// (deceleration reaching `brakingG`, held for `debounceM` and shedding `minDropKmh`, the
    /// same zones as `decel_zones` in src/f1lap/phases.py) with their apexes (the slowest point
    /// before the car gains speed again). Zones are found on speed for both cars, as the perfect
    /// lap has no pedals worth the name.
    public struct Channels: Sendable {
        public let speedKmh: [Double]?
        public let throttle: [Double]?
        public let brake: [Double]?
        /// Where each braking zone starts. Perfect car: where its deceleration reaches
        /// `brakingG`. Rated car: its brake pedal, as its braking colour is (deceleration also
        /// fires on a lift or a coast, metres before the pedal): the first row on the brake from
        /// `pedalLeadM` before the zone to its apex, after the previous apex; none for a zone
        /// taken without the brake. Only a lap without brake data falls back to the deceleration.
        public let braking: [Marker]
        /// Slowest point of each braking zone.
        public let apex: [Marker]
        /// Rated car only: back to full throttle after each apex, judged on its pedal; none when
        /// it lacks pedals or does not get back to full before the next braking zone.
        public let fullThrottle: [Marker]
        /// Deceleration in m/s² from the smoothed speed; nil without speed.
        fileprivate let decel: [Double]?
        fileprivate let isSim: Bool

        fileprivate func phase(_ row: Int) -> Phase? {
            if isSim {
                guard let a = decel?[row], a.isFinite else { return nil }
                let g = GhostReplay.g
                return a >= GhostReplay.brakingG * g ? .braking
                    : a <= -GhostReplay.accelG * g ? .accelerating : .steady
            }
            guard let t = throttle?[row], let b = brake?[row], t.isFinite, b.isFinite else {
                return nil
            }
            if b > 0.5 { return .braking }
            return t >= GhostReplay.fullThrottlePct ? .fullThrottle : .partial
        }
    }

    public struct Car: Sendable, Equatable {
        public let distanceM: Double
        public let x: Double
        public let y: Double
        public let finished: Bool
        public let speedKmh: Double?
        public let phase: Phase?
    }

    public struct Frame: Sendable, Equatable {
        public let sim: Car
        public let lap: Car
        /// Time the rated lap is behind the perfect lap at the rated car's position.
        public let gapS: Double
    }

    /// Speed and pedal changes shorter than this are blips, not braking zones or throttle pickups.
    public static let debounceM = 10.0
    /// A braking zone that sheds less speed than this is not a corner.
    public static let minDropKmh = 10.0
    /// Deceleration (in g) that counts as braking, for both cars.
    public static let brakingG = 0.5
    /// Acceleration (in g) that counts as gaining speed; below it the perfect car is steady.
    public static let accelG = 0.05
    /// Full throttle in %: the same threshold as `FULL_THROTTLE` in src/f1lap/phases.py.
    public static let fullThrottlePct = 95.0
    /// The rated car's brake pedal may come this far before its deceleration-based zone start.
    public static let pedalLeadM = 50.0
    /// Gaussian σ (m) of the smoothing applied to speed before it is differentiated.
    public static let smoothingM = 4.0
    static let g = 9.81

    /// `nil` when the file lacks the replay columns (older sidecars) or has under two usable rows.
    public init?(_ t: Traces) {
        let d = t["distance"], st = t["sim.time"], lt = t["lap.time"], xs = t["x"], ys = t["y"]
        let n = d.count
        guard n > 1, [st, lt, xs, ys].allSatisfy({ $0.count == n }) else { return nil }
        var keep: [Int] = []
        for i in 0..<n where d[i].isFinite && st[i].isFinite && lt[i].isFinite
            && xs[i].isFinite && ys[i].isFinite {
            if let last = keep.last, !(st[i] > st[last] && lt[i] > lt[last]) { continue }
            keep.append(i)
        }
        guard keep.count > 1 else { return nil }
        let dk = keep.map { d[$0] }, xk = keep.map { xs[$0] }, yk = keep.map { ys[$0] }
        /// An optional column on the kept rows; nil when absent or the wrong length.
        func kept(_ name: String) -> [Double]? {
            let c = t[name]
            return c.count == n ? keep.map { c[$0] } : nil
        }
        func marker(_ row: Int) -> Marker {
            Marker(row: row, distanceM: dk[row], x: xk[row], y: yk[row])
        }
        func channels(_ prefix: String) -> Channels {
            let speed = kept(prefix + ".speed")
            let throttle = kept(prefix + ".throttle"), brake = kept(prefix + ".brake")
            let isSim = prefix == "sim"
            guard let speed else {
                return Channels(speedKmh: nil, throttle: throttle, brake: brake, braking: [],
                                apex: [], fullThrottle: [], decel: nil, isSim: isSim)
            }
            let rows = dk.count
            let v = Self.smooth(speed.map { $0 / 3.6 }, dk)  // m/s
            let decel = (0..<rows).map { i in
                let lo = max(i - 1, 0), hi = min(i + 1, rows - 1)
                return -v[i] * (v[hi] - v[lo]) / (dk[hi] - dk[lo])
            }
            let zones = Self.runs(decel.map { $0 >= Self.brakingG * Self.g }, dk) { r in
                let first = speed[r.start...r.end].first(where: \.isFinite)
                let low = speed[r.start...r.end].filter(\.isFinite).min()
                guard let first, let low else { return false }
                return first - low >= Self.minDropKmh
            }
            var apex: [Int] = []
            for (k, z) in zones.enumerated() {
                // Slowest point before the car gains speed again (or the next zone starts).
                let stop = k + 1 < zones.count ? zones[k + 1].start - 1 : rows - 1
                var j = z.end
                while j < stop, !(decel[j + 1] <= -Self.accelG * Self.g) { j += 1 }
                let slowest = (z.start...j).filter { v[$0].isFinite }.min { v[$0] < v[$1] }
                apex.append(slowest ?? z.end)
            }
            var braking: [Marker] = []
            let pedal = isSim || !(brake?.contains(where: \.isFinite) ?? false) ? nil : brake
            for (k, z) in zones.enumerated() {
                guard let pedal else { braking.append(marker(z.start)); continue }
                let from = dk[z.start] - Self.pedalLeadM
                let lo = k > 0 ? apex[k - 1] + 1 : 0
                if let row = (lo...apex[k]).first(where: { dk[$0] >= from && pedal[$0] > 0.5 }) {
                    braking.append(marker(row))
                }
            }
            var full: [Marker] = []
            if !isSim, let throttle, let brake {
                let on = zip(throttle, brake).map { $0 >= Self.fullThrottlePct && !($1 > 0.5) }
                for (k, a) in apex.enumerated() {
                    // First row from the apex that stays at full throttle for `debounceM`.
                    let stop = k + 1 < zones.count ? zones[k + 1].start : rows
                    var i = a
                    while i < stop {
                        guard on[i] else { i += 1; continue }
                        var j = i
                        while j + 1 < rows, on[j + 1], dk[j] - dk[i] < Self.debounceM { j += 1 }
                        if dk[j] - dk[i] >= Self.debounceM || j == rows - 1 {
                            full.append(marker(i))
                            break
                        }
                        i = j + 1
                    }
                }
            }
            return Channels(
                speedKmh: speed, throttle: throttle, brake: brake,
                braking: braking, apex: apex.map(marker),
                fullThrottle: full, decel: decel, isSim: isSim)
        }
        (distance, x, y) = (dk, xk, yk)
        var path = 0.0
        for i in 1..<dk.count { path += hypot(xk[i] - xk[i - 1], yk[i] - yk[i - 1]) }
        unitsPerMetre = dk[dk.count - 1] > dk[0] ? path / (dk[dk.count - 1] - dk[0]) : 1
        simTime = keep.map { st[$0] }
        lapTime = keep.map { lt[$0] }
        sim = channels("sim")
        lap = channels("lap")
    }

    public var simLapTimeS: Double { simTime[simTime.count - 1] - simTime[0] }
    public var lapTimeS: Double { lapTime[lapTime.count - 1] - lapTime[0] }
    /// Until the slower car crosses the line.
    public var durationS: Double { max(simLapTimeS, lapTimeS) }

    /// Both cars `t` seconds after the start.
    public func frame(at t: Double) -> Frame {
        let si = Self.index(simTime, simTime[0] + t)
        let li = Self.index(lapTime, lapTime[0] + t)
        let gap = (value(lapTime, li) - lapTime[0]) - (value(simTime, li) - simTime[0])
        return Frame(sim: car(si, sim, finished: t >= simLapTimeS),
                     lap: car(li, lap, finished: t >= lapTimeS), gapS: gap)
    }

    private func car(_ i: Double, _ c: Channels, finished: Bool) -> Car {
        let speed = c.speedKmh.map { value($0, i) }
        return Car(distanceM: value(distance, i), x: value(x, i), y: value(y, i),
                   finished: finished, speedKmh: speed?.isFinite == true ? speed : nil,
                   phase: c.phase(Int(i.rounded())))
    }

    /// First and last rows of each run of `on` lasting `debounceM`, after dropping the runs
    /// that fail `keep` and then merging those separated by gaps shorter than that. Filtering
    /// first keeps a short run that does not qualify from pulling a zone's start earlier. A run
    /// already under way on the first row is dropped.
    static func runs(_ on: [Bool], _ d: [Double],
                     keep: ((start: Int, end: Int)) -> Bool = { _ in true })
        -> [(start: Int, end: Int)] {
        let n = on.count
        /// Where the run ending on row `j` stops: the next row.
        func endM(_ j: Int) -> Double { d[min(j + 1, n - 1)] }
        var raw: [(start: Int, end: Int)] = []
        var i = 0
        while i < n {
            guard on[i] else { i += 1; continue }
            var j = i
            while j + 1 < n, on[j + 1] { j += 1 }
            raw.append((i, j))
            i = j + 1
        }
        var runs: [(start: Int, end: Int)] = []
        for r in raw where keep(r) {
            if let last = runs.last, d[r.start] - endM(last.end) < debounceM {
                runs[runs.count - 1].end = r.end
            } else {
                runs.append(r)
            }
        }
        return runs.filter { $0.start > 0 && endM($0.end) - d[$0.start] >= debounceM }
    }

    /// `v` smoothed with a Gaussian of σ `smoothingM` cut at 3σ over distance, skipping missing
    /// values (a row with none in reach stays missing); `_smooth` in src/f1lap/phases.py matches.
    static func smooth(_ v: [Double], _ d: [Double]) -> [Double] {
        let reach = 3 * smoothingM
        return v.indices.map { i in
            var sum = 0.0, weight = 0.0
            var j = i
            while j > 0, d[i] - d[j - 1] <= reach { j -= 1 }
            while j < v.count, d[j] - d[i] <= reach {
                if v[j].isFinite {
                    let w = exp(-pow((d[j] - d[i]) / smoothingM, 2) / 2)
                    sum += w * v[j]
                    weight += w
                }
                j += 1
            }
            return weight > 0 ? sum / weight : .nan
        }
    }

    /// Fractional row where the increasing `times` reach `t`, clamped to the lap.
    static func index(_ times: [Double], _ t: Double) -> Double {
        guard t > times[0] else { return 0 }
        guard t < times[times.count - 1] else { return Double(times.count - 1) }
        var lo = 0, hi = times.count - 1  // times[lo] < t <= times[hi]
        while hi - lo > 1 {
            let mid = (lo + hi) / 2
            if times[mid] < t { lo = mid } else { hi = mid }
        }
        return Double(lo) + (t - times[lo]) / (times[hi] - times[lo])
    }

    private func value(_ column: [Double], _ i: Double) -> Double {
        let lo = Int(i), hi = min(lo + 1, column.count - 1)
        return column[lo] + (column[hi] - column[lo]) * (i - Double(lo))
    }
}
