using F1Lap.Core;
using Xunit;

namespace F1Lap.Core.Tests;

// Port of GhostReplayTests: synthetic lap, perfect car 50 m/s, rated car 40 m/s, straight line.

public class GhostReplayTests
{
    private static readonly double[] Grid = Enumerable.Range(0, 101).Select(i => i * 10.0).ToArray();

    private static Dictionary<string, double[]> Columns(double[]? dist = null)
    {
        var d = dist ?? Grid;
        return new()
        {
            ["distance"] = d,
            ["sim.time"] = d.Select(x => x / 50).ToArray(),
            ["lap.time"] = d.Select(x => x / 40).ToArray(),
            ["x"] = d,
            ["y"] = d.Select(_ => 0.0).ToArray(),
        };
    }

    private static GhostReplay Ghost(Dictionary<string, double[]>? c = null)
    {
        var g = GhostReplay.Create(new Traces(c ?? Columns()));
        Assert.NotNull(g);
        return g;
    }

    private static bool Close(double a, double b) => Math.Abs(a - b) < 1e-9;

    [Fact]
    public void NullWithoutReplayColumns()
    {
        var noX = Columns();
        noX.Remove("x");
        Assert.Null(GhostReplay.Create(new Traces(noX)));
        var shortY = Columns();
        shortY["y"] = shortY["y"][..^1];
        Assert.Null(GhostReplay.Create(new Traces(shortY)));
        Assert.Null(GhostReplay.Create(new Traces(new Dictionary<string, double[]>())));
    }

    [Fact]
    public void DropsNonFiniteAndStalledRows()
    {
        var c = Columns().ToDictionary(kv => kv.Key, kv => kv.Value.ToList());
        foreach (var k in c.Keys) c[k].Insert(52, c[k][51]);  // duplicate row: clocks do not advance
        foreach (var k in c.Keys) c[k].Insert(31, c[k][30]);  // another stalled row
        foreach (var k in c.Keys) c[k].Insert(21, k == "x" ? double.NaN : c[k][20]);  // missing x
        var g = Ghost(c.ToDictionary(kv => kv.Key, kv => kv.Value.ToArray()));
        Assert.Equal(Grid, g.Distance);
        Assert.Equal(Grid, g.X);
    }

    [Fact]
    public void Durations()
    {
        var g = Ghost();
        Assert.True(Close(g.DurationS, 25));
        Assert.True(Close(g.SimLapTimeS, 20));
        Assert.True(Close(g.LapTimeS, 25));
        Assert.True(Close(g.UnitsPerMetre, 1));
    }

    [Fact]
    public void StartFrame()
    {
        var f = Ghost().FrameAt(0);
        Assert.True(f.Sim.DistanceM == 0 && f.Lap.DistanceM == 0);
        Assert.True(Close(f.GapS, 0));
        Assert.True(!f.Sim.Finished && !f.Lap.Finished);
    }

    [Fact]
    public void MidFrame()
    {
        var f = Ghost().FrameAt(10);
        Assert.True(Close(f.Sim.DistanceM, 500) && Close(f.Sim.X, 500) && f.Sim.Y == 0);
        Assert.True(Close(f.Lap.DistanceM, 400) && Close(f.Lap.X, 400));
        Assert.True(Close(f.GapS, 2));
        Assert.True(!f.Sim.Finished && !f.Lap.Finished);
    }

    [Fact]
    public void PerfectCarFinishesFirst()
    {
        var f = Ghost().FrameAt(20);
        Assert.True(Close(f.Sim.DistanceM, 1000) && f.Sim.Finished);
        Assert.True(Close(f.Lap.DistanceM, 800) && !f.Lap.Finished);
        Assert.True(Close(f.GapS, 4));
    }

    [Fact]
    public void PastTheEnd()
    {
        var f = Ghost().FrameAt(30);
        Assert.True(Close(f.Sim.DistanceM, 1000) && f.Sim.Finished);
        Assert.True(Close(f.Lap.DistanceM, 1000) && f.Lap.Finished);
        Assert.True(Close(f.GapS, 5));
    }

