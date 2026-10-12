using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Platform;
using F1Lap.App.Views;

namespace F1Lap.App;

/// Sidebar plus detail column under a unified toolbar, like the Mac window
/// (NavigationSplitView in ContentView.swift).
///
/// Window sizing: the minimum width is the detail column's minimum plus the sidebar when it is
/// shown, and showing the sidebar in a window too narrow for both grows the window instead of
/// squeezing or clipping the sidebar (the bug the Mac app had).
public sealed class MainWindow : Window
{
    /// Narrowest the detail column gets: the Compare tab's chart pane and track pane minimums
    /// plus the divider; everything else in the column fits or wraps in that.
    public const double DetailMinWidth = 760;
    public const double SidebarMin = 220, SidebarMax = 340;
    private const double ToolbarHeight = 52;

    private readonly AppModel _model;
    private double _sidebarWidth = 250;
    private bool _sidebarShown = true;
    private ContentControl _content = new();
    private Control? _sidebarPane, _sidebarGrab;
    private ColumnDefinition? _sidebarColumn;
    private Segmented? _tabs;
    private Button? _toggle;

    public MainWindow(AppModel model)
    {
        _model = model;
        Title = "F1 Lap Analyser";
        Width = 1280;
        Height = 820;
        MinHeight = 640;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        // Draw the toolbar in the title bar, as macOS's unified toolbar does; the system keeps
        // the caption buttons (Windows) or traffic lights (macOS).
        ExtendClientAreaToDecorationsHint = true;
        ExtendClientAreaChromeHints = ExtendClientAreaChromeHints.PreferSystemChrome;
        ExtendClientAreaTitleBarHeightHint = ToolbarHeight;
        Ui.Res(this, BackgroundProperty, MacTheme.Keys.WindowBackground);

        KeyBindings.Add(new KeyBinding
        {
            Gesture = new KeyGesture(Key.Enter, KeyModifiers.Control),
            Command = new Command(() => { if (_model.CanCompare) _model.Compare(); }),
        });
        KeyBindings.Add(new KeyBinding
        {
            Gesture = new KeyGesture(Key.S, KeyModifiers.Control | KeyModifiers.Alt),
            Command = new Command(ToggleSidebar),
        });

        _model.PropertyChanged += (_, e) =>
        {
            switch (e.PropertyName)
            {
                case nameof(AppModel.Tab):
                    if (_tabs is not null) _tabs.SelectedIndex = (int)_model.Tab;
                    ShowTab();
                    break;
                case nameof(AppModel.Comparison) when _model.Tab == AppModel.Tabs.Compare:
                case nameof(AppModel.Info):
                case nameof(AppModel.Rating) when _model.Tab == AppModel.Tabs.Rating:
                case nameof(AppModel.PerfectPlot) when _model.Tab == AppModel.Tabs.Rating:
                    ShowTab();
                    break;
            }
        };
        ActualThemeVariantChanged += (_, _) => Build();  // drawn colours are read at build time
        Build();
    }

    public bool SidebarShown => _sidebarShown;

    private double RequiredWidth => DetailMinWidth + (_sidebarShown ? _sidebarWidth + 1 : 0);

