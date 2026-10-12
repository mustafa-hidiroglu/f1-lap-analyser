using System.Diagnostics;
using System.Globalization;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using F1Lap.App.Controls;
using F1Lap.Core;
using Avalonia.Controls.Primitives;
using Grid = Avalonia.Controls.Grid;

namespace F1Lap.App.Views;

/// The rated lap racing the perfect lap on the track map (GhostReplayView.swift).
public sealed class GhostReplayView : UserControl
{
    private readonly GhostReplay _replay;
    private readonly string _driver;
    /// Official lap times and gap, shown once the cars finish; the replay's own when null.
    private readonly double? _lapTimeS, _simLapTimeS, _gapS;
    private readonly GhostCanvas _canvas;
    private readonly DispatcherTimer _timer;
    private readonly Stopwatch _clock = new();
    private readonly Button _play;
    private readonly Slider _slider;
    private readonly TextBlock _time, _gap;
    private readonly (TextBlock Value, TextBlock Phase) _simReadout, _lapReadout;
    private readonly Control _legend;

    /// Playback anchor: replay time `_startT` when `_clock` was last restarted; paused when stopped.
    private double _startT, _speed = 1;
    private bool _resumeAfterScrub, _syncingSlider;
    private bool? _shownPlaying;

    public GhostReplayView(GhostReplay replay, IReadOnlyList<(double X, double Y)> outline,
                           double rotationDeg, string driver, double? lapTimeS, double? simLapTimeS,
                           double? gapS)
    {
        (_replay, _driver, _lapTimeS, _simLapTimeS, _gapS) = (replay, driver, lapTimeS, simLapTimeS, gapS);
        _canvas = new GhostCanvas(replay, outline, rotationDeg, driver) { Height = 290 };

        var markers = new CheckBox { Content = "Markers", IsChecked = true };
        var follow = new CheckBox { Content = "Follow", IsChecked = false };
        markers.IsCheckedChanged += (_, _) =>
        {
            _canvas.ShowMarkers = markers.IsChecked == true;
            UpdateLegend();
        };
        follow.IsCheckedChanged += (_, _) => _canvas.Follow = follow.IsChecked == true;
        _legend = new FlowPanel { Spacing = 10, LineSpacing = 4 };
        var header = new DockPanel
        {
            Children =
            {
                Dock(Ui.Text("Ghost replay", MacTheme.Caption, secondary: true), Avalonia.Controls.Dock.Left),
                Dock(Ui.H(12, markers, follow), Avalonia.Controls.Dock.Right),
                new Border(),
            },
        };

        _play = new Button { Classes = { "plain" }, Width = 30, Padding = new Thickness(4) };
        _play.Click += (_, _) => TogglePlay();
        var speeds = new Segmented(["1×", "2×", "4×"], 0, MacTheme.Callout) { Width = 120 };
        speeds.SelectionChanged += i =>
        {
            _startT = Now();
            if (Playing) _clock.Restart();
            _speed = new[] { 1.0, 2, 4 }[i];
        };
        _slider = new Slider
        {
            Minimum = 0, Maximum = replay.DurationS, VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(0, -6),
        };
        _slider.PropertyChanged += (_, e) =>
        {
            if (e.Property != RangeBase.ValueProperty || _syncingSlider) return;
            _startT = _slider.Value;
            if (Playing) _clock.Restart();
            Refresh();
        };
        // Pause while dragging the thumb; resume on release.
        _slider.AddHandler(PointerPressedEvent, (_, _) =>
        {
            if (!Playing) return;
            Pause();
            _resumeAfterScrub = true;
        }, Avalonia.Interactivity.RoutingStrategies.Tunnel);
        _slider.AddHandler(PointerReleasedEvent, (_, _) =>
        {
            if (!_resumeAfterScrub) return;
            _resumeAfterScrub = false;
            if (_startT < replay.DurationS) PlayFrom(_startT);
        }, Avalonia.Interactivity.RoutingStrategies.Tunnel);
        _time = new TextBlock { Width = 64, TextAlignment = TextAlignment.Right, FontSize = MacTheme.Callout, VerticalAlignment = VerticalAlignment.Center };
        _gap = new TextBlock { Width = 56, TextAlignment = TextAlignment.Right, FontSize = MacTheme.Callout, VerticalAlignment = VerticalAlignment.Center };
        var controls = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("Auto,Auto,*,Auto,Auto"),
            ColumnSpacing = 12,
        };
        controls.Children.Add(_play);
        controls.Children.Add(Col(speeds, 1));
        controls.Children.Add(Col(_slider, 2));
        controls.Children.Add(Col(_time, 3));
        controls.Children.Add(Col(_gap, 4));

