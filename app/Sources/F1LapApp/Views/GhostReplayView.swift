import AppKit
import F1LapKit
import SwiftUI

/// The rated lap racing the perfect lap on the track map.
struct GhostReplayView: View {
    let replay: GhostReplay
    let outline: [(x: Double, y: Double)]
    /// Label for the rated car, e.g. "LEC L12".
    let driver: String
    /// Official lap times and gap, shown once the cars finish (the replay's grid stops short of
    /// the line); the replay's own when nil.
    let lapTimeS: Double?, simLapTimeS: Double?, gapS: Double?
    private let rotationDeg: Double
    private let bounds: TrackProjection.Bounds?

    init(replay: GhostReplay, outline: [(x: Double, y: Double)], rotationDeg: Double,
         driver: String, lapTimeS: Double?, simLapTimeS: Double?, gapS: Double?) {
        self.replay = replay
        self.outline = outline
        self.driver = driver
        (self.lapTimeS, self.simLapTimeS, self.gapS) = (lapTimeS, simLapTimeS, gapS)
        self.rotationDeg = rotationDeg
        bounds = TrackProjection.Bounds(x: outline.map(\.x), y: outline.map(\.y),
                                        rotationDeg: rotationDeg)
    }

    /// Playback anchor: replay time `startT` at wall-clock `origin`; `origin` is nil while paused.
    @State private var origin: Date?
    @State private var startT = 0.0
    @State private var speed = 1.0
    /// Playing when a scrub began: resumes on release.
    @State private var resumeAfterScrub = false
    @State private var showMarkers = true
    /// Zoomed in on the cars instead of the whole track.
    @State private var follow = false

    private var playing: Bool { origin != nil }

