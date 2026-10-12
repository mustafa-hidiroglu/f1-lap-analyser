using System.Globalization;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using F1Lap.Core;

namespace F1Lap.App.Controls;

/// The circuit on the reference lap's line, coloured by where time is gained (green) or lost
/// (red), with corner numbers, the start/finish line and the shared pointer (TrackMap in
/// CompareView.swift).
public sealed class TrackMap : Control
{
    private readonly IReadOnlyList<TrackPt> _pts;
    private readonly CircuitInfo _circuit;
    private readonly ChartSync _sync;
    private readonly TrackProjection.Bounds? _bounds;

    public TrackMap(IReadOnlyList<TrackPt> pts, CircuitInfo circuit, ChartSync sync)
    {
        (_pts, _circuit, _sync) = (pts, circuit, sync);
        _bounds = TrackProjection.Bounds.Of(pts.Select(p => p.X).ToList(), pts.Select(p => p.Y).ToList(),
                                            circuit.RotationDeg);
        ClipToBounds = true;
        AttachedToVisualTree += (_, _) => _sync.Changed += InvalidateVisual;
        DetachedFromVisualTree += (_, _) => _sync.Changed -= InvalidateVisual;
        ActualThemeVariantChanged += (_, _) => InvalidateVisual();
    }

    public override void Render(DrawingContext ctx)
    {
        if (_bounds is not { } b || _pts.Count < 2) return;
        var project = new TrackProjection(b, Bounds.Width, Bounds.Height);
        var screen = _pts.Select(p => project.Project(p.X, p.Y)).Select(p => new Point(p.X, p.Y)).ToArray();
        var window = _sync.Window;

        // Saturates at 0.02 s lost or gained per 100 m.
        for (int i = 1; i < screen.Length; i++)
        {
            double gain = _pts[i].Gain;
            double strength = Math.Min(1, Math.Abs(gain) / 0.02);
            var color = MacTheme.Mix(gain < 0 ? MacTheme.Green : MacTheme.Red, MacTheme.Gray, 1 - strength);
            bool inWindow = window is not { } w || (_pts[i].D >= w.Lo && _pts[i].D <= w.Hi);
            ctx.DrawLine(new Pen(MacTheme.Brush(MacTheme.WithAlpha(color, inWindow ? 1 : 0.25)), inWindow ? 5 : 3,
                                 lineCap: PenLineCap.Round), screen[i - 1], screen[i]);
        }

        var label = MacTheme.Brush(MacTheme.Secondary);
        foreach (var c in _circuit.Corners)
        {
            if (Nearest(c.DistanceM) is not { } i) continue;
            var t = new FormattedText(c.Label, CultureInfo.InvariantCulture, FlowDirection.LeftToRight,
                                      new Typeface(MacTheme.Font, weight: FontWeight.Bold), MacTheme.Caption2, label);
            ctx.DrawText(t, new Point(screen[i].X + 10 - t.Width / 2, screen[i].Y - 10 - t.Height / 2));
        }
        var primary = MacTheme.Brush(MacTheme.Primary);
        if (_sync.Cursor is { } cur && Nearest(cur) is { } ci)
            ctx.DrawEllipse(primary, null, screen[ci], 6, 6);
        var s = screen[0];  // start/finish
        ctx.FillRectangle(primary, new Rect(s.X - 2, s.Y - 8, 4, 16));
    }

    private int? Nearest(double d)
    {
        if (_pts.Count == 0) return null;
        int lo = 0, hi = _pts.Count - 1;
        while (lo < hi)
        {
            int mid = (lo + hi) / 2;
            if (_pts[mid].D < d) lo = mid + 1; else hi = mid;
        }
        return lo;
    }
}