        _simReadout = Readout(out var simRow, "Perfect", MacTheme.Perfect);
        _lapReadout = Readout(out var lapRow, driver, MacTheme.Reference);

        _timer = new DispatcherTimer(TimeSpan.FromMilliseconds(1000.0 / 60), DispatcherPriority.Render,
                                     (_, _) => Tick());
        DetachedFromVisualTree += (_, _) => Pause();

        Content = Ui.V(6, header, _legend, _canvas, controls, Ui.H(20, simRow, lapRow));
        UpdateLegend();
        Refresh();
    }

    private bool Playing => _clock.IsRunning;

    private double Now() =>
        Math.Min(_startT + (Playing ? _clock.Elapsed.TotalSeconds * _speed : 0), _replay.DurationS);

    private void TogglePlay()
    {
        if (Playing) Pause();
        else PlayFrom(_startT >= _replay.DurationS ? 0 : _startT);
    }

    private void PlayFrom(double t)
    {
        _startT = t;
        _clock.Restart();
        _timer.Start();
        Refresh();
    }

    private void Pause()
    {
        _startT = Now();
        _clock.Reset();
        _timer.Stop();
        Refresh();
    }

    private void Tick()
    {
        if (Now() >= _replay.DurationS)  // stop at the end instead of redrawing a still frame
        {
            _startT = _replay.DurationS;
            _clock.Reset();
            _timer.Stop();
        }
        Refresh();
    }

    private void Refresh()
    {
        double t = Now();
        var frame = _replay.FrameAt(t);
        _canvas.Frame = frame;
        if (_shownPlaying != Playing)  // swap the icon on a state change, not every frame
        {
            _shownPlaying = Playing;
            _play.Content = new IconView(Playing ? Glyph.Pause : Glyph.Play) { Width = 14, Height = 14 };
        }
        _syncingSlider = true;
        _slider.Value = t;
        _syncingSlider = false;
        // Replay time runs on the distance grid, a little off the official times shown once a
        // car finishes; the clock never drops below a finished car's official time.
        double simOfficial = _simLapTimeS ?? _replay.SimLapTimeS, lapOfficial = _lapTimeS ?? _replay.LapTimeS;
        double clock = t >= _replay.DurationS ? Math.Max(lapOfficial, simOfficial)
            : Math.Max(t, Math.Max(frame.Sim.Finished ? simOfficial : 0, frame.Lap.Finished ? lapOfficial : 0));
        double gap = frame.Lap.Finished ? _gapS ?? frame.GapS : frame.GapS;
        _time.Text = Fmt.LapTime(clock);
        _gap.Text = Fmt.Delta(gap);
        _gap.Foreground = MacTheme.Brush(MacTheme.Delta(gap));
        Show(_simReadout, frame.Sim, simOfficial);
        Show(_lapReadout, frame.Lap, lapOfficial);
    }

    /// A car's live speed and phase; its lap time once it has crossed the line.
    private static void Show((TextBlock Value, TextBlock Phase) r, GhostReplay.Car car, double lapTimeS)
    {
        if (car.Finished)
        {
            r.Value.Text = Fmt.LapTime(lapTimeS);
            r.Phase.Text = "Finished";
            r.Phase.Foreground = MacTheme.Brush(MacTheme.Secondary);
            return;
        }
        r.Value.Text = $"{Fmt.Speed(car.SpeedKmh)} km/h";
        r.Phase.Text = car.Phase is { } p ? Label(p) : "";
        r.Phase.Foreground = MacTheme.Brush(car.Phase is { } q && GhostCanvas.Fill(q) is { } c ? c : MacTheme.Secondary);
    }

    private static (TextBlock, TextBlock) Readout(out Control row, string name, Color color)
    {
        var value = new TextBlock { Width = 70, TextAlignment = TextAlignment.Right, FontSize = MacTheme.Callout };
        var phase = new TextBlock { Width = 90, FontSize = MacTheme.Callout };
        row = Ui.H(6, Ui.Text(name, MacTheme.Callout, weight: FontWeight.Bold, color: color), value, phase);
        return (value, phase);
    }

    private void UpdateLegend()
    {
        var items = new List<Control>
        {
            Swatch(Ui.Dot(MacTheme.Braking, 7), "Braking"),
            Swatch(Ui.Dot(MacTheme.Lifting, 7), $"{_driver} lift / part throttle"),
        };
        if (_canvas.ShowMarkers)
        {
            items.Add(Swatch(new Border { Width = 2, Height = 9, Background = MacTheme.Brush(MacTheme.Secondary), Margin = new Thickness(6, 0, 0, 0) },
                             $"Braking point ({_driver}: pedal)"));
            items.Add(Swatch(new Avalonia.Controls.Shapes.Ellipse { Width = 7, Height = 7, Stroke = MacTheme.Brush(MacTheme.Secondary), StrokeThickness = 1.5 },
                             "Slowest point"));
            items.Add(Swatch(Ui.Dot(MacTheme.Secondary, 6), $"{_driver} full throttle"));
        }
        var panel = (FlowPanel)_legend;
        panel.Children.Clear();
        panel.Children.AddRange(items);

        static Control Swatch(Control mark, string text) =>
            Ui.H(4, mark, Ui.Text(text, MacTheme.Caption, secondary: true));
    }

    private static string Label(GhostReplay.Phase phase) => phase switch
    {
        GhostReplay.Phase.Braking => "Braking",
        GhostReplay.Phase.Partial => "Lift / part",
        GhostReplay.Phase.FullThrottle => "Full throttle",
        GhostReplay.Phase.Accelerating => "Accelerating",
        _ => "Steady",
    };

    private static Control Dock(Control c, Dock d)
    {
        DockPanel.SetDock(c, d);
        c.VerticalAlignment = VerticalAlignment.Center;
        return c;
    }

    private static Control Col(Control c, int column)
    {
        Grid.SetColumn(c, column);
        return c;
    }
}

