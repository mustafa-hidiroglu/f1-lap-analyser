using System.Globalization;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Media;
using F1Lap.Core;

namespace F1Lap.App.Controls;

/// Pointer distance and zoom window shared by every chart (and the track map) of a comparison.
public sealed class ChartSync
{
    private double? _cursor;
    private (double Lo, double Hi)? _window;

    public event Action? Changed;

    /// Distance under the pointer.
    public double? Cursor
    {
        get => _cursor;
        set { if (_cursor != value) { _cursor = value; Changed?.Invoke(); } }
    }

    /// Visible distance window; null = the whole lap.
    public (double Lo, double Hi)? Window
    {
        get => _window;
        set { if (_window != value) { _window = value; Changed?.Invoke(); } }
    }
}

/// A line series; the colour is read at draw time so it follows light/dark changes.
public sealed record Series(IReadOnlyList<Pt> Points, Func<Color> Color, double Width = 2);

/// A shaded distance band (RectangleMark spanning the plot's height).
public sealed record Band(double From, double To, Func<Color> Color);

/// A line chart over lap distance in the style of Swift Charts: y axis on the trailing edge,
/// solid horizontal and dashed vertical gridlines, corner rules labelled above the plot. Hovering
/// moves the shared pointer; dragging zooms every synced chart to the dragged range.
public sealed class TraceChart : Control
{
    private const double AxisGap = 6, XLabelHeight = 16;
    private double? _dragFrom, _dragTo;

    public List<Series> Series { get; } = [];
    public List<Band> Bands { get; } = [];
    public IReadOnlyList<CircuitCorner>? Corners { get; init; }
    public double? ZeroRule { get; init; }
    public (double Lo, double Hi)? YDomain { get; init; }
    public double LengthM { get; init; }
    /// Shared pointer and zoom; without one the chart shows the whole lap and is not interactive.
    public ChartSync? Sync { get; init; }

    public TraceChart()
    {
        ClipToBounds = true;
        Cursor = new Cursor(StandardCursorType.Cross);
        AttachedToVisualTree += (_, _) => { if (Sync is not null) Sync.Changed += InvalidateVisual; };
        DetachedFromVisualTree += (_, _) => { if (Sync is not null) Sync.Changed -= InvalidateVisual; };
        ActualThemeVariantChanged += (_, _) => InvalidateVisual();
    }

    private (double Lo, double Hi) XDomain => Sync?.Window ?? (0, Math.Max(LengthM, 1));

    /// Fewer y ticks on short charts (brake, gear), as Swift Charts does.
    private int YTickCount => Math.Clamp((int)(Bounds.Height / 32), 2, 5);

    /// Decimals needed to print multiples of `step` exactly (0.25 → 2, 0.5 → 1, 50 → 0).
    public static int Decimals(double step)
    {
        int d = 0;
        while (d < 4 && Math.Abs(step * Math.Pow(10, d) - Math.Round(step * Math.Pow(10, d))) > 1e-9) d++;
        return d;
    }

    private double TopInset => Corners is null ? 6 : 16;  // room for the corner labels

    private (double Lo, double Hi) YRange()
    {
        if (YDomain is { } d) return d;
        double lo = double.PositiveInfinity, hi = double.NegativeInfinity;
        var (x0, x1) = XDomain;
        foreach (var s in Series)
            foreach (var p in s.Points)
            {
                if (p.D < x0 || p.D > x1) continue;
                lo = Math.Min(lo, p.V);
                hi = Math.Max(hi, p.V);
            }
        if (double.IsInfinity(lo)) return (0, 1);
        // Like Swift Charts' automatic scale: include zero, then round out to nice ticks.
        lo = Math.Min(lo, 0);
        hi = Math.Max(hi, 0);
        if (hi - lo < 1e-9) hi = lo + 1;
        double step = NiceStep((hi - lo) / YTickCount);
        return (Math.Floor(lo / step) * step, Math.Ceiling(hi / step) * step);
    }

