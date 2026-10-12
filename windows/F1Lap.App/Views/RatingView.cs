using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using F1Lap.App.Controls;
using F1Lap.Core;
using Grid = Avalonia.Controls.Grid;

namespace F1Lap.App.Views;

/// The rated lap against the field and the perfect lap (RatingView.swift).
public sealed class RatingView : UserControl
{
    public RatingView(AppModel model)
    {
        var side = new Segmented(["Reference", "Compared"], model.RatedSide == AppModel.Side.Reference ? 0 : 1) { Width = 200 };
        side.SelectionChanged += i => model.RatedSide = i == 0 ? AppModel.Side.Reference : AppModel.Side.Compared;
        var rate = new Button { Content = Ui.Label(Glyph.Gauge, "Rate"), IsEnabled = model.Key is not null };
        rate.Click += (_, _) => model.Rate();
        var header = new DockPanel { Margin = new Thickness(12) };
        DockPanel.SetDock(rate, Dock.Right);
        header.Children.Add(rate);
        header.Children.Add(Ui.H(8, Center(Ui.Text("Rate")), side));

        Control body;
        if (model.Rating is { } r)
        {
            var content = Ui.V(24);
            if (r.Perfect is { } perfect)
            {
                var driver = r.Driver + (r.LapNumber is { } n ? $" L{n}" : "");
                content.Children.Add(new PerfectReport(perfect, model.PerfectPlot, r.Circuit.RotationDeg, driver));
                content.Children.Add(Ui.Divider());
            }
            content.Children.Add(new RatingReport(r));
            body = new ScrollViewer
            {
                HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled,
                Padding = new Thickness(14),
                Content = content,
            };
        }
        else
        {
            body = Ui.Placeholder(model.Info is null ? "Pick an event and session" : "Press Rate");
        }
        var grid = new Grid { RowDefinitions = new RowDefinitions("Auto,1,*") };
        grid.Children.Add(header);
        var line = Ui.Divider();
        Grid.SetRow(line, 1);
        grid.Children.Add(line);
        Grid.SetRow(body, 2);
        grid.Children.Add(body);
        Content = grid;
    }

    internal static T Center<T>(T c) where T : Control
    {
        c.VerticalAlignment = VerticalAlignment.Center;
        return c;
    }
}

internal sealed class RatingReport : UserControl
{
    public RatingReport(Rating r)
    {
        string lap = r.Driver + (r.LapNumber is { } n ? $" L{n}" : "");
        var stats = new FlowPanel
        {
            Spacing = 32,
            LineSpacing = 12,
            Children =
            {
                new ScoreGauge(r.Score) { Width = 92, Height = 92 },
                RatingView.Center(Ui.Stat(lap, Fmt.LapTime(r.LapTimeS))),
                RatingView.Center(Ui.Stat("Theoretical best", Fmt.LapTime(r.TheoreticalBestS))),
                RatingView.Center(Ui.Stat("Left on the table", Fmt.Delta(r.TimeLeftS))),
                RatingView.Center(Ui.Stat("Session ultimate", Fmt.LapTime(r.UltimateS))),
                RatingView.Center(Ui.Stat("Gap to ultimate", Fmt.Delta(r.GapToUltimateS))),
            },
        };
        var note = Ui.Text($"Against {r.Laps} valid laps from {r.Drivers} drivers; segments cut on {Fmt.Lap(r.Reference)}. "
                           + "Score = mean corner percentile vs other drivers' bests.", MacTheme.Caption, secondary: true);
        note.TextWrapping = TextWrapping.Wrap;

        var chart = new BarChart(r.Segments.Select(s => s.Name).ToList(),
        [
            ("Field best", () => MacTheme.Red, r.Segments.Select(s => s.LostToFieldS).ToList()),
            ("Own best", () => MacTheme.Orange, r.Segments.Select(s => s.LostToOwnBestS).ToList()),
        ]) { Height = 200 };
        var bars = Ui.V(4, Ui.Text("Time lost per segment (s)", MacTheme.Caption, secondary: true), chart,
                        Legend(("Field best", MacTheme.Red), ("Own best", MacTheme.Orange)));

        Content = Ui.V(18, stats, note, bars, SegmentGrid(r));
    }

