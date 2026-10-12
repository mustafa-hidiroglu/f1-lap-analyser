using System.Globalization;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;

namespace F1Lap.App.Controls;

/// SwiftUI's `.accessoryCircular` gauge: an open ring tinted red → yellow → green, a marker at
/// the value, the value in the middle and the label underneath.
public sealed class ScoreGauge(double value, double max = 100, string label = "Score") : Control
{
    private const double Sweep = 270, Start = 135;  // degrees, clockwise from +x; gap at the bottom

    protected override Size MeasureOverride(Size availableSize) => new(120, 120);

    public override void Render(DrawingContext ctx)
    {
        double size = Math.Min(Bounds.Width, Bounds.Height);
        var c = new Point(Bounds.Width / 2, Bounds.Height / 2);
        double r = size / 2 - 8, thickness = 9;
        // The gradient as short arcs (a conic gradient that also works on every backend).
        const int steps = 90;
        for (int i = 0; i < steps; i++)
        {
            double t0 = (double)i / steps, t1 = (i + 1.0) / steps;
            ctx.DrawGeometry(null, new Pen(MacTheme.Brush(Tint(t0)), thickness, lineCap: i is 0 or steps - 1 ? PenLineCap.Round : PenLineCap.Flat),
                             Arc(c, r, Start + Sweep * t0, Start + Sweep * Math.Min(t1 + 0.002, 1)));
        }
        double f = Math.Clamp(value / max, 0, 1);
        var at = Polar(c, r, Start + Sweep * f);
        ctx.DrawEllipse(MacTheme.Brush(MacTheme.WindowBackground), new Pen(MacTheme.Brush(MacTheme.Primary), 2.5), at,
                        thickness / 2 + 1, thickness / 2 + 1);

        var primary = MacTheme.Brush(MacTheme.Primary);
        var number = Text(value.ToString("0", CultureInfo.InvariantCulture), 26, FontWeight.SemiBold, primary);
        ctx.DrawText(number, new Point(c.X - number.Width / 2, c.Y - number.Height / 2 - 2));
        var caption = Text(label, MacTheme.Caption, FontWeight.Medium, MacTheme.Brush(MacTheme.Secondary));
        ctx.DrawText(caption, new Point(c.X - caption.Width / 2, c.Y + r - caption.Height / 2));
    }

    private static Color Tint(double t) => t < 0.5
        ? MacTheme.Mix(MacTheme.Red, MacTheme.Yellow, t * 2)
        : MacTheme.Mix(MacTheme.Yellow, MacTheme.Green, (t - 0.5) * 2);

    private static Point Polar(Point c, double r, double deg)
    {
        double a = deg * Math.PI / 180;
        return new Point(c.X + r * Math.Cos(a), c.Y + r * Math.Sin(a));
    }

    private static Geometry Arc(Point c, double r, double fromDeg, double toDeg)
    {
        var g = new StreamGeometry();
        using var ctx = g.Open();
        ctx.BeginFigure(Polar(c, r, fromDeg), false);
        ctx.ArcTo(Polar(c, r, toDeg), new Size(r, r), 0, toDeg - fromDeg > 180, SweepDirection.Clockwise);
        ctx.EndFigure(false);
        return g;
    }

    private static FormattedText Text(string s, double size, FontWeight weight, IBrush brush) =>
        new(s, CultureInfo.InvariantCulture, FlowDirection.LeftToRight, new Typeface(MacTheme.Font, weight: weight),
            size, brush);
}