/// Draws the line, markers and both cars for one frame.
public sealed class GhostCanvas : Control
{
    private readonly GhostReplay _replay;
    private readonly IReadOnlyList<(double X, double Y)> _outline;
    private readonly double _rotationDeg;
    private readonly string _driver;
    private readonly TrackProjection.Bounds? _bounds;
    private GhostReplay.Frame _frame;
    private bool _showMarkers = true, _follow;

    public GhostCanvas(GhostReplay replay, IReadOnlyList<(double X, double Y)> outline, double rotationDeg, string driver)
    {
        (_replay, _outline, _rotationDeg, _driver) = (replay, outline, rotationDeg, driver);
        _bounds = TrackProjection.Bounds.Of(outline.Select(o => o.X).ToList(), outline.Select(o => o.Y).ToList(), rotationDeg);
        ClipToBounds = true;
        ActualThemeVariantChanged += (_, _) => InvalidateVisual();
    }

    public GhostReplay.Frame Frame { get => _frame; set { _frame = value; InvalidateVisual(); } }
    public bool ShowMarkers { get => _showMarkers; set { _showMarkers = value; InvalidateVisual(); } }
    /// Zoomed in on the cars instead of the whole track.
    public bool Follow { get => _follow; set { _follow = value; InvalidateVisual(); } }

    /// Dot fill for a phase; null when not slowing, where the car shows its own colour.
    public static Color? Fill(GhostReplay.Phase phase) => phase switch
    {
        GhostReplay.Phase.Braking => MacTheme.Braking,
        GhostReplay.Phase.Partial => MacTheme.Lifting,
        _ => null,
    };

    public override void Render(DrawingContext ctx)
    {
        if (_bounds is not { } b) return;
        double w = Bounds.Width, h = Bounds.Height;
        TrackProjection project;
        if (_follow)
        {
            // A window of ~400 m around both cars, wider when needed to keep them both in view.
            var f = _frame;
            double half = Math.Max(200 * _replay.UnitsPerMetre,
                Math.Sqrt(Math.Pow(f.Sim.X - f.Lap.X, 2) + Math.Pow(f.Sim.Y - f.Lap.Y, 2)) / 2 + 80 * _replay.UnitsPerMetre);
            project = new TrackProjection(TrackProjection.Bounds.Around((f.Sim.X + f.Lap.X) / 2, (f.Sim.Y + f.Lap.Y) / 2, half, _rotationDeg), w, h);
        }
        else
        {
            project = new TrackProjection(b, w, h);
        }
        DrawTrack(ctx, project, w, h);
        DrawCars(ctx, project);
    }

    private Point P(TrackProjection project, double x, double y)
    {
        var (px, py) = project.Project(x, y);
        return new Point(px, py);
    }