    [Fact]
    public void InterpolatesAndClamps()
    {
        var g = Ghost();
        var f = g.FrameAt(10.1);
        Assert.True(Close(f.Lap.DistanceM, 404) && Close(f.Lap.X, 404));
        Assert.True(Close(f.Sim.DistanceM, 505));
        var before = g.FrameAt(-3);
        Assert.True(before.Sim.DistanceM == 0 && before.Lap.DistanceM == 0);
        Assert.True(Close(before.GapS, 0) && !before.Sim.Finished);
    }

    /// Speed (m/s) on a 1 m grid to 1000 m: 80 m/s, easing off at 0.2 g from `drift`, 4 g from
    /// `brake` down to 30 m/s (the apex), then 1 g back up to 80.
    private static (double[] V, double ApexM) Profile(double drift, double brake)
    {
        const double g = 9.81;
        var v = new List<double> { 80.0 };
        double apexM = 0;
        bool slowed = false;
        for (int s = 1; s <= 1000; s++)
        {
            double d = s - 1, was = v[s - 1];
            double a = slowed ? (was < 80 ? g : 0) : d >= brake ? -4 * g : d >= drift ? -0.2 * g : 0;
            double next = Math.Sqrt(Math.Max(was * was + 2 * a, 0));
            if (!slowed && next <= 30) { next = 30; slowed = true; apexM = s; }
            v.Add(Math.Min(next, 80));
        }
        return ([.. v], apexM);
    }

    /// Elapsed time on the 1 m grid at speeds `v` (m/s).
    private static double[] Times(double[] v)
    {
        var t = new List<double> { 0.0 };
        for (int i = 1; i < v.Length; i++) t.Add(t[i - 1] + 2 / (v[i] + v[i - 1]));
        return [.. t];
    }

    private static bool In(double x, double lo, double hi) => x >= lo && x < hi;

    /// Perfect car like the real base: no brake at all, its "throttle" at 50 from where it
    /// starts losing speed (a 0.2 g drift from 300 m) to the apex; the real slowdown is 4 g from
    /// 360 m. Rated car: brakes at 4 g from 340 m, part throttle from its apex for 30 m with a
    /// 5 m blip of full throttle, then flat out.
    private static (Dictionary<string, double[]> C, double[] SimT, double[] LapT,
                    double SimApexM, double LapApexM) Corner()
    {
        var d = Enumerable.Range(0, 1001).Select(i => (double)i).ToArray();
        var (sv, sa) = Profile(drift: 300, brake: 360);
        var (lv, la) = Profile(drift: 340, brake: 340);
        var simT = Times(sv);
        var lapT = Times(lv);
        var c = new Dictionary<string, double[]>
        {
            ["distance"] = d,
            ["sim.time"] = simT,
            ["lap.time"] = lapT,
            ["x"] = d,
            ["y"] = d.Select(_ => 0.0).ToArray(),
            ["sim.speed"] = sv.Select(x => x * 3.6).ToArray(),
            ["lap.speed"] = lv.Select(x => x * 3.6).ToArray(),
            ["sim.brake"] = d.Select(_ => 0.0).ToArray(),
            ["sim.throttle"] = d.Select(x => In(x, 300, sa) ? 50.0 : 100.0).ToArray(),
            ["lap.brake"] = d.Select(x => In(x, 340, la) ? 1.0 : 0.0).ToArray(),
            ["lap.throttle"] = d.Select(x =>
                In(x, 340, la) ? 0.0
                : In(x, la, la + 30) && !In(x, la + 10, la + 15) ? 40.0 : 100.0).ToArray(),
        };
        return (c, simT, lapT, sa, la);
    }

