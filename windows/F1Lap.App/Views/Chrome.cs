using System.ComponentModel;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Templates;
using Avalonia.Layout;
using Avalonia.Media;
using F1Lap.Core;
using Grid = Avalonia.Controls.Grid;

namespace F1Lap.App.Views;

/// Season, event and session (SessionSidebar in ContentView.swift).
public sealed class SessionSidebar : UserControl
{
    private readonly AppModel _model;
    private readonly ComboBox _season;
    private readonly ListBox _events;
    private readonly ComboBox _session;
    private readonly Control _sessionRow;
    private bool _syncing;

    public SessionSidebar(AppModel model)
    {
        _model = model;
        _season = new ComboBox { ItemsSource = AppModel.Seasons.Select(y => y.ToString()).ToList(), MinWidth = 90 };
        _season.SelectionChanged += (_, _) =>
        {
            if (_syncing || _season.SelectedIndex < 0) return;
            _model.Year = AppModel.Seasons[_season.SelectedIndex];
        };
        _events = new ListBox
        {
            Classes = { "sidebar" },
            ItemTemplate = new FuncDataTemplate<Event>((e, _) => e is null ? new TextBlock() : Ui.V(2,
                new TextBlock { Text = e.Name, TextTrimming = TextTrimming.CharacterEllipsis },
                Ui.Text($"R{e.Round} · {e.Location} · {e.Date}", MacTheme.Caption, secondary: true))),
        };
        _events.SelectionChanged += (_, _) =>
        {
            if (_syncing) return;
            _model.EventRound = (_events.SelectedItem as Event)?.Round;
        };
        _session = new ComboBox { MinWidth = 140 };
        _session.SelectionChanged += (_, _) =>
        {
            if (_syncing) return;
            _model.SessionName = (_session.SelectedItem as ComboBoxItem)?.Tag as string;
        };
        _sessionRow = Ui.V(0, Ui.Divider(), Row("Session", _session));

        var grid = new Grid { RowDefinitions = new RowDefinitions("Auto,*,Auto") };
        grid.Children.Add(Row("Season", _season));
        Grid.SetRow(_events, 1);
        grid.Children.Add(_events);
        Grid.SetRow(_sessionRow, 2);
        grid.Children.Add(_sessionRow);
        Content = grid;

        Ui.Observe(this, _model, OnModelChanged);
        Sync();
    }

    private static Control Row(string label, Control picker) => new DockPanel
    {
        Margin = new Thickness(14, 10),
        Children =
        {
            new TextBlock { Text = label, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 10, 0) },
            picker,
        },
    };

    private void OnModelChanged(string? name)
    {
        if (name is nameof(AppModel.Year) or nameof(AppModel.Events) or nameof(AppModel.EventRound)
            or nameof(AppModel.Event) or nameof(AppModel.SessionName))
            Sync();
    }

    private void Sync()
    {
        _syncing = true;
        try
        {
            _season.SelectedIndex = AppModel.Seasons.ToList().IndexOf(_model.Year);
            if (!ReferenceEquals(_events.ItemsSource, _model.Events)) _events.ItemsSource = _model.Events;
            _events.SelectedItem = _model.Event;
            if (_model.Event is { } ev)
            {
                _sessionRow.IsVisible = true;
                var items = new List<ComboBoxItem> { new() { Content = "Choose…", Tag = null } };
                items.AddRange(ev.Sessions.Select(s => new ComboBoxItem { Content = s, Tag = s }));
                _session.ItemsSource = items;
                _session.SelectedItem = items.FirstOrDefault(i => (string?)i.Tag == _model.SessionName) ?? items[0];
            }
            else
            {
                _sessionRow.IsVisible = false;
            }
        }
        finally { _syncing = false; }
    }
}

/// Reference and compared lap pickers plus Compare (LapBar in ContentView.swift). Wraps the
/// compared picker onto a second row when the column is narrow, so it never forces the window
/// wider than it is.
public sealed class LapBar : UserControl
{
    private readonly AppModel _model;
    private readonly LapPicker _reference, _other;
    private readonly ComboBox _otherYear;
    private readonly Button _compare;
    private bool _syncing;

