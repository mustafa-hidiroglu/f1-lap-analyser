import F1LapKit
import Foundation
import Observation

/// One lap picked in the UI; `lap == nil` is the driver's fastest.
struct LapChoice: Hashable {
    /// A driver, or whoever set the session's fastest lap (resolved against the loaded session,
    /// so it follows session changes; `lap` is unused then).
    enum Pick: Hashable {
        case driver(String)
        case sessionFastest
    }

    var pick: Pick?
    var lap: Int?

    init(pick: Pick? = nil, lap: Int? = nil) {
        self.pick = pick
        self.lap = lap
    }

    init(driver: String?) {
        self.init(pick: driver.map(Pick.driver))
    }

    /// `fastest` (any case) picks the session's fastest lap; anything else is a driver code.
    init(spec: String) {
        self.init(pick: spec.lowercased() == "fastest" ? .sessionFastest : .driver(spec))
    }

    var driver: String? {
        if case .driver(let code) = pick { code } else { nil }
    }

    func ref(in info: SessionInfo?) -> LapRef? {
        switch pick {
        case .driver(let code): LapRef(driver: code, lap: lap)
        case .sessionFastest: info?.fastestLap().map { LapRef(driver: $0.driver, lap: $0.lap) }
        case nil: nil
        }
    }
}

/// A finished comparison, with traces prepared for plotting.
struct Comparison {
    let result: CompareResult
    let traces: PlotTraces
}

@MainActor @Observable
final class AppModel {
    let service: F1LapService

    var year = Calendar.current.component(.year, from: .now) - 1
    private(set) var events: [Event] = []
    var eventRound: Int? { didSet { if eventRound != oldValue { sessionName = nil } } }
    var sessionName: String? { didSet { if sessionName != oldValue { loadSession() } } }
    private(set) var info: SessionInfo?

    var reference = LapChoice()
    var other = LapChoice()
    /// Season for the compared lap; nil = the same session as the reference. Another season
    /// loads the same event (matched by circuit) and session name in that year.
    var otherYear: Int? { didSet { if otherYear != oldValue { loadOtherSession() } } }
    private(set) var otherKey: SessionKey?
    private(set) var otherInfo: SessionInfo?
    private(set) var comparison: Comparison?
    private(set) var rating: Rating?
    private(set) var perfectPlot: PerfectPlot?
    var tab = Tab.compare
    var ratedSide = Side.reference { didSet { if ratedSide != oldValue { rate() } } }

    /// What the sidecar is working on, for the status line; nil when idle.
    private(set) var busy: String?
    /// Latest sidecar progress for the running request (e.g. "Reading 934 laps… 400/934").
    private(set) var progress: SidecarProgress?
    var error: String?

    enum Tab: String, CaseIterable, Identifiable {
        case compare = "Compare", rating = "Rating"
        var id: Self { self }
    }

    enum Side: String, CaseIterable, Identifiable {
        case reference = "Reference", other = "Compared"
        var id: Self { self }
    }

    private var sessionTask: Task<Void, Never>?
    private var otherTask: Task<Void, Never>?
    private var analysisTask: Task<Void, Never>?
    private var ratingTask: Task<Void, Never>?

    init(service: F1LapService) {
        self.service = service
    }

    var event: Event? { events.first { $0.round == eventRound } }

    var key: SessionKey? {
        guard let event, let sessionName else { return nil }
        return SessionKey(year: year, event: event.name, session: sessionName)
    }

    /// Session of the compared lap: its own season's, or the reference session.
    var otherSessionKey: SessionKey? { otherYear == nil ? key : otherKey }
    var otherSessionInfo: SessionInfo? { otherYear == nil ? info : otherInfo }

    var canCompare: Bool {
        guard key != nil, let otherKey = otherSessionKey, let ref = reference.ref(in: info),
              let oth = other.ref(in: otherSessionInfo)
        else { return false }
        return key != otherKey || ref != oth
    }

    /// Seasons with FastF1 telemetry (2018 on), newest first.
    static let seasons = Array((2018...Calendar.current.component(.year, from: .now)).reversed())

    func start() async {
        do {
            _ = try await service.ping()
        } catch {
            self.error = error.localizedDescription
            return
        }
        Task { [service] in
            for await p in service.client.progress { self.progress = p }
        }
        await loadSchedule()
        if let spec = ProcessInfo.processInfo.environment["F1LAP_OPEN"] { await open(spec) }
    }

    /// Development shortcut: `F1LAP_OPEN=2024/Monza/Qualifying/LEC/SAI[/rating]` opens that session
    /// and compares the two drivers' fastest laps; `…/HAM/HAM@2025` takes the compared lap from
    /// the same event in another season; `fastest` in place of a driver picks the session's
    /// fastest lap.
    private func open(_ spec: String) async {
        let parts = spec.split(separator: "/").map(String.init)
        guard parts.count >= 5, let y = Int(parts[0]) else { return }
        if y != year {
            year = y
            await loadSchedule()
        }
        let needle = parts[1].lowercased()
        eventRound = events.first {
            $0.name.lowercased().contains(needle) || $0.location.lowercased().contains(needle)
        }?.round
        sessionName = parts[2]
        await sessionTask?.value
        reference = LapChoice(spec: parts[3])
        let otherSpec = parts[4].split(separator: "@").map(String.init)
        if otherSpec.count == 2, let oy = Int(otherSpec[1]) {
            otherYear = oy
            await otherTask?.value
        }
        other = LapChoice(spec: otherSpec[0])
        if parts.count > 5, parts[5] == "rating" { tab = .rating }
        compare()
    }

