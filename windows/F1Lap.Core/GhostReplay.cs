namespace F1Lap.Core;

/// The rated lap and the perfect lap as two cars on one racing line, replayed in time.
/// A line-for-line port of app/Sources/F1LapKit/GhostReplay.swift; see there for the reasoning.
///
/// Built from the perfect-lap trace file: both laps' elapsed time on a shared distance grid plus
/// the x/y line. Rows with a missing value, or where either clock does not move forward, are
/// dropped so every lookup is a binary search over strictly increasing times.
public sealed class GhostReplay
{
    public double[] Distance { get; }
    public double[] SimTime { get; }
    public double[] LapTime { get; }
    public double[] X { get; }
    public double[] Y { get; }
    public Channels Sim { get; }
    public Channels Lap { get; }
    /// x/y units per metre of lap distance (FastF1 positions are in 1/10 m).
    public double UnitsPerMetre { get; }

    /// What a car is doing at a point of the lap. The rated car's phase is its pedals; the
    /// perfect car's is read off its speed (the simulation has no pedal model).
    public enum Phase { Braking, Partial, FullThrottle, Accelerating, Steady }

    /// A point on the line: a braking point, an apex or a return to full throttle.
    public readonly record struct Marker(int Row, double DistanceM, double X, double Y);

    /// One car's speed and pedals on the kept rows, plus its braking zones and apexes.
    public sealed class Channels
    {
        public double[]? SpeedKmh { get; init; }
        public double[]? Throttle { get; init; }
        public double[]? Brake { get; init; }
        public IReadOnlyList<Marker> Braking { get; init; } = [];
        public IReadOnlyList<Marker> Apex { get; init; } = [];
        /// Rated car only: back to full throttle after each apex, judged on its pedal.
        public IReadOnlyList<Marker> FullThrottle { get; init; } = [];
        internal double[]? Decel { get; init; }
        internal bool IsSim { get; init; }

        internal Phase? PhaseAt(int row)
        {
            if (IsSim)
            {
                if (Decel is null) return null;
                double a = Decel[row];
                if (!double.IsFinite(a)) return null;
                return a >= BrakingG * G ? Phase.Braking
                    : a <= -AccelG * G ? Phase.Accelerating : Phase.Steady;
            }
            if (Throttle is null || Brake is null) return null;
            double t = Throttle[row], b = Brake[row];
            if (!double.IsFinite(t) || !double.IsFinite(b)) return null;
            if (b > 0.5) return Phase.Braking;
            return t >= FullThrottlePct ? Phase.FullThrottle : Phase.Partial;
        }
    }

    public readonly record struct Car(double DistanceM, double X, double Y, bool Finished,
                                      double? SpeedKmh, Phase? Phase);

    public readonly record struct Frame(Car Sim, Car Lap, double GapS);

    public const double DebounceM = 10;
    public const double MinDropKmh = 10;
    public const double BrakingG = 0.5;
    public const double AccelG = 0.05;
    public const double FullThrottlePct = 95;
    public const double PedalLeadM = 50;
    public const double SmoothingM = 4;
    internal const double G = 9.81;

    /// Null when the file lacks the replay columns (older sidecars) or has under two usable rows.
    public static GhostReplay? Create(Traces t)
    {
        double[] d = t["distance"], st = t["sim.time"], lt = t["lap.time"], xs = t["x"], ys = t["y"];
        int n = d.Length;
        if (n <= 1 || new[] { st, lt, xs, ys }.Any(c => c.Length != n)) return null;
        var keep = new List<int>();
        for (int i = 0; i < n; i++)
        {
            if (!(double.IsFinite(d[i]) && double.IsFinite(st[i]) && double.IsFinite(lt[i])
                  && double.IsFinite(xs[i]) && double.IsFinite(ys[i]))) continue;
            if (keep.Count > 0)
            {
                int last = keep[^1];
                if (!(st[i] > st[last] && lt[i] > lt[last])) continue;
            }
            keep.Add(i);
        }
        if (keep.Count <= 1) return null;
        return new GhostReplay(t, keep, n);
    }

