import Foundation

/// A session is identified by year, event (name or round) and session name ("Q", "Race", ...).
public struct SessionKey: Codable, Sendable, Hashable {
    public let year: Int
    public let event: String
    public let session: String

    public init(year: Int, event: String, session: String) {
        self.year = year
        self.event = event
        self.session = session
    }
}

/// A lap to analyse: `lap == nil` means the driver's fastest lap.
public struct LapRef: Codable, Sendable, Hashable {
    public let driver: String
    public let lap: Int?

    public init(driver: String, lap: Int? = nil) {
        self.driver = driver
        self.lap = lap
    }

    public func encode(to encoder: any Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(driver, forKey: .driver)
        if let lap { try c.encode(lap, forKey: .lap) } else { try c.encode("fastest", forKey: .lap) }
    }
}

/// Typed API over the sidecar's JSON-RPC methods.
public struct F1LapService: Sendable {
    public let client: SidecarClient

    public init(client: SidecarClient) {
        self.client = client
    }

    public struct Ping: Decodable, Sendable {
        public let `protocol`: Int
        public let cacheDir: String
    }

    public func ping() async throws -> Ping {
        try await client.call("ping", NoParams())
    }

    public func schedule(year: Int) async throws -> [Event] {
        struct P: Encodable, Sendable { let year: Int }
        return try await client.call("schedule", P(year: year))
    }

    public func session(_ key: SessionKey) async throws -> SessionInfo {
        try await client.call("session", key)
    }

    /// Compares two laps of one session and loads the trace file the sidecar wrote.
    public func compare(
        _ key: SessionKey, reference: LapRef, other: LapRef
    ) async throws -> (CompareResult, Traces) {
        try await compare(reference: (key, reference), other: (key, other))
    }

    /// Compares laps from two sessions (e.g. one driver at one track in different years). The
    /// reference session supplies the circuit and corner segments.
    public func compare(
        reference: (SessionKey, LapRef), other: (SessionKey, LapRef)
    ) async throws -> (CompareResult, Traces) {
        struct Side: Encodable, Sendable {
            let key: SessionKey, lap: LapRef
            func encode(to encoder: any Encoder) throws {
                try lap.encode(to: encoder)
                try key.encode(to: encoder)
            }
        }
        struct P: Encodable, Sendable {
            let year: Int, event: String, session: String, reference: Side, other: Side
        }
        let key = reference.0
        let result: CompareResult = try await client.call(
            "compare",
            P(year: key.year, event: key.event, session: key.session,
              reference: Side(key: reference.0, lap: reference.1),
              other: Side(key: other.0, lap: other.1)))
        let traces = try await Self.loadTraces(result.traces)
        return (result, traces)
    }

    public func rate(_ key: SessionKey, lap: LapRef) async throws -> Rating {
        struct P: Encodable, Sendable {
            let year: Int, event: String, session: String, driver: String, lap: LapRef
            func encode(to encoder: any Encoder) throws {
                // `rate` takes driver/lap at top level; reuse LapRef's "fastest" encoding.
                try lap.encode(to: encoder)
                var c = encoder.container(keyedBy: CodingKeys.self)
                try c.encode(year, forKey: .year)
                try c.encode(event, forKey: .event)
                try c.encode(session, forKey: .session)
            }
            enum CodingKeys: String, CodingKey { case year, event, session }
        }
        return try await client.call(
            "rate",
            P(year: key.year, event: key.event, session: key.session, driver: lap.driver, lap: lap))
    }

    /// Memory-maps and decodes a trace file off the caller's actor.
    @concurrent
    static func loadTraces(_ file: TraceFile) async throws -> Traces {
        try Traces.read(URL(fileURLWithPath: file.path), layout: file.columns)
    }
}
