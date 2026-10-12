using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Templates;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Styling;
using F1Lap.App.Controls;
using F1Lap.Core;
using Grid = Avalonia.Controls.Grid;

namespace F1Lap.App.Views;

/// Summary, synced traces, track map and corner table for one comparison (CompareView.swift).
public sealed class CompareView : UserControl
{
    public const double ChartsMin = 440, PaneMin = 300, PaneIdeal = 420;

    public CompareView(AppModel model)
    {
        if (model.Comparison is not { } c)
        {
            Content = Ui.Placeholder(model.Info is null ? "Pick an event and session"
                                                        : "Choose two laps and press Compare (Ctrl+Enter)");
            return;
        }
        var sync = new ChartSync();
        var charts = new ScrollViewer
        {
            HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled,
            Content = Ui.V(14, Summary(c.Result), new TraceCharts(c, sync)),
            Padding = new Thickness(14),
        };
        var table = new CornerTable(c.Result);
        table.Selected += corner =>
        {
            double pad = (corner.EndM - corner.StartM) * 0.1;
            sync.Window = (Math.Max(0, corner.StartM - pad), Math.Min(c.Traces.LengthM, corner.EndM + pad));
        };
        var mapPanel = new Grid { RowDefinitions = new RowDefinitions("Auto,*"), Margin = new Thickness(10) };
        mapPanel.Children.Add(MapHeader());
        var trackMap = c.Traces.Track.Count == 0
            ? Ui.Placeholder("No position data")
            : (Control)new TrackMap(c.Traces.Track, c.Result.Circuit, sync);
        Grid.SetRow(trackMap, 1);
        mapPanel.Children.Add(trackMap);

        // Track map over the corner table, split by a draggable divider (VSplitView).
        var right = new Grid { RowDefinitions = new RowDefinitions("*,1,240") };
        right.RowDefinitions[0].MinHeight = 260;
        right.RowDefinitions[2].MinHeight = 160;
        right.Children.Add(mapPanel);
        var hsplit = new GridSplitter { ResizeDirection = GridResizeDirection.Rows, Height = 1, MinHeight = 1 };
        Ui.Res(hsplit, BackgroundProperty, MacTheme.Keys.Separator);
        Grid.SetRow(hsplit, 1);
        right.Children.Add(hsplit);
        Grid.SetRow(table, 2);
        right.Children.Add(table);

        Content = new TwoPane(charts, right, ChartsMin, PaneMin, PaneIdeal);
    }

    private static Control MapHeader()
    {
        var legend = Ui.H(10,
            Ui.H(4, Ui.Dot(MacTheme.Green, 8), Ui.Text("gaining", MacTheme.Caption2, color: MacTheme.Green)),
            Ui.H(4, Ui.Dot(MacTheme.Red, 8), Ui.Text("losing", MacTheme.Caption2, color: MacTheme.Red)));
        var dock = new DockPanel();
        DockPanel.SetDock(legend, Dock.Right);
        dock.Children.Add(legend);
        dock.Children.Add(Ui.Text("Track — coloured by delta", MacTheme.Caption, secondary: true));
        return dock;
    }

    private static Control Summary(CompareResult r)
    {
        // Name the season when the laps come from different years.
        bool years = r.Reference.Year != r.Other.Year;
        double delta = r.LapTimeDeltaS ?? r.FinalDeltaS;
        return new FlowPanel
        {
            Spacing = 28,
            LineSpacing = 10,
            Children =
            {
                Ui.Stat(Fmt.Lap(r.Reference, years), Fmt.LapTime(r.Reference.LapTimeS), MacTheme.Reference),
                Ui.Stat(Fmt.Lap(r.Other, years), Fmt.LapTime(r.Other.LapTimeS), MacTheme.Other),
                Ui.Stat("Delta", Fmt.Delta(delta), MacTheme.Delta(delta)),
                Ui.Stat("Best gain", $"{Fmt.Delta(r.MaxGainS)} @ {(int)r.MaxGainAtM} m", MacTheme.Secondary),
                Ui.Stat("Worst loss", $"{Fmt.Delta(r.MaxLossS)} @ {(int)r.MaxLossAtM} m", MacTheme.Secondary),
            },
        };
    }
}

