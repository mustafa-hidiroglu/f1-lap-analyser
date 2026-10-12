using System.Globalization;

namespace F1Lap.Core;

/// Number formatting shared by every view (mirrors Format.swift). Invariant culture: lap times
/// always read "1:19.461", whatever the Windows locale's decimal separator.
public static class Fmt
{
    private static readonly CultureInfo C = CultureInfo.InvariantCulture;

    public static string LapTime(double? s)
    {
        if (s is not { } v || !double.IsFinite(v)) return "—";
        int m = (int)v / 60;
        return m > 0
            ? $"{m.ToString(C)}:{(v - m * 60).ToString("00.000", C)}"
            : v.ToString("0.000", C);
    }

    /// Signed seconds; positive = compared lap slower.
    public static string Delta(double? s, int digits = 3)
    {
        if (s is not { } v || !double.IsFinite(v)) return "—";
        var body = Math.Abs(v).ToString("F" + digits, C);
        // Like printf's %+: a value that rounds to zero keeps its sign ("-0.000").
        return (v < 0 || (v == 0 && double.IsNegative(v)) ? "-" : "+") + body;
    }

    public static string Speed(double? v) =>
        v is { } x && double.IsFinite(x) ? x.ToString("0", C) : "—";

    public static string Lap(LapLabel label, bool year = false)
    {
        var name = label.LapNumber is { } n ? $"{label.Driver} L{n}" : label.Driver;
        return year && label.Year is { } y ? $"{name} · {y}" : name;
    }

    public static string Fixed(double v, int digits) => v.ToString("F" + digits, C);
}
