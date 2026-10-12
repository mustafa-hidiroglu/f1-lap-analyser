using System.Text.Json;
using System.Text.Json.Serialization;

namespace F1Lap.Core;

// Mirrors app/Sources/F1LapKit/Models.swift. Decoded with snake_case names: `lap_time_s` -> LapTimeS.

public static class Json
{
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        NumberHandling = JsonNumberHandling.Strict,
    };
}

public sealed record Event(int Round, string Name, string Country, string Location, string Date,
                           string Format, IReadOnlyList<string> Sessions);

public sealed record SessionInfo(int Year, string Event, string Session,
                                 IReadOnlyList<Driver> Drivers, IReadOnlyList<LapRow> Laps)
{
    public IEnumerable<LapRow> LapsOf(string driver) => Laps.Where(l => l.Driver == driver);

    /// The session's fastest lap across all drivers: the quickest valid lap (deleted, inaccurate
    /// and pit laps never count), null when none is valid. Ties go to the first in `Laps` order.
    public LapRow? FastestLap()
    {
        LapRow? best = null;
        foreach (var l in Laps)
            if (l.Valid && l.TimeS is { } t && (best is null || t < best.TimeS!.Value)) best = l;
        return best;
    }
}

public sealed record Driver(string Code, string Team, string? Color, int? Position);

public sealed record LapRow(string Driver, int Lap, double? TimeS, string? Compound,
                            bool PersonalBest, bool Valid);

public sealed record LapLabel(string Driver, int? LapNumber, double? LapTimeS, int? Year);

// MARK: compare

public sealed record CompareResult(
    LapLabel Reference, LapLabel Other, Grid Grid, double FinalDeltaS, double? LapTimeDeltaS,
    double MaxGainS, double MaxGainAtM, double MaxLossS, double MaxLossAtM,
    IReadOnlyList<Sector> Sectors, IReadOnlyList<CornerComparison> Corners,
    IReadOnlyList<LapMetrics> Metrics, CircuitInfo Circuit, TraceFile Traces);

public sealed record Grid(double StepM, int Samples, double LengthM);

public sealed record Sector(string Name, double StartM, double EndM, double RefTimeS,
                            double OtherTimeS, double DeltaS, double RefMinSpeed,
                            double OtherMinSpeed);

public sealed record CornerComparison(
    string Name, double StartM, double EndM, double DeltaS,
    IReadOnlyDictionary<string, double?> PhaseDeltaS,  // approach, braking, mid, exit, straight
    CornerPoints Reference, CornerPoints Other);

public sealed record CornerPoints(
    string Name, double EntryM, double? BrakeOnM, double? BrakeOffM, int BrakeApplications,
    double ApexM, double MidStartM, double MidEndM, double PickupM, double FullThrottleM,
    double EntrySpeed, double ApexSpeed, double ExitSpeed, bool Flat);

public sealed record LapMetrics(
    string Driver, int? LapNumber, double LapTimeS, double FullThrottlePct, double BrakingPct,
    double CoastingPct, double? ThrottleSmoothness, string BrakeSource,
    IReadOnlyList<CornerMetrics> Corners);

public sealed record CornerMetrics(string Name, bool Flat, double? ThrottleSmoothness,
                                   double? ThrottleRampS, int ThrottleLifts, double? PeakDecelG,
                                   double? DecelRiseS);

public sealed record CircuitInfo(string Name, string Source, double RotationDeg,
                                 IReadOnlyList<CircuitCorner> Corners,
                                 IReadOnlyList<CircuitSegment> Segments, CircuitTrack? Track);

public sealed record CircuitCorner(string Label, double DistanceM);

public sealed record CircuitSegment(string Name, double StartM, double EndM);

public sealed record CircuitTrack(IReadOnlyList<double> Distance, IReadOnlyList<double> X,
                                  IReadOnlyList<double> Y);

public sealed record TraceFile(string Path, IReadOnlyList<SoAColumnLayout> Columns);

// MARK: rate

public sealed record Rating(
    string Driver, int? LapNumber, double LapTimeS, double? OfficialLapTimeS,
    double TheoreticalBestS, double TimeLeftS, double UltimateS, double GapToUltimateS,
    double Score, int Drivers, int Laps, IReadOnlyList<RatedSegment> Segments,
    CircuitInfo Circuit, LapLabel Reference,
    /// The lap against the session's simulated perfect lap (null from old sidecars).
    PerfectLap? Perfect);

/// Comparison with the session's perfect (simulated) lap. When the session has none, only
/// `Error` is set.
public sealed record PerfectLap(
    string? Error, double? LapTimeS, double? SimLapTimeS, double? GapS,
    /// Median gap of the session's best laps to the perfect lap: what "good" looks like.
    double? TypicalGapS, IReadOnlyList<PerfectCorner>? Corners,
    IReadOnlyList<Finding>? LapFindings, IReadOnlyList<string>? Summary, TraceFile? Traces);

public sealed record PerfectCorner(string Name, double StartM, double EndM, double LostS,
                                   double TypicalLostS, double ExcessS,
                                   IReadOnlyList<Finding> Findings);

public sealed record Finding(string Kind, string Text, string? Corner,
                             /// Time attributed to this finding; null for context.
                             double? CostS);

public sealed record RatedSegment(string Name, double TimeS, double OwnBestS, int? OwnBestLap,
                                  double LostToOwnBestS, double FieldBestS, string FieldBestBy,
                                  double LostToFieldS, int Rank, double Percentile);

/// A session is identified by year, event (name or round) and session name ("Q", "Race", ...).
public sealed record SessionKey(int Year, string Event, string Session);

/// A lap to analyse: `Lap == null` means the driver's fastest lap.
public sealed record LapRef(string Driver, int? Lap = null)
{
    /// The wire form of `Lap`: the lap number, or "fastest".
    public object LapParam => Lap is { } n ? n : "fastest";
}

public sealed record Ping(int Protocol, string CacheDir);