/// Delta, speed, throttle, brake and gear on one distance axis, all zoomed and pointed together.
public sealed class TraceCharts : UserControl
{
    public TraceCharts(Comparison c, ChartSync sync)
    {
        var t = c.Traces;
        var pointer = Ui.Text("Pointer: —", MacTheme.Caption, secondary: true);
        var showAll = new Button { Content = Ui.Label(Glyph.Expand, "Show full lap", MacTheme.Caption), FontSize = MacTheme.Caption, IsVisible = false };
        showAll.Click += (_, _) => sync.Window = null;
        sync.Changed += () =>
        {
            pointer.Text = $"Pointer: {(sync.Cursor is { } d ? $"{(int)d} m" : "—")}";
            showAll.IsVisible = sync.Window is not null;
        };
        var header = new DockPanel { Height = 24 };
        DockPanel.SetDock(showAll, Dock.Right);
        header.Children.Add(showAll);
        pointer.VerticalAlignment = VerticalAlignment.Center;
        header.Children.Add(pointer);

        // Fixed speed ceiling: the corner labels otherwise crowd the automatic domain.
        double peak = t.Ref["speed"].Concat(t.Oth["speed"]).Select(p => p.V).DefaultIfEmpty(300).Max();
        double speedTop = Math.Ceiling(peak / 50) * 50;

        Content = Ui.V(10,
            header,
            Panel("Delta (s)", 110, new TraceChart { LengthM = t.LengthM, Sync = sync, ZeroRule = 0, Series = { new(t.Delta, () => MacTheme.Purple) } }),
            Panel("Speed (km/h)", 224, Pair("speed", corners: c.Result.Circuit.Corners, yDomain: (0, speedTop))),
            Panel("Throttle (%)", 90, Pair("throttle")),
            Panel("Brake", 60, Pair("brake")),
            Panel("Gear", 80, Pair("gear")));

        TraceChart Pair(string channel, IReadOnlyList<CircuitCorner>? corners = null, (double, double)? yDomain = null) =>
            new()
            {
                LengthM = t.LengthM, Sync = sync, Corners = corners, YDomain = yDomain,
                Series = { new(t.Ref[channel], () => MacTheme.Reference), new(t.Oth[channel], () => MacTheme.Other) },
            };
    }

    private static Control Panel(string title, double height, TraceChart chart)
    {
        chart.Height = height;
        return Ui.V(2, Ui.Text(title, MacTheme.Caption, secondary: true), chart);
    }
}

/// Corners with the time each phase gained or lost; selecting a row zooms the traces to it.
public sealed class CornerTable : UserControl
{
    private static readonly string[] Columns = ["Corner", "Δ", "Brake", "Mid", "Exit", "Min km/h"];
    private const string Widths = "1.1*,*,*,*,*,1.6*";

    public event Action<CornerComparison>? Selected;

    public CornerTable(CompareResult result)
    {
        var sectors = result.Sectors.GroupBy(s => s.Name).ToDictionary(g => g.Key, g => g.First());
        var header = new Grid { ColumnDefinitions = new ColumnDefinitions(Widths), Margin = new Thickness(16, 6, 16, 6) };
        for (int i = 0; i < Columns.Length; i++)
        {
            var h = Ui.Text(Columns[i], MacTheme.Callout, weight: FontWeight.Medium);
            Grid.SetColumn(h, i);
            header.Children.Add(h);
        }
        var rows = result.Corners.Select((corner, i) => (corner, i)).ToList();
        var list = new ListBox
        {
            Background = Brushes.Transparent,
            ItemsSource = rows,
            ItemTemplate = new FuncDataTemplate<(CornerComparison Corner, int Index)>((row, _) =>
            {
                var (c, i) = row;
                var g = new Grid { ColumnDefinitions = new ColumnDefinitions(Widths), Margin = new Thickness(8, 0) };
                var s = sectors.GetValueOrDefault(c.Name);
                Cell(g, 0, Ui.Text(c.Name));
                Cell(g, 1, DeltaCell(c.DeltaS));
                Cell(g, 2, DeltaCell(c.PhaseDeltaS.GetValueOrDefault("braking")));
                Cell(g, 3, DeltaCell(c.PhaseDeltaS.GetValueOrDefault("mid")));
                Cell(g, 4, DeltaCell(c.PhaseDeltaS.GetValueOrDefault("exit")));
                Cell(g, 5, Ui.Text($"{Fmt.Speed(s?.RefMinSpeed)} / {Fmt.Speed(s?.OtherMinSpeed)}"));
                return new Border
                {
                    Child = g, Padding = new Thickness(0, 4), CornerRadius = new CornerRadius(4),
                    Background = i % 2 == 1 ? MacTheme.Brush(MacTheme.RowAlternate) : Brushes.Transparent,
                };
            }),
        };
        list.Styles.Add(new Avalonia.Styling.Style(x => x.OfType<ListBoxItem>())
        {
            Setters =
            {
                new Avalonia.Styling.Setter(PaddingProperty, new Thickness(8, 0)),
                new Avalonia.Styling.Setter(MinHeightProperty, 0.0),
            },
        });
        list.SelectionChanged += (_, _) =>
        {
            if (list.SelectedItem is ValueTuple<CornerComparison, int> row) Selected?.Invoke(row.Item1);
        };
        ToolTip.SetTip(list, "Δ = compared − reference: negative means the compared lap is faster. Select a row to zoom the traces.");
        var grid = new Grid { RowDefinitions = new RowDefinitions("Auto,1,*"), MinWidth = MinTableWidth };
        grid.Children.Add(header);
        var line = Ui.Divider();
        Grid.SetRow(line, 1);
        grid.Children.Add(line);
        Grid.SetRow(list, 2);
        grid.Children.Add(list);
        // Like the Mac Table: columns keep a readable width and scroll sideways in a narrow pane.
        Content = new ScrollViewer
        {
            HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Auto,
            VerticalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled,
            Content = grid,
        };
    }