    /// The line, start/finish and (when shown) both cars' braking points, slowest points and the
    /// rated car's return to full throttle. Only what falls on the canvas is drawn.
    private void DrawTrack(DrawingContext ctx, TrackProjection project, double w, double h)
    {
        var visible = new Rect(-30, -30, w + 60, h + 60);
        var line = new StreamGeometry();
        using (var g = line.Open())
        {
            bool drawing = false;
            foreach (var o in _outline)
            {
                var p = P(project, o.X, o.Y);
                if (!visible.Contains(p))
                {
                    if (drawing) g.EndFigure(false);
                    drawing = false;
                }
                else if (drawing) g.LineTo(p);
                else
                {
                    g.BeginFigure(p, false);
                    drawing = true;
                }
            }
            if (drawing) g.EndFigure(false);
        }
        // Opaque, so overlapping round caps at the joins don't show as dots.
        var track = MacTheme.Mix(MacTheme.Gray, MacTheme.WindowBackground, 0.4);
        ctx.DrawGeometry(null, new Pen(MacTheme.Brush(track), _follow ? 10 : 5, lineCap: PenLineCap.Round,
                                       lineJoin: PenLineJoin.Round), line);
        if (_outline.Count > 0)
        {
            var s = P(project, _outline[0].X, _outline[0].Y);
            ctx.FillRectangle(MacTheme.Brush(MacTheme.Primary), new Rect(s.X - 2, s.Y - 8, 4, 16));
        }
        if (!_showMarkers) return;
        // Perfect lap's markers on one side of the line, the rated lap's on the other.
        foreach (var (c, color, side) in new[] { (_replay.Sim, MacTheme.Perfect, 1.0), (_replay.Lap, MacTheme.Reference, -1.0) })
        {
            var brush = MacTheme.Brush(MacTheme.WithAlpha(color, 0.85));
            foreach (var m in c.Braking)
            {
                if (Normal(m, project) is not { } pn || !visible.Contains(pn.P)) continue;
                var (p, n) = pn;
                ctx.DrawLine(new Pen(brush, 2.5, lineCap: PenLineCap.Round), p,
                             new Point(p.X + n.X * side * 11, p.Y + n.Y * side * 11));
            }
            foreach (var m in c.Apex)
            {
                if (Normal(m, project) is not { } pn || !visible.Contains(pn.P)) continue;
                var at = new Point(pn.P.X + pn.N.X * side * 7, pn.P.Y + pn.N.Y * side * 7);
                ctx.DrawEllipse(null, new Pen(brush, 1.5), at, 3, 3);
            }
            foreach (var m in c.FullThrottle)
            {
                if (Normal(m, project) is not { } pn || !visible.Contains(pn.P)) continue;
                var at = new Point(pn.P.X + pn.N.X * side * 7, pn.P.Y + pn.N.Y * side * 7);
                ctx.DrawEllipse(brush, null, at, 3, 3);
            }
        }
    }

    /// A marker's point on the canvas and the unit normal to the line there.
    private (Point P, Point N)? Normal(GhostReplay.Marker m, TrackProjection project)
    {
        int last = _replay.X.Length - 1;
        var a = P(project, _replay.X[Math.Max(m.Row - 1, 0)], _replay.Y[Math.Max(m.Row - 1, 0)]);
        var b = P(project, _replay.X[Math.Min(m.Row + 1, last)], _replay.Y[Math.Min(m.Row + 1, last)]);
        double len = Math.Sqrt(Math.Pow(b.X - a.X, 2) + Math.Pow(b.Y - a.Y, 2));
        if (len <= 0) return null;
        return (P(project, m.X, m.Y), new Point(-(b.Y - a.Y) / len, (b.X - a.X) / len));
    }

    private void DrawCars(DrawingContext ctx, TrackProjection project)
    {
        var f = _frame;
        bool simLeads = f.Sim.DistanceM >= f.Lap.DistanceM;
        // Rated car drawn last so it sits on top when the two overlap.
        var cars = new[] { (f.Sim, "Perfect", MacTheme.Perfect, simLeads), (f.Lap, _driver, MacTheme.Reference, !simLeads) };
        var points = cars.Select(c => P(project, c.Item1.X, c.Item1.Y)).ToArray();
        var white = new Pen(Brushes.White, 1.5);
        for (int i = 0; i < cars.Length; i++)
        {
            var (car, _, color, _) = cars[i];
            ctx.DrawEllipse(MacTheme.Brush(color), null, points[i], 7, 7);
            if (car.Phase is { } ph && Fill(ph) is { } fill) ctx.DrawEllipse(MacTheme.Brush(fill), null, points[i], 4, 4);
            ctx.DrawEllipse(null, white, points[i], 7, 7);
        }
        // Leader's label to the right of its dot, the other's to the left, each on a chip.
        var chip = MacTheme.Brush(MacTheme.WindowBackground);
        for (int i = 0; i < cars.Length; i++)
        {
            var (_, label, color, leads) = cars[i];
            var text = new FormattedText(label, CultureInfo.InvariantCulture, FlowDirection.LeftToRight,
                                         new Typeface(MacTheme.Font, weight: FontWeight.Bold), MacTheme.Caption2, MacTheme.Brush(color));
            double x = leads ? points[i].X + 11 : points[i].X - 11 - text.Width;
            double y = points[i].Y - text.Height / 2;
            ctx.DrawRectangle(chip, null, new RoundedRect(new Rect(x - 3, y - 1, text.Width + 6, text.Height + 2), 4));
            ctx.DrawText(text, new Point(x, y));
        }
    }
}
