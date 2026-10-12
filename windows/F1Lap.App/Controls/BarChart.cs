using System.Globalization;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;

namespace F1Lap.App.Controls;

/// Grouped bars per category (Swift Charts BarMark with `.position(by:)`): y axis on the trailing
/// edge with solid gridlines, category names under each group.
public sealed class BarChart(IReadOnlyList<string> categories,
                             IReadOnlyList<(string Name, Func<Color> Color, IReadOnlyList<double> Values)> groups)
    : Control
{
    public override void Render(DrawingContext ctx)
    {
        if (categories.Count == 0) return;
        double lo = Math.Min(0, groups.SelectMany(g => g.Values).DefaultIfEmpty(0).Min());
        double hi = Math.Max(0, groups.SelectMany(g => g.Values).DefaultIfEmpty(1).Max());
        if (hi - lo < 1e-9) hi = lo + 1;
        double step = TraceChart.NiceStep((hi - lo) / 4);
        (lo, hi) = (Math.Floor(lo / step) * step, Math.Ceiling(hi / step) * step);
        var ticks = TraceChart.Ticks(lo, hi, 4);
        var secondary = MacTheme.Brush(MacTheme.Secondary);
        int digits = TraceChart.Decimals(step);
        string Fmt(double v) => v.ToString("0." + new string('#', digits), CultureInfo.InvariantCulture);
        double labelWidth = ticks.Select(t => Text(Fmt(t), secondary).Width).DefaultIfEmpty(0).Max();
        var plot = new Rect(0, 4, Math.Max(10, Bounds.Width - labelWidth - 6), Math.Max(10, Bounds.Height - 22));
        double Y(double v) => plot.Bottom - (v - lo) / (hi - lo) * plot.Height;

        var grid = new Pen(MacTheme.Brush(MacTheme.Gridline), 1);
        foreach (var t in ticks)
        {
            double y = Math.Round(Y(t)) + 0.5;
            ctx.DrawLine(grid, new Point(plot.X, y), new Point(plot.Right, y));
            var label = Text(Fmt(t), secondary);
            ctx.DrawText(label, new Point(plot.Right + 6, y - label.Height / 2));
        }
        double slot = plot.Width / categories.Count;
        double groupWidth = slot * 0.7, bar = groupWidth / Math.Max(groups.Count, 1);
        for (int i = 0; i < categories.Count; i++)
        {
            double x = plot.X + slot * i + (slot - groupWidth) / 2;
            for (int g = 0; g < groups.Count; g++)
            {
                if (i >= groups[g].Values.Count) continue;
                double v = groups[g].Values[i], ya = Y(Math.Max(v, 0)), yb = Y(Math.Min(v, 0));
                ctx.DrawRectangle(MacTheme.Brush(groups[g].Color()), null,
                                  new RoundedRect(new Rect(x + bar * g, ya, Math.Max(bar - 1, 1), Math.Max(yb - ya, 0.5)), 1.5));
            }
            var name = Text(categories[i], secondary);
            if (name.Width <= slot + 4)
                ctx.DrawText(name, new Point(plot.X + slot * i + (slot - name.Width) / 2, plot.Bottom + 4));
        }
    }

    private static FormattedText Text(string s, IBrush brush) =>
        new(s, CultureInfo.InvariantCulture, FlowDirection.LeftToRight, new Typeface(MacTheme.Font), MacTheme.Caption2, brush);
}