    private const double MinTableWidth = 360;

    private static void Cell(Grid g, int column, Control c)
    {
        Grid.SetColumn(c, column);
        c.VerticalAlignment = VerticalAlignment.Center;
        g.Children.Add(c);
    }

    private static Control DeltaCell(double? s) => Ui.Text(Fmt.Delta(s), color: MacTheme.Delta(s ?? 0));
}

/// Two panes side by side: the first flexible with a minimum, the second clamped between its
/// minimum and a preferred width the divider drags. Unlike a star Grid (or NSSplitView), it never
/// lets the panes add up to more than it has, so nothing is ever pushed off-screen.
public sealed class TwoPane : Panel
{
    private readonly Control _first, _second;
    private readonly Border _divider;
    private readonly double _firstMin, _secondMin;
    private double _preferred;
    private double? _dragStart;
    private double _dragWidth;

    public TwoPane(Control first, Control second, double firstMin, double secondMin, double secondIdeal)
    {
        (_first, _second, _firstMin, _secondMin, _preferred) = (first, second, firstMin, secondMin, secondIdeal);
        _divider = new Border { Width = 1, Cursor = new Cursor(StandardCursorType.SizeWestEast) };
        Ui.Res(_divider, Border.BackgroundProperty, MacTheme.Keys.Separator);
        // A wider, invisible grab area over the 1 px line.
        var grab = new Border { Width = 8, Background = Brushes.Transparent, Cursor = new Cursor(StandardCursorType.SizeWestEast) };
        grab.PointerPressed += (_, e) =>
        {
            _dragStart = e.GetPosition(this).X;
            _dragWidth = SecondWidth(Bounds.Width);
            e.Pointer.Capture(grab);
        };
        grab.PointerMoved += (_, e) =>
        {
            if (_dragStart is not { } start) return;
            _preferred = _dragWidth - (e.GetPosition(this).X - start);
            InvalidateArrange();
        };
        grab.PointerReleased += (_, e) =>
        {
            _dragStart = null;
            _preferred = SecondWidth(Bounds.Width);  // forget any overshoot past the clamp
            e.Pointer.Capture(null);
        };
        Children.Add(first);
        Children.Add(_divider);
        Children.Add(second);
        Children.Add(grab);
        _grab = grab;
    }

    private readonly Border _grab;

    private double SecondWidth(double total) =>
        Math.Min(Math.Max(_preferred, _secondMin), Math.Max(_secondMin, total - _firstMin - 1));

    protected override Size MeasureOverride(Size available)
    {
        double total = double.IsInfinity(available.Width) ? _firstMin + 1 + _preferred : available.Width;
        double second = SecondWidth(total);
        double first = Math.Max(0, total - second - 1);
        _first.Measure(new Size(first, available.Height));
        _second.Measure(new Size(second, available.Height));
        _divider.Measure(available);
        _grab.Measure(available);
        return new Size(_firstMin + 1 + _secondMin, 0);
    }

    protected override Size ArrangeOverride(Size final)
    {
        double second = SecondWidth(final.Width);
        double first = Math.Max(0, final.Width - second - 1);
        _first.Arrange(new Rect(0, 0, first, final.Height));
        _divider.Arrange(new Rect(first, 0, 1, final.Height));
        _grab.Arrange(new Rect(first - 3.5, 0, 8, final.Height));
        _second.Arrange(new Rect(first + 1, 0, second, final.Height));
        return final;
    }
}