    public override void Render(DrawingContext ctx)
    {
        var (y0, y1) = YRange();
        var (x0, x1) = XDomain;
        var secondary = MacTheme.Brush(MacTheme.Secondary);
        var yTicks = Ticks(y0, y1, YTickCount);
        // The plot leaves room on the right for the widest y label.
        double labelWidth = yTicks.Select(t => Measure(FormatY(t, yTicks)).Width).DefaultIfEmpty(0).Max();
        var plot = new Rect(0, TopInset, Math.Max(10, Bounds.Width - labelWidth - AxisGap),
                            Math.Max(10, Bounds.Height - TopInset - XLabelHeight));
        double X(double d) => plot.X + (d - x0) / (x1 - x0) * plot.Width;
        double Y(double v) => plot.Bottom - (v - y0) / (y1 - y0) * plot.Height;

        foreach (var b in Bands)
        {
            double a = Math.Max(X(b.From), plot.X), z = Math.Min(X(b.To), plot.Right);
            if (z > a) ctx.FillRectangle(MacTheme.Brush(b.Color()), new Rect(a, plot.Y, z - a, plot.Height));
        }

        var grid = new Pen(MacTheme.Brush(MacTheme.Gridline), 1);
        foreach (var t in yTicks)
        {
            double y = Math.Round(Y(t)) + 0.5;
            ctx.DrawLine(grid, new Point(plot.X, y), new Point(plot.Right, y));
            var text = Text(FormatY(t, yTicks), secondary);
            ctx.DrawText(text, new Point(plot.Right + AxisGap, y - text.Height / 2));
        }
        var dashed = new Pen(MacTheme.Brush(MacTheme.Gridline), 1, new DashStyle([2, 2], 0));
        foreach (var t in Ticks(x0, x1, 8))
        {
            double x = Math.Round(X(t)) + 0.5;
            ctx.DrawLine(dashed, new Point(x, plot.Y), new Point(x, plot.Bottom + 4));
            var text = Text(t.ToString("#,0", CultureInfo.InvariantCulture), secondary);
            ctx.DrawText(text, new Point(x + 3, plot.Bottom + 2));
        }

        // Corner rules and their labels go down before the clipped series: text drawn after a
        // popped clip was dropped (with everything after it) by the renderer.
        if (Corners is not null)
        {
            var rule = new Pen(MacTheme.Brush(MacTheme.WithAlpha(MacTheme.Gray, 0.45)), 1.5);
            foreach (var c in Corners)
            {
                if (c.DistanceM < x0 || c.DistanceM > x1) continue;
                double x = X(c.DistanceM);
                ctx.DrawLine(rule, new Point(x, plot.Y), new Point(x, plot.Bottom));
                var label = Text(c.Label, secondary, MacTheme.Caption2);
                ctx.DrawText(label, new Point(x - label.Width / 2, plot.Y - label.Height - 1));
            }
        }

        using (ctx.PushClip(plot.Inflate(new Thickness(0, 2))))
        {
            if (ZeroRule is { } z0)
                ctx.DrawLine(new Pen(MacTheme.Brush(MacTheme.WithAlpha(MacTheme.Gray, 0.5)), 1.5),
                             new Point(plot.X, Y(z0)), new Point(plot.Right, Y(z0)));
            foreach (var s in Series) DrawSeries(ctx, s, X, Y, x0, x1);
        }

        if (_dragFrom is { } f && _dragTo is { } to)
        {
            double a = Math.Min(X(f), X(to)), b = Math.Max(X(f), X(to));
            ctx.FillRectangle(MacTheme.Brush(MacTheme.WithAlpha(MacTheme.Blue, 0.15)), new Rect(a, plot.Y, b - a, plot.Height));
        }
        if (Sync?.Cursor is { } cur && cur >= x0 && cur <= x1)
        {
            double x = Math.Round(X(cur)) + 0.5;
            ctx.DrawLine(new Pen(MacTheme.Brush(MacTheme.WithAlpha(MacTheme.Primary, 0.5)), 1.5),
                         new Point(x, plot.Y), new Point(x, plot.Bottom));
        }
        _plot = plot;
    }

    private Rect _plot;