    func loadSchedule() async {
        let year = year
        await run("Loading \(year) calendar") {
            let events = try await self.service.schedule(year: year)
            guard year == self.year else { return }
            self.events = events
            if !events.contains(where: { $0.round == self.eventRound }) { self.eventRound = nil }
            // The same round and session in the new season is a different session: load it
            // (otherwise the old season's laps would stay under the new season's key).
            if self.key != nil, let info = self.info, info.year != year { self.loadSession() }
        }
    }

    private func loadSession() {
        sessionTask?.cancel()
        // An in-flight comparison or rating belongs to the previous session.
        analysisTask?.cancel()
        ratingTask?.cancel()
        info = nil
        comparison = nil
        rating = nil
        perfectPlot = nil
        guard let key else { return }
        sessionTask = Task {
            await run("Loading \(key.event) \(key.session) (first load downloads telemetry)") {
                let info = try await self.service.session(key)
                guard !Task.isCancelled, key == self.key else { return }
                self.info = info
                // Default to the top two finishers' fastest laps; a session-fastest pick stays.
                let order = info.drivers.sorted { ($0.position ?? 99) < ($1.position ?? 99) }
                if self.reference.pick != .sessionFastest {
                    self.reference = LapChoice(driver: order.first?.code)
                }
                if self.otherYear == nil, self.other.pick != .sessionFastest {
                    self.other = LapChoice(driver: order.dropFirst().first?.code)
                }
            }
        }
        loadOtherSession()
    }

    /// Finds this event in `otherYear`'s calendar and loads that session for the compared lap.
    private func loadOtherSession() {
        otherTask?.cancel()
        analysisTask?.cancel()  // a comparison against the old compared session is stale
        otherKey = nil
        otherInfo = nil
        comparison = nil
        guard let otherYear, let event, let sessionName else { return }
        otherTask = Task { [sessionTask] in
            await sessionTask?.value  // default to the reference driver once it is chosen
            await run("Finding \(event.name) in \(otherYear)") {
                let events = try await self.service.schedule(year: otherYear)
                // Same circuit; names change (sponsors, "Mexican" → "Mexico City").
                guard let match = events.first(where: { $0.location == event.location })
                    ?? events.first(where: { $0.name == event.name })
                else {
                    throw AppError("No \(event.location) round in \(otherYear).")
                }
                guard match.sessions.contains(sessionName) else {
                    throw AppError("\(match.name) \(otherYear) has no \(sessionName) session.")
                }
                let key = SessionKey(year: otherYear, event: match.name, session: sessionName)
                guard !Task.isCancelled, otherYear == self.otherYear else { return }
                self.otherKey = key
                let info = try await self.service.session(key)
                guard !Task.isCancelled, key == self.otherKey else { return }
                self.otherInfo = info
                // Default to the reference pick: the point is usually one driver (or the
                // session's fastest lap) across years.
                if self.reference.pick == .sessionFastest {
                    self.other = LapChoice(pick: .sessionFastest)
                    return
                }
                if self.other.pick == .sessionFastest { return }
                let codes = Set(info.drivers.map(\.code))
                let driver = self.reference.driver.flatMap { codes.contains($0) ? $0 : nil }
                    ?? info.drivers.min { ($0.position ?? 99) < ($1.position ?? 99) }?.code
                self.other = LapChoice(driver: driver)
            }
        }
    }

    func compare() {
        guard let key, let otherKey = otherSessionKey, let ref = reference.ref(in: info),
              let oth = other.ref(in: otherSessionInfo)
        else { return }
        analysisTask?.cancel()
        analysisTask = Task {
            await run("Comparing \(ref.driver) and \(oth.driver)") {
                let (result, traces) = try await self.service.compare(
                    reference: (key, ref), other: (otherKey, oth))
                let plot = await PlotTraces.prepare(traces, grid: result.grid)
                guard !Task.isCancelled else { return }
                self.comparison = Comparison(result: result, traces: plot)
            }
        }
        rate()
    }

    func rate() {
        let choice = ratedSide == .reference ? reference : other
        let rated = ratedSide == .reference ? (key, info) : (otherSessionKey, otherSessionInfo)
        guard let key = rated.0, let lap = choice.ref(in: rated.1) else { return }
        ratingTask?.cancel()
        ratingTask = Task {
            await run("Rating \(lap.driver) against the \(key.year) field") {
                let rating = try await self.service.rate(key, lap: lap)
                var plot: PerfectPlot?
                // The rating stands even if the perfect-lap trace file cannot be read.
                if let perfect = rating.perfect,
                   let traces = try? await self.service.perfectTraces(perfect) {
                    plot = await PerfectPlot.prepare(traces)
                }
                guard !Task.isCancelled else { return }
                self.rating = rating
                self.perfectPlot = plot
            }
        }
    }

    func laps(of driver: String?, in info: SessionInfo?) -> [LapRow] {
        guard let driver, let info else { return [] }
        return info.laps(of: driver).filter { $0.timeS != nil }
    }

    private func run(_ label: String, _ work: @MainActor () async throws -> Void) async {
        busy = label
        progress = nil
        defer { if busy == label { busy = nil; progress = nil } }
        do {
            try await work()
            error = nil
        } catch is CancellationError {
        } catch {
            if !Task.isCancelled { self.error = error.localizedDescription }
        }
    }
}

struct AppError: LocalizedError {
    let errorDescription: String?
    init(_ message: String) { errorDescription = message }
}