    public LapBar(AppModel model)
    {
        _model = model;
        _reference = new LapPicker(model, "Reference", MacTheme.Reference, isReference: true);
        _otherYear = new ComboBox { Width = 130 };
        ToolTip.SetTip(_otherYear, "Compare against the same event in another season");
        _otherYear.SelectionChanged += (_, _) =>
        {
            if (_syncing) return;
            _model.OtherYear = (_otherYear.SelectedItem as ComboBoxItem)?.Tag as int?;
        };
        _other = new LapPicker(model, "Compared", MacTheme.Other, isReference: false, accessory: _otherYear);
        _compare = new Button { Content = Ui.Label(Glyph.Chart, "Compare"), VerticalAlignment = VerticalAlignment.Top };
        ToolTip.SetTip(_compare, "Compare (Ctrl+Enter)");
        _compare.Click += (_, _) => _model.Compare();

        var pickers = new FlowPanel { Spacing = 16, LineSpacing = 6, Children = { _reference, _other } };
        var dock = new DockPanel { Margin = new Thickness(12, 8) };
        DockPanel.SetDock(_compare, Dock.Right);
        dock.Children.Add(_compare);
        dock.Children.Add(pickers);
        Content = dock;

        Ui.Observe(this, _model, name =>
        {
            if (name is nameof(AppModel.Year) or nameof(AppModel.OtherYear) or nameof(AppModel.CanCompare)
                or nameof(AppModel.Info))
                Sync();
        });
        Sync();
    }

    private void Sync()
    {
        _syncing = true;
        try
        {
            var items = new List<ComboBoxItem> { new() { Content = "Same session", Tag = null } };
            items.Add(new ComboBoxItem { Content = new Separator(), IsEnabled = false, MinHeight = 0, Padding = new Thickness(4, 2) });
            items.AddRange(AppModel.Seasons.Where(y => y != _model.Year)
                .Select(y => new ComboBoxItem { Content = y.ToString(), Tag = (int?)y }));
            _otherYear.ItemsSource = items;
            _otherYear.SelectedItem = items.FirstOrDefault(i => (int?)i.Tag == _model.OtherYear) ?? items[0];
            _compare.IsEnabled = _model.CanCompare;
            IsEnabled = _model.Info is not null;
        }
        finally { _syncing = false; }
    }
}

/// Dot, title, optional accessory, driver picker and lap picker (LapPicker in ContentView.swift).
public sealed class LapPicker : UserControl
{
    private readonly AppModel _model;
    private readonly bool _isReference;
    private readonly ComboBox _driver = new() { Width = 110 };
    private readonly ComboBox _lap = new() { Width = 160 };
    private bool _syncing;

    private LapChoice Choice
    {
        get => _isReference ? _model.Reference : _model.Other;
        set { if (_isReference) _model.Reference = value; else _model.Other = value; }
    }

    private SessionInfo? Info => _isReference ? _model.Info : _model.OtherSessionInfo;

    public LapPicker(AppModel model, string title, Color color, bool isReference, Control? accessory = null)
    {
        (_model, _isReference) = (model, isReference);
        ToolTip.SetTip(_driver, "★ Fastest: the session's fastest valid lap, whoever set it");
        _driver.SelectionChanged += (_, _) =>
        {
            if (_syncing || _driver.SelectedItem is not ComboBoxItem item) return;
            Choice = new LapChoice(item.Tag as LapChoice.Pick);  // a new driver starts on their fastest lap
        };
        _lap.SelectionChanged += (_, _) =>
        {
            if (_syncing || _lap.SelectedItem is not ComboBoxItem item) return;
            Choice = Choice with { Lap = item.Tag as int? };
        };
        var row = Ui.H(6, Ui.Dot(color, 9), Ui.Text(title, secondary: true));
        foreach (var c in row.Children) c.VerticalAlignment = VerticalAlignment.Center;
        if (accessory is not null) row.Children.Add(accessory);
        row.Children.Add(_driver);
        row.Children.Add(_lap);
        Content = row;

        Ui.Observe(this, _model, name =>
        {
            if (name is nameof(AppModel.Info) or nameof(AppModel.OtherInfo) or nameof(AppModel.OtherYear)
                or nameof(AppModel.Reference) or nameof(AppModel.Other))
                Sync();
        });
        Sync();
    }