    private void Build()
    {
        var sidebar = new SessionSidebar(_model);
        var sidebarPane = new Grid { RowDefinitions = new RowDefinitions($"{ToolbarHeight},*") };
        Ui.Res(sidebarPane, Panel.BackgroundProperty, MacTheme.Keys.SidebarBackground);
        Grid.SetRow(sidebar, 1);
        sidebarPane.Children.Add(sidebar);
        // On a Mac (development) the traffic lights sit on the sidebar's top edge, as in the
        // real app; on Windows the app name goes there.
        if (!OperatingSystem.IsMacOS())
            sidebarPane.Children.Add(new TextBlock
            {
                Text = "F1 Lap Analyser", FontWeight = FontWeight.SemiBold, Margin = new Thickness(16, 0),
                VerticalAlignment = VerticalAlignment.Center, IsHitTestVisible = false,
            });

        // Resizing the sidebar: a grab strip over its right edge.
        var grab = new Border { Width = 6, Background = Brushes.Transparent, Cursor = new Cursor(StandardCursorType.SizeWestEast), HorizontalAlignment = HorizontalAlignment.Right };
        double? dragFrom = null, startWidth = null;
        grab.PointerPressed += (_, e) => { dragFrom = e.GetPosition(this).X; startWidth = _sidebarWidth; e.Pointer.Capture(grab); };
        grab.PointerMoved += (_, e) =>
        {
            if (dragFrom is not { } from || startWidth is not { } w0) return;
            // Never wider than the window leaves room for alongside the detail column.
            double room = Bounds.Width - DetailMinWidth - 1;
            _sidebarWidth = Math.Clamp(w0 + e.GetPosition(this).X - from, SidebarMin, Math.Max(SidebarMin, Math.Min(SidebarMax, room)));
            ApplySidebar();
        };
        grab.PointerReleased += (_, e) => { dragFrom = null; e.Pointer.Capture(null); };

        var detail = new Grid { RowDefinitions = new RowDefinitions($"{ToolbarHeight},Auto,1,*,Auto"), MinWidth = DetailMinWidth };
        detail.Children.Add(Toolbar());
        var lapBar = new LapBar(_model);
        Grid.SetRow(lapBar, 1);
        detail.Children.Add(lapBar);
        var line = Ui.Divider();
        Grid.SetRow(line, 2);
        detail.Children.Add(line);
        _content = new ContentControl();
        Grid.SetRow(_content, 3);
        detail.Children.Add(_content);
        var status = new StatusBar(_model);
        Grid.SetRow(status, 4);
        detail.Children.Add(status);

        _sidebarColumn = new ColumnDefinition(_sidebarWidth, GridUnitType.Pixel);
        var root = new Grid
        {
            ColumnDefinitions = { _sidebarColumn, new ColumnDefinition(1, GridUnitType.Pixel), new ColumnDefinition(1, GridUnitType.Star) },
        };
        root.Children.Add(sidebarPane);
        var separator = Ui.Divider(vertical: true);
        Grid.SetColumn(separator, 1);
        root.Children.Add(separator);
        Grid.SetColumn(detail, 2);
        root.Children.Add(detail);
        root.Children.Add(grab);
        (_sidebarPane, _sidebarGrab) = (sidebarPane, grab);
        Content = root;
        ApplySidebar();
        ShowTab();
    }

    private Control Toolbar()
    {
        var toolbar = new Grid();
        Ui.Res(toolbar, Panel.BackgroundProperty, MacTheme.Keys.ToolbarBackground);
        var bottom = Ui.Divider();
        bottom.VerticalAlignment = VerticalAlignment.Bottom;
        toolbar.Children.Add(bottom);

        var toggle = new Button
        {
            Classes = { "plain" }, Content = new IconView(Glyph.Sidebar) { Width = 18, Height = 18 },
            HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(10, 0), Padding = new Thickness(6, 4),
        };
        Ui.Secondary(toggle);
        ToolTip.SetTip(toggle, "Show or hide the sidebar (Ctrl+Alt+S)");
        toggle.Click += (_, _) => ToggleSidebar();
        toolbar.Children.Add(toggle);
        _toggle = toggle;

        _tabs = new Segmented(["Compare", "Rating"], (int)_model.Tab)
        {
            Width = 200, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center,
        };
        _tabs.SelectionChanged += i => _model.Tab = (AppModel.Tabs)i;
        toolbar.Children.Add(_tabs);
        return toolbar;
    }

    public void ToggleSidebar()
    {
        _sidebarShown = !_sidebarShown;
        ApplySidebar();
    }

    private void ApplySidebar()
    {
        if (_sidebarColumn is null || _sidebarPane is null || _sidebarGrab is null) return;
        _sidebarPane.IsVisible = _sidebarGrab.IsVisible = _sidebarShown;
        _sidebarColumn.Width = new GridLength(_sidebarShown ? _sidebarWidth : 0, GridUnitType.Pixel);
        _sidebarGrab.Margin = new Thickness(_sidebarWidth - 3, 0, 0, 0);
        _sidebarGrab.HorizontalAlignment = HorizontalAlignment.Left;
        // The toggle clears the macOS traffic lights when the sidebar is hidden.
        if (_toggle is not null)
            _toggle.Margin = new Thickness(OperatingSystem.IsMacOS() && !_sidebarShown ? 80 : 10, 0, 0, 0);
        MinWidth = RequiredWidth;
        if (WindowState == WindowState.Normal && Width < RequiredWidth)
        {
            // Grow (to the right, or left if the screen edge is in the way) rather than clip.
            double grow = RequiredWidth - Width;
            Width = RequiredWidth;
            if (Screens.ScreenFromWindow(this)?.WorkingArea is { } area)
            {
                double scale = RenderScaling;
                double right = Position.X + RequiredWidth * scale;
                if (right > area.Right)
                    Position = new PixelPoint(Math.Max(area.X, (int)(Position.X - grow * scale)), Position.Y);
            }
        }
    }

    private void ShowTab()
    {
        _content.Content = _model.Tab == AppModel.Tabs.Compare ? new CompareView(_model) : new RatingView(_model);
    }

    /// Minimal ICommand for key bindings.
    private sealed class Command(Action run) : System.Windows.Input.ICommand
    {
        public event EventHandler? CanExecuteChanged { add { } remove { } }
        public bool CanExecute(object? parameter) => true;
        public void Execute(object? parameter) => run();
    }
}