    internal static Control Legend(params (string Name, Color Color)[] items)
    {
        var p = Ui.H(12);
        foreach (var (name, color) in items)
            p.Children.Add(Ui.H(4, Ui.Dot(color, 8), Ui.Text(name, MacTheme.Caption2, secondary: true)));
        return p;
    }

    private static Control SegmentGrid(Rating r)
    {
        string[] headers = ["Segment", "Time", "Own best", "Lost", "Field best", "By", "Lost", "Rank", "Pctl"];
        var g = new Grid { ColumnDefinitions = new ColumnDefinitions(string.Join(",", headers.Select(_ => "Auto"))), ColumnSpacing = 18, RowSpacing = 6 };
        for (int i = 0; i < headers.Length; i++)
            Put(g, 0, i, Ui.Text(headers[i], MacTheme.Caption, secondary: true), leading: i is 0 or 5);
        g.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
        g.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
        var line = Ui.Divider();
        Grid.SetRow(line, 1);
        Grid.SetColumnSpan(line, headers.Length);
        g.Children.Add(line);
        int row = 2;
        foreach (var s in r.Segments)
        {
            g.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            Put(g, row, 0, T(s.Name), leading: true);
            Put(g, row, 1, T(Fmt.Fixed(s.TimeS, 3)));
            Put(g, row, 2, T(Fmt.Fixed(s.OwnBestS, 3) + (s.OwnBestLap is { } l ? $" (L{l})" : "")));
            Put(g, row, 3, T(Fmt.Delta(s.LostToOwnBestS), Loss(s.LostToOwnBestS)));
            Put(g, row, 4, T(Fmt.Fixed(s.FieldBestS, 3)));
            Put(g, row, 5, T(s.FieldBestBy), leading: true);
            Put(g, row, 6, T(Fmt.Delta(s.LostToFieldS), Loss(s.LostToFieldS)));
            Put(g, row, 7, T($"{s.Rank}/{r.Drivers}"));
            Put(g, row, 8, T(Fmt.Fixed(s.Percentile, 0)));
            row++;
        }
        return g;

        static TextBlock T(string s, Color? c = null) => Ui.Text(s, MacTheme.Callout, color: c);
        static Color Loss(double s) => s > 0.0005 ? MacTheme.Red : MacTheme.Secondary;
    }

    private static void Put(Grid g, int row, int col, Control c, bool leading = false)
    {
        Grid.SetRow(c, row);
        Grid.SetColumn(c, col);
        c.HorizontalAlignment = leading ? HorizontalAlignment.Left : HorizontalAlignment.Right;
        g.Children.Add(c);
    }
}

/// The lap against the session's simulated perfect lap, with reasons and the ghost replay.
internal sealed class PerfectReport : UserControl
{
    public PerfectReport(PerfectLap p, PerfectPlot? plot, double rotationDeg, string driver)
    {
        var content = Ui.V(14, Ui.Text("vs the perfect lap", MacTheme.Headline, weight: FontWeight.Bold));
        if (p.Error is { } error)
        {
            content.Children.Add(Ui.H(6, Ui.Secondary(new IconView(Glyph.Info) { Width = 14, Height = 14 }),
                                      Ui.Text($"No perfect lap for this session: {error}", secondary: true)));
            Content = content;
            return;
        }
        content.Children.Add(new FlowPanel
        {
            Spacing = 32,
            LineSpacing = 12,
            Children =
            {
                Ui.Stat("Perfect lap", Fmt.LapTime(p.SimLapTimeS)),
                Ui.Stat("Gap", Fmt.Delta(p.GapS)),
                Ui.Stat("Best laps' gap", Fmt.Delta(p.TypicalGapS)),
                Ui.Stat("Left on the table", Fmt.Delta(Math.Max((p.GapS ?? 0) - (p.TypicalGapS ?? 0), 0))),
            },
        });
        var lines = Ui.V(6);
        foreach (var (line, i) in (p.Summary ?? []).Select((l, i) => (l, i)))
        {
            var icon = new IconView(i == 0 ? Glyph.FlagCheckered : Glyph.TurnDownRight) { Width = 15, Height = 15, VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(0, 1, 0, 0) };
            if (i > 0) Ui.Secondary(icon);
            var text = new SelectableTextBlock { Text = line, TextWrapping = TextWrapping.Wrap };
            var row = new DockPanel();
            DockPanel.SetDock(icon, Dock.Left);
            icon.Margin = new Thickness(0, 1, 8, 0);
            row.Children.Add(icon);
            row.Children.Add(text);
            lines.Children.Add(row);
        }
        content.Children.Add(lines);
        if (plot?.Replay is { } replay)
            content.Children.Add(new GhostReplayView(replay, plot.Outline, rotationDeg, driver, p.LapTimeS, p.SimLapTimeS, p.GapS));
        if (plot is not null) content.Children.Add(SpeedVsPerfect(plot, p.Corners ?? []));
        content.Children.Add(CornerReasons(p.Corners ?? []));
        Content = content;
    }