    [Fact]
    public void WithoutSpeedOrPedals()
    {
        var g = Ghost();
        var f = g.FrameAt(10);
        Assert.True(f.Sim.SpeedKmh is null && f.Sim.Phase is null);
        Assert.True(f.Lap.SpeedKmh is null && f.Lap.Phase is null);
        Assert.True(g.Sim.Braking.Count == 0 && g.Sim.Apex.Count == 0 && g.Lap.FullThrottle.Count == 0);
        // No rated-car throttle column, a wrong-length perfect-car one: the perfect car's phase
        // and both cars' markers come from speed; the rated car has no phase or pedal marker.
        var (c, simT, _, _, _) = Corner();
        c.Remove("lap.throttle");
        c["sim.throttle"] = c["sim.throttle"][..^1];
        var h = Ghost(c);
        var at = h.FrameAt(simT[400]);
        Assert.True(at.Sim.Phase == GhostReplay.Phase.Braking && at.Lap.Phase is null && at.Sim.SpeedKmh is not null);
        Assert.True(h.Sim.Throttle is null && h.Lap.Brake is not null);
        Assert.True(h.Lap.Braking.Count == 1 && h.Sim.Braking.Count == 1 && h.Lap.FullThrottle.Count == 0);
    }

    [Fact]
    public void BrakingPointIsTheRealDecelerationNotTheDrift()
    {
        var (c, _, _, simApex, lapApex) = Corner();
        var g = Ghost(c);
        // Smoothing (sigma 4 m) lets the 0.5 g threshold lead the 4 g onset by a few metres.
        Assert.True(g.Sim.Braking.Count == 1 && g.Sim.Braking[0].DistanceM is >= 352 and <= 360);
        // The rated car's braking point is its pedal.
        Assert.Equal([340.0], g.Lap.Braking.Select(m => m.DistanceM));
        Assert.True(g.Sim.Apex.Count == 1 && Math.Abs(g.Sim.Apex[0].DistanceM - simApex) <= 3);
        Assert.True(g.Lap.Apex.Count == 1 && Math.Abs(g.Lap.Apex[0].DistanceM - lapApex) <= 3);
        // Only the rated car has a pedal marker, and the 5 m blip after its apex is not it.
        Assert.Empty(g.Sim.FullThrottle);
        Assert.Equal([lapApex + 30], g.Lap.FullThrottle.Select(m => m.DistanceM));
    }

    [Fact]
    public void RatedBrakingPointIsThePedalNotTheLift()
    {
        var (c, _, _, _, lapApex) = Corner();
        // Decelerating from ~336 m (lifting) but on the brake only from 370 m.
        c["lap.brake"] = c["distance"].Select(x => In(x, 370, lapApex) ? 1.0 : 0.0).ToArray();
        Assert.Equal([370.0], Ghost(c).Lap.Braking.Select(m => m.DistanceM));
        // A pedal more than `PedalLeadM` before the zone is another event: no braking point.
        c["lap.brake"] = c["distance"].Select(x => In(x, 200, 250) ? 1.0 : 0.0).ToArray();
        Assert.Empty(Ghost(c).Lap.Braking);
    }

    [Fact]
    public void RatedBrakingPointWithoutBrakeDataIsTheDeceleration()
    {
        var (c, _, _, _, _) = Corner();
        c["lap.brake"] = c["lap.brake"].Select(_ => double.NaN).ToArray();
        var g = Ghost(c);
        Assert.True(g.Lap.Braking.Count == 1 && g.Lap.Braking[0].DistanceM is >= 332 and <= 340);
        c.Remove("lap.brake");
        Assert.Equal(g.Lap.Braking.Select(m => m.DistanceM), Ghost(c).Lap.Braking.Select(m => m.DistanceM));
    }

    /// Shared fixture: tests/test_phases.py::test_decel_zones_match_the_app asserts the same
    /// starts. 80 m/s on a 1 m grid to 600 m: 2 g already under way at 0 m (dropped), a 1 g lift
    /// over 200-215 m shedding ~7 km/h (dropped before merging, so it cannot pull the next start
    /// to 200 m), 4 g over 228-268 m, 2 g over 450-470 m.
    [Fact]
    public void DecelZonesMatchPython()
    {
        const double g = 9.81;
        static double Accel(int m) =>
            m < 30 ? -2 * g : m is >= 200 and < 215 ? -g : m is >= 228 and < 268 ? -4 * g
                : m is >= 450 and < 470 ? -2 * g : 0;
        var v = new List<double> { 80.0 };
        for (int s = 1; s <= 600; s++) v.Add(Math.Sqrt(Math.Max(v[s - 1] * v[s - 1] + 2 * Accel(s - 1), 0)));
        var d = Enumerable.Range(0, 601).Select(i => (double)i).ToArray();
        var t = Times([.. v]);
        var r = Ghost(new()
        {
            ["distance"] = d, ["sim.time"] = t, ["lap.time"] = t, ["x"] = d,
            ["y"] = d.Select(_ => 0.0).ToArray(), ["sim.speed"] = v.Select(x => x * 3.6).ToArray(),
        });
        Assert.Equal([224.0, 448.0], r.Sim.Braking.Select(m => m.DistanceM));
    }

