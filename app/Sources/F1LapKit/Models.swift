import Foundation

// Decoded with `.convertFromSnakeCase`: `lap_time_s` -> `lapTimeS`.

public struct Event: Decodable, Sendable, Hashable, Identifiable {
    public let round: Int
    public let name: String
    public let country: String
    public let location: String
    public let date: String
    public let format: String
    public let sessions: [String]
    public var id: Int { round }
}

public struct SessionInfo: Decodable, Sendable {
    public let year: Int
    public let event: String
    public let session: String
    public let drivers: [Driver]
    public let laps: [LapRow]

    public func laps(of driver: String) -> [LapRow] {
        laps.filter { $0.driver == driver }
    }
}

public struct Driver: Decodable, Sendable, Hashable, Identifiable {
    public let code: String
    public let team: String
    public let color: String?
    public let position: Int?
    public var id: String { code }
}

public struct LapRow: Decodable, Sendable, Hashable, Identifiable {
    public let driver: String
    public let lap: Int
    public let timeS: Double?
    public let compound: String?
    public let personalBest: Bool
    public let valid: Bool
    public var id: String { "\(driver)-\(lap)" }
}

public struct LapLabel: Decodable, Sendable, Hashable {
    public let driver: String
    public let lapNumber: Int?
    public let lapTimeS: Double?
}

// MARK: - compare

public struct CompareResult: Decodable, Sendable {
    public let reference: LapLabel
    public let other: LapLabel
    public let grid: Grid
    public let finalDeltaS: Double
    public let lapTimeDeltaS: Double?
    public let maxGainS: Double
    public let maxGainAtM: Double
    public let maxLossS: Double
    public let maxLossAtM: Double
    public let sectors: [Sector]
    public let corners: [CornerComparison]
    public let metrics: [LapMetrics]
    public let circuit: CircuitInfo
    public let traces: TraceFile
}

public struct Grid: Decodable, Sendable {
    public let stepM: Double
    public let samples: Int
    public let lengthM: Double
}

public struct Sector: Decodable, Sendable, Identifiable {
    public let name: String
    public let startM: Double
    public let endM: Double
    public let refTimeS: Double
    public let otherTimeS: Double
    public let deltaS: Double
    public let refMinSpeed: Double
    public let otherMinSpeed: Double
    public var id: String { name }
}

public struct CornerComparison: Decodable, Sendable, Identifiable {
    public let name: String
    public let startM: Double
    public let endM: Double
    public let deltaS: Double
    public let phaseDeltaS: [String: Double]  // approach, braking, mid, exit, straight
    public let reference: CornerPoints
    public let other: CornerPoints
    public var id: String { name }
}

public struct CornerPoints: Decodable, Sendable {
    public let name: String
    public let entryM: Double
    public let brakeOnM: Double?
    public let brakeOffM: Double?
    public let brakeApplications: Int
    public let apexM: Double
    public let midStartM: Double
    public let midEndM: Double
    public let pickupM: Double
    public let fullThrottleM: Double
    public let entrySpeed: Double
    public let apexSpeed: Double
    public let exitSpeed: Double
    public let flat: Bool
}

public struct LapMetrics: Decodable, Sendable {
    public let driver: String
    public let lapNumber: Int?
    public let lapTimeS: Double
    public let fullThrottlePct: Double
    public let brakingPct: Double
    public let coastingPct: Double
    public let throttleSmoothness: Double?
    public let brakeSource: String
    public let corners: [CornerMetrics]
}

public struct CornerMetrics: Decodable, Sendable {
    public let name: String
    public let flat: Bool
    public let throttleSmoothness: Double?
    public let throttleRampS: Double?
    public let throttleLifts: Int
    public let peakDecelG: Double?
    public let decelRiseS: Double?
}

public struct CircuitInfo: Decodable, Sendable {
    public struct Corner: Decodable, Sendable, Identifiable {
        public let label: String
        public let distanceM: Double
        public var id: String { label }
    }
    public struct Segment: Decodable, Sendable, Identifiable {
        public let name: String
        public let startM: Double
        public let endM: Double
        public var id: String { name }
    }
    public struct Track: Decodable, Sendable {
        public let distance: [Double]
        public let x: [Double]
        public let y: [Double]
    }
    public let name: String
    public let source: String
    public let rotationDeg: Double
    public let corners: [Corner]
    public let segments: [Segment]
    public let track: Track?
}

public struct TraceFile: Decodable, Sendable {
    public let path: String
    public let columns: [SoAColumnLayout]
}

// MARK: - rate

public struct Rating: Decodable, Sendable {
    public let driver: String
    public let lapNumber: Int?
    public let lapTimeS: Double
    public let officialLapTimeS: Double?
    public let theoreticalBestS: Double
    public let timeLeftS: Double
    public let ultimateS: Double
    public let gapToUltimateS: Double
    public let score: Double
    public let drivers: Int
    public let laps: Int
    public let segments: [RatedSegment]
    public let circuit: CircuitInfo
    public let reference: LapLabel
}

public struct RatedSegment: Decodable, Sendable, Identifiable {
    public let name: String
    public let timeS: Double
    public let ownBestS: Double
    public let ownBestLap: Int?
    public let lostToOwnBestS: Double
    public let fieldBestS: Double
    public let fieldBestBy: String
    public let lostToFieldS: Double
    public let rank: Int
    public let percentile: Double
    public var id: String { name }
}