    private static Control SpeedVsPerfect(PerfectPlot plot, IReadOnlyList<PerfectCorner> corners)
    {
        var chart = new TraceChart
        {
            LengthM = Math.Max(plot.LengthM, 1), Height = 200,
            Series = { new(plot.Sim, () => MacTheme.Green), new(plot.Lap, () => MacTheme.Reference) },
        };
        foreach (var c in corners.Where(c => c.ExcessS > 0.1))
        {
            double alpha = Math.Min(0.06 + c.ExcessS * 0.4, 0.3);
            chart.Bands.Add(new Band(c.StartM, c.EndM, () => MacTheme.WithAlpha(MacTheme.Red, alpha)));
        }
        var note = Ui.Text("Shaded: corners where this lap lost over 0.1 s more than the session's best laps.", MacTheme.Caption2, secondary: true);
        note.TextWrapping = TextWrapping.Wrap;
        return Ui.V(4, Ui.Text("Speed vs the perfect lap (km/h)", MacTheme.Caption, secondary: true), chart,
                    RatingReport.Legend(("Perfect", MacTheme.Green), ("This lap", MacTheme.Reference)), note);
    }

    private static Control CornerReasons(IReadOnlyList<PerfectCorner> corners)
    {
        var g = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,Auto,Auto,Auto,*"), ColumnSpacing = 16, RowSpacing = 8 };
        string[] headers = ["Corner", "Lost", "Best laps", "Excess", "Why"];
        g.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
        for (int i = 0; i < headers.Length; i++) Put(g, 0, i, Ui.Text(headers[i], MacTheme.Caption, secondary: true));
        g.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
        var line = Ui.Divider();
        Grid.SetRow(line, 1);
        Grid.SetColumnSpan(line, headers.Length);
        g.Children.Add(line);
        int row = 2;
        foreach (var c in corners)
        {
            g.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            Put(g, row, 0, Ui.Text(c.Name, MacTheme.Callout));
            Put(g, row, 1, Ui.Text(Fmt.Delta(c.LostS), MacTheme.Callout));
            Put(g, row, 2, Ui.Text(Fmt.Delta(c.TypicalLostS), MacTheme.Callout, secondary: true));
            Put(g, row, 3, Ui.Text(Fmt.Delta(c.ExcessS), MacTheme.Callout, color: c.ExcessS > 0.05 ? MacTheme.Red : MacTheme.Secondary));
            var why = Ui.V(2);
            foreach (var f in c.Findings)
            {
                var text = f.Text.StartsWith($"{c.Name}: ") ? f.Text[(c.Name.Length + 2)..] : f.Text;
                var t = Ui.Text(text, MacTheme.Callout, secondary: f.CostS is null);
                t.TextWrapping = TextWrapping.Wrap;
                why.Children.Add(t);
            }
            Put(g, row, 4, why);
            row++;
        }
        return g;
    }

    private static void Put(Grid g, int row, int col, Control c)
    {
        Grid.SetRow(c, row);
        Grid.SetColumn(c, col);
        c.VerticalAlignment = VerticalAlignment.Top;
        g.Children.Add(c);
    }
}