    private func time(at now: Date) -> Double {
        guard let origin else { return startT }
        return min(startT + now.timeIntervalSince(origin) * speed, replay.durationS)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 12) {
                Text("Ghost replay").foregroundStyle(.secondary)
                Spacer()
                legend
                Toggle("Markers", isOn: $showMarkers)
                Toggle("Follow", isOn: $follow)
            }
            .font(.caption)
            .toggleStyle(.checkbox)
            Group {
                if follow {  // the camera moves, so the track is redrawn every frame
                    TimelineView(.animation(paused: !playing)) { context in
                        let frame = replay.frame(at: time(at: context.date))
                        Canvas { ctx, size in
                            guard let project = followProjection(frame, size) else { return }
                            drawTrack(ctx, size, project)
                            drawCars(ctx, size, project, frame)
                        }
                    }
                } else {  // the track sits outside the timeline so it is drawn once
                    ZStack {
                        Canvas { ctx, size in
                            guard let bounds else { return }
                            drawTrack(ctx, size, TrackProjection(bounds, size: size))
                        }
                        TimelineView(.animation(paused: !playing)) { context in
                            let frame = replay.frame(at: time(at: context.date))
                            Canvas { ctx, size in
                                guard let bounds else { return }
                                drawCars(ctx, size, TrackProjection(bounds, size: size), frame)
                            }
                        }
                    }
                }
            }
            .frame(height: 290)
            .accessibilityElement()
            .accessibilityLabel("Ghost replay")
            .padding(.bottom, 2)
            TimelineView(.animation(paused: !playing)) { context in
                let t = time(at: context.date)
                let frame = replay.frame(at: t)
                VStack(alignment: .leading, spacing: 4) {
                    controls(t, frame)
                    HStack(spacing: 20) {
                        readout("Perfect", Palette.perfect, frame.sim,
                                lapTimeS: simLapTimeS ?? replay.simLapTimeS)
                        readout(driver, Palette.reference, frame.lap,
                                lapTimeS: lapTimeS ?? replay.lapTimeS)
                    }
                }
            }
        }
        .task(id: origin) {  // stop at the end instead of animating a still frame forever
            guard let origin else { return }
            let remaining = (replay.durationS - time(at: .now)) / speed
            try? await Task.sleep(for: .seconds(max(remaining, 0)))
            guard !Task.isCancelled, self.origin == origin else { return }
            startT = replay.durationS
            self.origin = nil
        }
    }

    private func controls(_ t: Double, _ frame: GhostReplay.Frame) -> some View {
        // Replay time runs on the distance grid, a little off the official times shown once a
        // car finishes; the clock never drops below a finished car's official time, and ends on
        // the slower one's.
        let simOfficial = simLapTimeS ?? replay.simLapTimeS
        let lapOfficial = lapTimeS ?? replay.lapTimeS
        let clock = t >= replay.durationS ? max(lapOfficial, simOfficial)
            : max(t, frame.sim.finished ? simOfficial : 0, frame.lap.finished ? lapOfficial : 0)
        let gap = frame.lap.finished ? gapS ?? frame.gapS : frame.gapS
        return HStack(spacing: 12) {
            Button(playing ? "Pause" : "Play", systemImage: playing ? "pause.fill" : "play.fill") {
                if playing {
                    startT = time(at: .now)
                    origin = nil
                } else {
                    if startT >= replay.durationS { startT = 0 }
                    origin = .now
                }
            }
            .labelStyle(.iconOnly)
            .frame(width: 24)
            Picker("Speed", selection: Binding(get: { speed }, set: { v in
                startT = time(at: .now)
                if playing { origin = .now }
                speed = v
            })) {
                ForEach([1.0, 2, 4], id: \.self) { Text("\(Int($0))×").tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 120)
            Slider(value: Binding(get: { t }, set: { v in
                startT = v
                if playing { origin = .now }
            }), in: 0...replay.durationS) { editing in  // pause while dragging
                if editing, playing {
                    startT = time(at: .now)
                    origin = nil
                    resumeAfterScrub = true
                } else if !editing, resumeAfterScrub {
                    resumeAfterScrub = false
                    if startT < replay.durationS { origin = .now }
                }
            }
            Text(Fmt.lapTime(clock)).frame(width: 64, alignment: .trailing)
            Text(Fmt.delta(gap)).foregroundStyle(Palette.delta(gap))
                .frame(width: 56, alignment: .trailing)
        }
        .monospacedDigit()
        .font(.callout)
    }

    /// A car's live speed and phase; its lap time once it has crossed the line.
    private func readout(_ name: String, _ color: Color, _ car: GhostReplay.Car,
                         lapTimeS: Double) -> some View {
        HStack(spacing: 6) {
            Text(name).bold().foregroundStyle(color)
            if car.finished {
                Text(Fmt.lapTime(lapTimeS)).frame(width: 64, alignment: .trailing)
                Text("Finished").foregroundStyle(.secondary).frame(width: 84, alignment: .leading)
            } else {
                Text("\(Fmt.speed(car.speedKmh)) km/h").frame(width: 64, alignment: .trailing)
                Text(car.phase.map(Self.label) ?? "")
                    .foregroundStyle(car.phase.map { Self.fill($0) ?? .secondary } ?? .secondary)
                    .frame(width: 84, alignment: .leading)
            }
        }
        .monospacedDigit()
        .font(.callout)
    }

    private var legend: some View {
        HStack(spacing: 8) {
            Circle().fill(Palette.braking).frame(width: 7, height: 7)
            Text("Braking")
            Circle().fill(Palette.lifting).frame(width: 7, height: 7)
            Text("\(driver) lift / part throttle")
            if showMarkers {
                Rectangle().frame(width: 2, height: 9).padding(.leading, 6)
                Text("Braking point (\(driver): pedal)")
                Circle().stroke(lineWidth: 1.5).frame(width: 6, height: 6)
                Text("Slowest point")
                Circle().frame(width: 6, height: 6)
                Text("\(driver) full throttle")
            }
        }
        .foregroundStyle(.secondary)
    }

    private static func label(_ phase: GhostReplay.Phase) -> String {
        switch phase {
        case .braking: "Braking"
        case .partial: "Lift / part"
        case .fullThrottle: "Full throttle"
        case .accelerating: "Accelerating"
        case .steady: "Steady"
        }
    }

    /// Dot fill for a phase; nil when not slowing, where the car shows its own colour.
    private static func fill(_ phase: GhostReplay.Phase) -> Color? {
        switch phase {
        case .braking: Palette.braking
        case .partial: Palette.lifting
        case .fullThrottle, .accelerating, .steady: nil
        }
    }

    /// A window of ~400 m around both cars, wider when needed to keep them both in view.
    private func followProjection(_ f: GhostReplay.Frame, _ size: CGSize) -> TrackProjection? {
        guard bounds != nil else { return nil }
        let half = max(200 * replay.unitsPerMetre,
                       hypot(f.sim.x - f.lap.x, f.sim.y - f.lap.y) / 2 + 80 * replay.unitsPerMetre)
        let window = TrackProjection.Bounds(around: (f.sim.x + f.lap.x) / 2, (f.sim.y + f.lap.y) / 2,
                                            half: half, rotationDeg: rotationDeg)
        return TrackProjection(window, size: size)
    }

    /// The line, start/finish and (when shown) both cars' braking points (the perfect car's
    /// where its deceleration starts, the rated car's on its brake pedal) and slowest points,
    /// plus the rated car's return to full throttle (the perfect car has no pedal to show). Only
    /// what falls on the canvas is drawn, so a zoomed-in window costs a short path per frame.
    private func drawTrack(_ ctx: GraphicsContext, _ size: CGSize, _ project: TrackProjection) {
        let visible = CGRect(origin: .zero, size: size).insetBy(dx: -30, dy: -30)
        var line = Path()
        var drawing = false
        for o in outline {
            let p = project(o.x, o.y)
            if !visible.contains(p) {
                drawing = false
            } else if drawing {
                line.addLine(to: p)
            } else {
                line.move(to: p)
                drawing = true
            }
        }
        // Opaque, so overlapping round caps at the joins don't show as dots.
        ctx.stroke(line, with: .color(.gray.mix(with: Color(nsColor: .windowBackgroundColor), by: 0.4)),
                   style: StrokeStyle(lineWidth: follow ? 10 : 5, lineCap: .round, lineJoin: .round))
        if let s = outline.first {  // start/finish
            let p = project(s.x, s.y)
            ctx.fill(Path(CGRect(x: p.x - 2, y: p.y - 8, width: 4, height: 16)), with: .color(.primary))
        }
        guard showMarkers else { return }
        // Perfect lap's markers on one side of the line, the rated lap's on the other, so they
        // stay apart where both cars brake at the same spot.
        for (c, color, side) in [(replay.sim, Palette.perfect, 1.0), (replay.lap, Palette.reference, -1.0)] {
            for m in c.braking {
                guard let (p, n) = normal(m, project), visible.contains(p) else { continue }
                var bar = Path()
                bar.move(to: p)
                bar.addLine(to: CGPoint(x: p.x + n.dx * side * 11, y: p.y + n.dy * side * 11))
                ctx.stroke(bar, with: .color(color.opacity(0.85)),
                           style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
            }
            for m in c.apex {
                guard let (p, n) = normal(m, project), visible.contains(p) else { continue }
                let at = CGPoint(x: p.x + n.dx * side * 7, y: p.y + n.dy * side * 7)
                let ring = Path(ellipseIn: CGRect(x: at.x - 3, y: at.y - 3, width: 6, height: 6))
                ctx.stroke(ring, with: .color(color.opacity(0.85)), lineWidth: 1.5)
            }
            for m in c.fullThrottle {
                guard let (p, n) = normal(m, project), visible.contains(p) else { continue }
                let at = CGPoint(x: p.x + n.dx * side * 7, y: p.y + n.dy * side * 7)
                let dot = Path(ellipseIn: CGRect(x: at.x - 3, y: at.y - 3, width: 6, height: 6))
                ctx.fill(dot, with: .color(color.opacity(0.85)))
            }
        }
    }

    /// A marker's point on the canvas and the unit normal to the line there.
    private func normal(_ m: GhostReplay.Marker,
                        _ project: TrackProjection) -> (CGPoint, CGVector)? {
        let last = replay.x.count - 1
        let a = project(replay.x[max(m.row - 1, 0)], replay.y[max(m.row - 1, 0)])
        let b = project(replay.x[min(m.row + 1, last)], replay.y[min(m.row + 1, last)])
        let len = hypot(b.x - a.x, b.y - a.y)
        guard len > 0 else { return nil }
        return (project(m.x, m.y), CGVector(dx: -(b.y - a.y) / len, dy: (b.x - a.x) / len))
    }

    private func drawCars(_ ctx: GraphicsContext, _ size: CGSize, _ project: TrackProjection,
                          _ frame: GhostReplay.Frame) {
        let simLeads = frame.sim.distanceM >= frame.lap.distanceM
        // Rated car drawn last so it sits on top when the two overlap.
        let cars = [(frame.sim, "Perfect", Palette.perfect, simLeads),
                    (frame.lap, driver, Palette.reference, !simLeads)]
        let points = cars.map { project($0.0.x, $0.0.y) }
        // The car's colour as a ring, its pedal phase as the fill.
        for ((car, _, color, _), p) in zip(cars, points) {
            let dot = Path(ellipseIn: CGRect(x: p.x - 7, y: p.y - 7, width: 14, height: 14))
            ctx.fill(dot, with: .color(color))
            if let fill = car.phase.flatMap(Self.fill) {
                ctx.fill(Path(ellipseIn: CGRect(x: p.x - 4, y: p.y - 4, width: 8, height: 8)),
                         with: .color(fill))
            }
            ctx.stroke(dot, with: .color(.white), lineWidth: 1.5)
        }
        // Leader's label to the right of its dot, the other's to the left, each on a chip.
        for ((_, label, color, leads), p) in zip(cars, points) {
            let text = ctx.resolve(Text(label).font(.caption2.bold()).foregroundStyle(color))
            let s = text.measure(in: size)
            let at = CGPoint(x: p.x + (leads ? 11 : -11), y: p.y)
            let chip = CGRect(x: leads ? at.x - 3 : at.x - s.width - 3, y: at.y - s.height / 2 - 1,
                              width: s.width + 6, height: s.height + 2)
            ctx.fill(Path(roundedRect: chip, cornerRadius: 4),
                     with: .color(Color(nsColor: .windowBackgroundColor)))
            ctx.draw(text, at: at, anchor: leads ? .leading : .trailing)
        }
    }
}
