import F1LapKit
import Foundation
import Observation

/// One lap picked in the UI; `lap == nil` is the driver's fastest.
struct LapChoice: Hashable {
    var driver: String?
    var lap: Int?

    var ref: LapRef? { driver.map { LapRef(driver: $0, lap: lap) } }
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
    private(set) var comparison: Comparison?
    private(set) var rating: Rating?
    var tab = Tab.compare
    var ratedSide = Side.reference { didSet { if ratedSide != oldValue { rate() } } }

    /// What the sidecar is working on, for the status line; nil when idle.
    private(set) var busy: String?
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

    var canCompare: Bool { key != nil && reference.ref != nil && other.ref != nil }

    func start() async {
        do {
            _ = try await service.ping()
        } catch {
            self.error = error.localizedDescription
            return
        }
        await loadSchedule()
        if let spec = ProcessInfo.processInfo.environment["F1LAP_OPEN"] { await open(spec) }
    }

    /// Development shortcut: `F1LAP_OPEN=2024/Monza/Qualifying/LEC/SAI[/rating]` opens that session
    /// and compares the two drivers' fastest laps.
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
        reference = LapChoice(driver: parts[3])
        other = LapChoice(driver: parts[4])
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
        }
    }

    private func loadSession() {
        sessionTask?.cancel()
        info = nil
        comparison = nil
        rating = nil
        guard let key else { return }
        sessionTask = Task {
            await run("Loading \(key.event) \(key.session) (first load downloads telemetry)") {
                let info = try await self.service.session(key)
                guard !Task.isCancelled, key == self.key else { return }
                self.info = info
                // Default to the top two finishers' fastest laps.
                let order = info.drivers.sorted { ($0.position ?? 99) < ($1.position ?? 99) }
                self.reference = LapChoice(driver: order.first?.code)
                self.other = LapChoice(driver: order.dropFirst().first?.code)
            }
        }
    }

    func compare() {
        guard let key, let ref = reference.ref, let oth = other.ref else { return }
        analysisTask?.cancel()
        analysisTask = Task {
            await run("Comparing \(ref.driver) and \(oth.driver)") {
                let (result, traces) = try await self.service.compare(key, reference: ref, other: oth)
                let plot = await PlotTraces.prepare(traces, grid: result.grid)
                guard !Task.isCancelled else { return }
                self.comparison = Comparison(result: result, traces: plot)
            }
        }
        rate()
    }

    func rate() {
        let choice = ratedSide == .reference ? reference : other
        guard let key, let lap = choice.ref else { return }
        ratingTask?.cancel()
        ratingTask = Task {
            await run("Rating \(lap.driver) against the field") {
                let rating = try await self.service.rate(key, lap: lap)
                guard !Task.isCancelled else { return }
                self.rating = rating
            }
        }
    }

    func laps(of driver: String?) -> [LapRow] {
        guard let driver, let info else { return [] }
        return info.laps(of: driver).filter { $0.timeS != nil }
    }

    private func run(_ label: String, _ work: @MainActor () async throws -> Void) async {
        busy = label
        defer { if busy == label { busy = nil } }
        do {
            try await work()
            error = nil
        } catch is CancellationError {
        } catch {
            if !Task.isCancelled { self.error = error.localizedDescription }
        }
    }
}