    private static void DrawSeries(DrawingContext ctx, Series s, Func<double, double> X,
                                   Func<double, double> Y, double x0, double x1)
    {
        var pts = s.Points;
        if (pts.Count < 2) return;
        // Only the visible stretch (plus one point either side so lines run to the edges).
        int lo = LowerBound(pts, x0) - 1, hi = LowerBound(pts, x1) + 1;
        lo = Math.Max(lo, 0);
        hi = Math.Min(hi, pts.Count - 1);
        if (hi <= lo) return;
        var geo = new StreamGeometry();
        using (var g = geo.Open())
        {
            g.BeginFigure(new Point(X(pts[lo].D), Y(pts[lo].V)), false);
            for (int i = lo + 1; i <= hi; i++) g.LineTo(new Point(X(pts[i].D), Y(pts[i].V)));
            g.EndFigure(false);
        }
        ctx.DrawGeometry(null, new Pen(MacTheme.Brush(s.Color()), s.Width, lineCap: PenLineCap.Round,
                                       lineJoin: PenLineJoin.Round), geo);
    }

    private static int LowerBound(IReadOnlyList<Pt> pts, double d)
    {
        int lo = 0, hi = pts.Count;
        while (lo < hi)
        {
            int mid = (lo + hi) / 2;
            if (pts[mid].D < d) lo = mid + 1; else hi = mid;
        }
        return lo;
    }

    // MARK: interaction

    private double? ValueAt(Point p)
    {
        if (_plot.Width <= 0) return null;
        var (x0, x1) = XDomain;
        double t = Math.Clamp((p.X - _plot.X) / _plot.Width, 0, 1);
        return x0 + t * (x1 - x0);
    }

    protected override void OnPointerMoved(PointerEventArgs e)
    {
        base.OnPointerMoved(e);
        if (Sync is null) return;
        var v = ValueAt(e.GetPosition(this));
        Sync.Cursor = v;
        if (_dragFrom is not null)
        {
            _dragTo = v;
            InvalidateVisual();
        }
    }

    protected override void OnPointerExited(PointerEventArgs e)
    {
        base.OnPointerExited(e);
        if (Sync is not null && _dragFrom is null) Sync.Cursor = null;
    }

    protected override void OnPointerPressed(PointerPressedEventArgs e)
    {
        base.OnPointerPressed(e);
        if (Sync is null || !e.GetCurrentPoint(this).Properties.IsLeftButtonPressed) return;
        _dragFrom = ValueAt(e.GetPosition(this));
        _dragTo = null;
        e.Pointer.Capture(this);
    }

    protected override void OnPointerReleased(PointerReleasedEventArgs e)
    {
        base.OnPointerReleased(e);
        if (Sync is null || _dragFrom is not { } a) return;
        var b = ValueAt(e.GetPosition(this)) ?? a;
        _dragFrom = _dragTo = null;
        e.Pointer.Capture(null);
        // Drag to zoom into a distance range (at least 20 m); a click just moves the pointer.
        if (Math.Abs(b - a) > 20)
            Sync.Window = (Math.Max(0, Math.Min(a, b)), Math.Min(Math.Max(LengthM, 1), Math.Max(a, b)));
        InvalidateVisual();
    }

    // MARK: ticks and text

    public static double NiceStep(double rough)
    {
        if (rough <= 0 || !double.IsFinite(rough)) return 1;
        double mag = Math.Pow(10, Math.Floor(Math.Log10(rough)));
        double r = rough / mag;
        return (r <= 1 ? 1 : r <= 2 ? 2 : r <= 2.5 ? 2.5 : r <= 5 ? 5 : 10) * mag;
    }

    /// Round-numbered ticks in [lo, hi], about `count` of them.
    public static List<double> Ticks(double lo, double hi, int count)
    {
        var ticks = new List<double>();
        if (!(hi > lo)) return ticks;
        double step = NiceStep((hi - lo) / count);
        for (double t = Math.Ceiling(lo / step - 1e-9) * step; t <= hi + step * 1e-9; t += step)
            ticks.Add(Math.Abs(t) < step * 1e-9 ? 0 : t);
        return ticks;
    }

    private static string FormatY(double v, List<double> ticks)
    {
        double step = ticks.Count > 1 ? ticks[1] - ticks[0] : 1;
        int digits = Decimals(step);
        var s = v.ToString("#,0." + new string('#', digits), CultureInfo.InvariantCulture);
        return s == "-0" ? "0" : s;
    }

    private static FormattedText Text(string s, IBrush brush, double size = MacTheme.Caption2) =>
        new(s, CultureInfo.InvariantCulture, FlowDirection.LeftToRight,
            new Typeface(MacTheme.Font), size, brush);

    private static Size Measure(string s)
    {
        var t = Text(s, Brushes.Black);
        return new Size(t.Width, t.Height);
    }
}