    private GhostReplay(Traces t, List<int> keep, int n)
    {
        double[] d = t["distance"], st = t["sim.time"], lt = t["lap.time"], xs = t["x"], ys = t["y"];
        var dk = keep.Select(i => d[i]).ToArray();
        var xk = keep.Select(i => xs[i]).ToArray();
        var yk = keep.Select(i => ys[i]).ToArray();
        (Distance, X, Y) = (dk, xk, yk);
        double path = 0;
        for (int i = 1; i < dk.Length; i++) path += Math.Sqrt(Math.Pow(xk[i] - xk[i - 1], 2) + Math.Pow(yk[i] - yk[i - 1], 2));
        UnitsPerMetre = dk[^1] > dk[0] ? path / (dk[^1] - dk[0]) : 1;
        SimTime = keep.Select(i => st[i]).ToArray();
        LapTime = keep.Select(i => lt[i]).ToArray();

        double[]? Kept(string name)
        {
            var c = t[name];
            return c.Length == n ? keep.Select(i => c[i]).ToArray() : null;
        }
        Marker MarkerAt(int row) => new(row, dk[row], xk[row], yk[row]);

        Channels Build(string prefix)
        {
            var speed = Kept(prefix + ".speed");
            var throttle = Kept(prefix + ".throttle");
            var brake = Kept(prefix + ".brake");
            bool isSim = prefix == "sim";
            if (speed is null)
                return new Channels { Throttle = throttle, Brake = brake, IsSim = isSim };
            int rows = dk.Length;
            var v = Smooth(speed.Select(s => s / 3.6).ToArray(), dk);  // m/s
            var decel = new double[rows];
            for (int i = 0; i < rows; i++)
            {
                int lo = Math.Max(i - 1, 0), hi = Math.Min(i + 1, rows - 1);
                decel[i] = -v[i] * (v[hi] - v[lo]) / (dk[hi] - dk[lo]);
            }
            var zones = Runs(decel.Select(a => a >= BrakingG * G).ToArray(), dk, r =>
            {
                double? first = null, low = null;
                for (int i = r.Start; i <= r.End; i++)
                {
                    if (!double.IsFinite(speed[i])) continue;
                    first ??= speed[i];
                    low = low is null ? speed[i] : Math.Min(low.Value, speed[i]);
                }
                return first is not null && low is not null && first - low >= MinDropKmh;
            });
            var apex = new List<int>();
            for (int k = 0; k < zones.Count; k++)
            {
                var z = zones[k];
                // Slowest point before the car gains speed again (or the next zone starts).
                int stop = k + 1 < zones.Count ? zones[k + 1].Start - 1 : rows - 1;
                int j = z.End;
                while (j < stop && !(decel[j + 1] <= -AccelG * G)) j++;
                int? slowest = null;
                for (int i = z.Start; i <= j; i++)
                    if (double.IsFinite(v[i]) && (slowest is null || v[i] < v[slowest.Value])) slowest = i;
                apex.Add(slowest ?? z.End);
            }
            var braking = new List<Marker>();
            bool hasBrake = brake is not null && brake.Any(double.IsFinite);
            var pedal = isSim || !hasBrake ? null : brake;
            for (int k = 0; k < zones.Count; k++)
            {
                var z = zones[k];
                if (pedal is null) { braking.Add(MarkerAt(z.Start)); continue; }
                double from = dk[z.Start] - PedalLeadM;
                int lo = k > 0 ? apex[k - 1] + 1 : 0;
                for (int row = lo; row <= apex[k]; row++)
                    if (dk[row] >= from && pedal[row] > 0.5) { braking.Add(MarkerAt(row)); break; }
            }
            var full = new List<Marker>();
            if (!isSim && throttle is not null && brake is not null)
            {
                var on = new bool[rows];
                for (int i = 0; i < rows; i++) on[i] = throttle[i] >= FullThrottlePct && !(brake[i] > 0.5);
                for (int k = 0; k < apex.Count; k++)
                {
                    // First row from the apex that stays at full throttle for `DebounceM`.
                    int stop = k + 1 < zones.Count ? zones[k + 1].Start : rows;
                    int i = apex[k];
                    while (i < stop)
                    {
                        if (!on[i]) { i++; continue; }
                        int j = i;
                        while (j + 1 < rows && on[j + 1] && dk[j] - dk[i] < DebounceM) j++;
                        if (dk[j] - dk[i] >= DebounceM || j == rows - 1)
                        {
                            full.Add(MarkerAt(i));
                            break;
                        }
                        i = j + 1;
                    }
                }
            }
            return new Channels
            {
                SpeedKmh = speed, Throttle = throttle, Brake = brake, Braking = braking,
                Apex = apex.Select(MarkerAt).ToList(), FullThrottle = full, Decel = decel,
                IsSim = isSim,
            };
        }

        Sim = Build("sim");
        Lap = Build("lap");
    }