    [Fact]
    public void BrakingPointSurvivesMissingSpeedAtItsStart()
    {
        var (c, _, _, _, _) = Corner();
        for (int i = 348; i <= 358; i++) c["sim.speed"][i] = double.NaN;
        var g = Ghost(c);
        Assert.True(g.Sim.Braking.Count == 1 && g.Sim.Braking[0].DistanceM is >= 345 and <= 362);
    }

    [Fact]
    public void Phases()
    {
        var (c, simT, lapT, _, lapApex) = Corner();
        var g = Ghost(c);
        GhostReplay.Phase? Sim(int m) => g.FrameAt(simT[m]).Sim.Phase;
        GhostReplay.Phase? Lap(int m) => g.FrameAt(lapT[m]).Lap.Phase;
        // The perfect car's phase is its speed: the 0.2 g drift is not braking.
        Assert.True(Sim(100) == GhostReplay.Phase.Steady && Sim(330) == GhostReplay.Phase.Steady
                    && Sim(400) == GhostReplay.Phase.Braking);
        Assert.True(Sim(600) == GhostReplay.Phase.Accelerating && Sim(900) == GhostReplay.Phase.Steady);
        int a = (int)lapApex;
        Assert.True(Lap(100) == GhostReplay.Phase.FullThrottle && Lap(380) == GhostReplay.Phase.Braking
                    && Lap(a + 5) == GhostReplay.Phase.Partial);
        Assert.True(Lap(800) == GhostReplay.Phase.FullThrottle);
        Assert.True(Close(g.FrameAt(simT[100]).Sim.SpeedKmh!.Value, 288));
    }

    [Fact]
    public void MissingThrottleHasNoPhase()
    {
        var (c, simT, lapT, _, _) = Corner();
        c["lap.throttle"] = c["lap.throttle"].Select(_ => double.NaN).ToArray();  // what the sidecar writes
        var g = Ghost(c);
        Assert.True(g.FrameAt(lapT[380]).Lap.Phase is null && g.FrameAt(lapT[800]).Lap.Phase is null);
        Assert.True(g.Lap.FullThrottle.Count == 0 && g.Lap.Braking.Count == 1);
        Assert.Equal(GhostReplay.Phase.Braking, g.FrameAt(simT[400]).Sim.Phase);
    }

    [Fact]
    public void RunsFilterBeforeMerging()
    {
        var d = Enumerable.Range(0, 100).Select(i => (double)i).ToArray();
        var on = Enumerable.Range(0, 100).Select(i => i is >= 20 and <= 24 || i is >= 30 and <= 60).ToArray();
        // Merged, the short run would pull the zone's start to 20 m.
        Assert.Equal([20], GhostReplay.Runs(on, d).Select(r => r.Start));
        var runs = GhostReplay.Runs(on, d, r => r.Start != 20);
        Assert.Equal([30], runs.Select(r => r.Start));
        Assert.Equal([60], runs.Select(r => r.End));
    }

    [Fact]
    public void RunsAreDebounced()
    {
        var d = Enumerable.Range(0, 200).Select(i => (double)i).ToArray();  // 1 m grid
        var on = Enumerable.Range(0, 200).Select(i =>
            i <= 5  // already off at the start: no run
            || i is >= 20 and <= 49 || i is >= 55 and <= 70  // 5 m back on: one run
            || i is >= 100 and <= 104  // 5 m blip
            || i >= 150).ToArray();  // to the end of the lap
        var runs = GhostReplay.Runs(on, d);
        Assert.Equal([20, 150], runs.Select(r => r.Start));
        Assert.Equal([70, 199], runs.Select(r => r.End));
    }
}