    private void Sync()
    {
        _syncing = true;
        try
        {
            var info = Info;
            var choice = Choice;
            var drivers = new List<ComboBoxItem>
            {
                new() { Content = "Driver", Tag = null },
                new() { Content = "★ Fastest", Tag = LapChoice.Pick.SessionFastest.Instance },
                new() { Content = new Separator(), IsEnabled = false, MinHeight = 0, Padding = new Thickness(4, 2) },
            };
            drivers.AddRange((info?.Drivers ?? []).Select(d => new ComboBoxItem
            {
                Content = d.Position is { } p ? $"P{p}  {d.Code}" : d.Code,
                Tag = new LapChoice.Pick.Driver(d.Code),
            }));
            _driver.ItemsSource = drivers;
            _driver.SelectedItem = drivers.FirstOrDefault(i => Equals(i.Tag, choice.Choice)) ?? drivers[0];

            var laps = new List<ComboBoxItem>();
            if (choice.IsSessionFastest)
            {
                var best = info?.FastestLap();
                laps.Add(new ComboBoxItem
                {
                    Content = best is not null ? $"{best.Driver}  L{best.Lap}  {Fmt.LapTime(best.TimeS)}"
                        : info is null ? "Loading…" : "No valid lap",
                    Tag = null,
                });
            }
            else
            {
                laps.Add(new ComboBoxItem { Content = "Fastest", Tag = null });
                laps.AddRange(_model.LapsOf(choice.DriverCode, info).Select(l => new ComboBoxItem
                {
                    Content = $"L{l.Lap}  {Fmt.LapTime(l.TimeS)}{(l.Valid ? "" : "  ✕")}{(l.PersonalBest ? "  ★" : "")}",
                    Tag = (int?)l.Lap,
                }));
            }
            _lap.ItemsSource = laps;
            _lap.SelectedItem = laps.FirstOrDefault(i => (int?)i.Tag == choice.Lap) ?? laps[0];
            // The session-fastest pick fixes the lap, so this only shows who set it.
            _lap.IsEnabled = !choice.IsSessionFastest;
        }
        finally { _syncing = false; }
    }
}

/// Progress or the last error, on a bar under the content (StatusBar in ContentView.swift).
public sealed class StatusBar : UserControl
{
    private readonly AppModel _model;

    public StatusBar(AppModel model)
    {
        _model = model;
        Ui.Res(this, BackgroundProperty, MacTheme.Keys.BarBackground);
        Ui.Observe(this, _model, name =>
        {
            if (name is nameof(AppModel.Busy) or nameof(AppModel.Progress) or nameof(AppModel.Error))
                Sync();
        });
        Sync();
    }

    private void Sync()
    {
        IsVisible = _model.Busy is not null || _model.Error is not null;
        if (!IsVisible) return;
        var row = new DockPanel { Margin = new Thickness(12, 6) };
        if (_model.Busy is { } busy)
        {
            var left = Ui.H(8);
            if (_model.Progress is { Done: { } done, Total: { } total } p && total > 0)
            {
                left.Children.Add(new ProgressBar { Minimum = 0, Maximum = total, Value = done, Width = 120, VerticalAlignment = VerticalAlignment.Center });
                left.Children.Add(Ui.Text($"{p.Message} — {done}/{total}", MacTheme.Callout));
            }
            else
            {
                left.Children.Add(new ProgressBar { IsIndeterminate = true, Width = 16, Height = 16, MinWidth = 16, VerticalAlignment = VerticalAlignment.Center });
                left.Children.Add(Ui.Text(_model.Progress?.Message ?? busy, MacTheme.Callout));
            }
            row.Children.Add(left);
        }
        else if (_model.Error is { } error)
        {
            var dismiss = new Button { Content = "Dismiss", Classes = { "plain" } };
            dismiss.Click += (_, _) => _model.Error = null;
            DockPanel.SetDock(dismiss, Dock.Right);
            row.Children.Add(dismiss);
            row.Children.Add(Ui.H(8,
                new IconView(Glyph.Warning) { Width = 14, Height = 14, Brush = MacTheme.Brush(MacTheme.Yellow), VerticalAlignment = VerticalAlignment.Center },
                new SelectableTextBlock { Text = error, FontSize = MacTheme.Callout, TextWrapping = TextWrapping.Wrap, MaxLines = 2, VerticalAlignment = VerticalAlignment.Center }));
        }
        Content = row;
    }
}