    public double SimLapTimeS => SimTime[^1] - SimTime[0];
    public double LapTimeS => LapTime[^1] - LapTime[0];
    /// Until the slower car crosses the line.
    public double DurationS => Math.Max(SimLapTimeS, LapTimeS);

    /// Both cars `t` seconds after the start.
    public Frame FrameAt(double t)
    {
        double si = Index(SimTime, SimTime[0] + t);
        double li = Index(LapTime, LapTime[0] + t);
        double gap = (Value(LapTime, li) - LapTime[0]) - (Value(SimTime, li) - SimTime[0]);
        return new Frame(CarAt(si, Sim, t >= SimLapTimeS), CarAt(li, Lap, t >= LapTimeS), gap);
    }

    private Car CarAt(double i, Channels c, bool finished)
    {
        double? speed = c.SpeedKmh is { } s ? Value(s, i) : null;
        return new Car(Value(Distance, i), Value(X, i), Value(Y, i), finished,
                       speed is { } sp && double.IsFinite(sp) ? sp : null,
                       c.PhaseAt((int)Math.Round(i, MidpointRounding.AwayFromZero)));
    }

    public readonly record struct Run(int Start, int End);

    /// First and last rows of each run of `on` lasting `DebounceM`, after dropping the runs that
    /// fail `keep` and then merging those separated by gaps shorter than that. A run already
    /// under way on the first row is dropped.
    public static List<Run> Runs(bool[] on, double[] d, Func<Run, bool>? keep = null)
    {
        int n = on.Length;
        double EndM(int j) => d[Math.Min(j + 1, n - 1)];
        var raw = new List<Run>();
        int i = 0;
        while (i < n)
        {
            if (!on[i]) { i++; continue; }
            int j = i;
            while (j + 1 < n && on[j + 1]) j++;
            raw.Add(new Run(i, j));
            i = j + 1;
        }
        var runs = new List<Run>();
        foreach (var r in raw)
        {
            if (keep is not null && !keep(r)) continue;
            if (runs.Count > 0 && d[r.Start] - EndM(runs[^1].End) < DebounceM)
                runs[^1] = runs[^1] with { End = r.End };
            else
                runs.Add(r);
        }
        return runs.Where(r => r.Start > 0 && EndM(r.End) - d[r.Start] >= DebounceM).ToList();
    }

    /// `v` smoothed with a Gaussian of σ `SmoothingM` cut at 3σ over distance, skipping missing
    /// values (a row with none in reach stays missing); `_smooth` in src/f1lap/phases.py matches.
    public static double[] Smooth(double[] v, double[] d)
    {
        const double reach = 3 * SmoothingM;
        var out_ = new double[v.Length];
        for (int i = 0; i < v.Length; i++)
        {
            double sum = 0, weight = 0;
            int j = i;
            while (j > 0 && d[i] - d[j - 1] <= reach) j--;
            for (; j < v.Length && d[j] - d[i] <= reach; j++)
            {
                if (!double.IsFinite(v[j])) continue;
                double w = Math.Exp(-Math.Pow((d[j] - d[i]) / SmoothingM, 2) / 2);
                sum += w * v[j];
                weight += w;
            }
            out_[i] = weight > 0 ? sum / weight : double.NaN;
        }
        return out_;
    }

    /// Fractional row where the increasing `times` reach `t`, clamped to the lap.
    public static double Index(double[] times, double t)
    {
        if (!(t > times[0])) return 0;
        if (!(t < times[^1])) return times.Length - 1;
        int lo = 0, hi = times.Length - 1;  // times[lo] < t <= times[hi]
        while (hi - lo > 1)
        {
            int mid = (lo + hi) / 2;
            if (times[mid] < t) lo = mid; else hi = mid;
        }
        return lo + (t - times[lo]) / (times[hi] - times[lo]);
    }

    private static double Value(double[] column, double i)
    {
        int lo = (int)i, hi = Math.Min(lo + 1, column.Length - 1);
        return column[lo] + (column[hi] - column[lo]) * (i - lo);
    }
}
