namespace F1Lap.Core;

/// A plotted point: distance and value.
public readonly record struct Pt(double D, double V);

/// A point of the track outline with the local delta slope (s per 100 m).
public readonly record struct TrackPt(double X, double Y, double D, double Gain);

/// Trace columns thinned for plotting (~1500 points per series) plus the track outline, built
/// once per comparison off the UI thread (mirrors PlotTraces.swift).
public sealed record PlotTraces(
    double LengthM, IReadOnlyList<Pt> Delta,
    IReadOnlyDictionary<string, IReadOnlyList<Pt>> Ref,
    IReadOnlyDictionary<string, IReadOnlyList<Pt>> Oth,
    IReadOnlyList<TrackPt> Track)
{
    public static readonly string[] Channels = ["speed", "throttle", "brake", "gear"];

    public static PlotTraces Prepare(Traces t, Grid grid)
    {
        var distance = t["distance"];
        int n = distance.Length;
        var refs = new Dictionary<string, IReadOnlyList<Pt>>();
        var oths = new Dictionary<string, IReadOnlyList<Pt>>();
        foreach (var c in Channels)
        {
            refs[c] = Thin(distance, t[$"ref.{c}"]);
            oths[c] = Thin(distance, t[$"oth.{c}"]);
        }

        double[] x = t["ref.x"], y = t["ref.y"], delta = t["delta"];
        var track = new List<TrackPt>();
        if (x.Length == n && y.Length == n && delta.Length == n && n > 0)
        {
            int step = Math.Max(1, (int)Math.Round(5 / grid.StepM));   // 5 m outline
            int half = Math.Max(1, (int)Math.Round(25 / grid.StepM));  // ±25 m slope window
            for (int i = 0; i < n; i += step)
            {
                if (!double.IsFinite(x[i]) || !double.IsFinite(y[i])) continue;
                int a = Math.Max(0, i - half), b = Math.Min(n - 1, i + half);
                double slope = (delta[b] - delta[a]) / Math.Max(distance[b] - distance[a], 1) * 100;
                track.Add(new TrackPt(x[i], y[i], distance[i], double.IsFinite(slope) ? slope : 0));
            }
        }
        return new PlotTraces(grid.LengthM, Thin(distance, delta), refs, oths, track);
    }

    /// Every k-th finite sample, for ~1500 points.
    public static List<Pt> Thin(double[] distance, double[] column)
    {
        int n = distance.Length;
        int stride = Math.Max(1, n / 1500);
        var pts = new List<Pt>();
        for (int i = 0; i < Math.Min(n, column.Length); i += stride)
            if (double.IsFinite(column[i])) pts.Add(new Pt(distance[i], column[i]));
        return pts;
    }
}

/// The rated lap against the perfect lap, thinned for plotting.
public sealed record PerfectPlot(
    double LengthM, IReadOnlyList<Pt> Sim, IReadOnlyList<Pt> Lap, IReadOnlyList<Pt> Delta,
    /// Both laps as cars on the racing line; null when the trace file has no x/y.
    GhostReplay? Replay,
    /// The replay's line thinned to ~5 m, for drawing the track.
    IReadOnlyList<(double X, double Y)> Outline)
{
    public static PerfectPlot Prepare(Traces t)
    {
        var distance = t["distance"];
        var replay = GhostReplay.Create(t);
        var outline = new List<(double, double)>();
        if (replay is not null)
        {
            double last = double.NegativeInfinity;
            var d = replay.Distance;
            for (int i = 0; i < d.Length; i++)
            {
                if (d[i] - last >= 5 || i == d.Length - 1)
                {
                    outline.Add((replay.X[i], replay.Y[i]));
                    last = d[i];
                }
            }
        }
        return new PerfectPlot(
            distance.Length > 0 ? distance[^1] : 0, PlotTraces.Thin(distance, t["sim.speed"]),
            PlotTraces.Thin(distance, t["lap.speed"]), PlotTraces.Thin(distance, t["delta"]),
            replay, outline);
    }
}
