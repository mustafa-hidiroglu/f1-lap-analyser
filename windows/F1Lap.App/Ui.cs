using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Documents;
using Avalonia.Controls.Primitives;
using Avalonia.Controls.Shapes;
using Avalonia.Layout;
using Avalonia.Markup.Xaml.MarkupExtensions;
using Avalonia.Media;

namespace F1Lap.App;

/// Small builders that keep the views close to their SwiftUI originals.
public static class Ui
{
    public static TextBlock Text(string text, double size = MacTheme.Body, bool secondary = false,
                                 FontWeight weight = FontWeight.Normal, Color? color = null)
    {
        var t = new TextBlock { Text = text, FontSize = size, FontWeight = weight };
        if (color is { } c) t.Foreground = MacTheme.Brush(c);
        else if (secondary) Secondary(t);
        return t;
    }

    /// SwiftUI's `.foregroundStyle(.secondary)`.
    public static T Secondary<T>(T control) where T : Control
    {
        control[!TextElement.ForegroundProperty] = new DynamicResourceExtension(MacTheme.Keys.Secondary);
        if (control is TextBlock t) t[!TextBlock.ForegroundProperty] = new DynamicResourceExtension(MacTheme.Keys.Secondary);
        return control;
    }

    /// Calls `onChange` with each changed property name while `owner` is on screen, so views
    /// rebuilt later (theme change, new results) don't leave handlers on the model behind.
    public static void Observe(Control owner, System.ComponentModel.INotifyPropertyChanged model,
                               Action<string?> onChange)
    {
        System.ComponentModel.PropertyChangedEventHandler handler = (_, e) => onChange(e.PropertyName);
        owner.AttachedToVisualTree += (_, _) => model.PropertyChanged += handler;
        owner.DetachedFromVisualTree += (_, _) => model.PropertyChanged -= handler;
    }

    public static T Res<T>(T control, AvaloniaProperty property, string key) where T : Control
    {
        control[!property] = new DynamicResourceExtension(key);
        return control;
    }

    /// A stat: caption title over a large semibold value (the Mac app's `stat(_:_:)`).
    public static Control Stat(string title, string value, Color? color = null) => new StackPanel
    {
        Spacing = 2,
        Children =
        {
            Text(title, MacTheme.Caption, secondary: true),
            Text(value, MacTheme.Title3, weight: FontWeight.SemiBold, color: color),
        },
    };

    public static Control Divider(bool vertical = false) => Res(new Border
    {
        Width = vertical ? 1 : double.NaN,
        Height = vertical ? double.NaN : 1,
    }, Border.BackgroundProperty, MacTheme.Keys.Separator);

    public static Control Dot(Color color, double size) =>
        new Ellipse { Width = size, Height = size, Fill = MacTheme.Brush(color), VerticalAlignment = VerticalAlignment.Center };

    public static StackPanel H(double spacing, params Control[] children)
    {
        var p = new StackPanel { Orientation = Orientation.Horizontal, Spacing = spacing };
        p.Children.AddRange(children);
        return p;
    }

    public static StackPanel V(double spacing, params Control[] children)
    {
        var p = new StackPanel { Spacing = spacing };
        p.Children.AddRange(children);
        return p;
    }

    /// Glyph then label, like `Button(_:systemImage:)`.
    public static Control Label(Glyph icon, string text, double size = MacTheme.Body) => new StackPanel
    {
        Orientation = Orientation.Horizontal,
        Spacing = 6,
        Children =
        {
            new IconView(icon) { Width = size + 2, Height = size + 2, VerticalAlignment = VerticalAlignment.Center },
            new TextBlock { Text = text, VerticalAlignment = VerticalAlignment.Center },
        },
    };

    /// ContentUnavailableView: a large icon over a bold title, centred.
    public static Control Placeholder(string text) => new StackPanel
    {
        HorizontalAlignment = HorizontalAlignment.Center,
        VerticalAlignment = VerticalAlignment.Center,
        Spacing = 12,
        Children =
        {
            Secondary(new IconView(Glyph.FlagCheckered) { Width = 44, Height = 44, HorizontalAlignment = HorizontalAlignment.Center }),
            new TextBlock
            {
                Text = text, FontSize = 19, FontWeight = FontWeight.Bold,
                HorizontalAlignment = HorizontalAlignment.Center, TextAlignment = TextAlignment.Center,
                TextWrapping = TextWrapping.Wrap,
            },
        },
    };
}

/// SF Symbols stand-ins, drawn on a 16×16 grid: stroked outline plus optional fill.
public sealed record Glyph(string? Stroke, string? Fill = null, double StrokeWidth = 1.5)
{
    public static readonly Glyph Play = new(null, "M4.5,2.5 L13.5,8 L4.5,13.5 Z");
    public static readonly Glyph Pause = new(null, "M3.5,2.5 H6.5 V13.5 H3.5 Z M9.5,2.5 H12.5 V13.5 H9.5 Z");
    public static readonly Glyph Sidebar = new(
        "M2,2.5 H14 A1.5,1.5 0 0 1 15.5,4 V12 A1.5,1.5 0 0 1 14,13.5 H2 A1.5,1.5 0 0 1 0.5,12 V4 A1.5,1.5 0 0 1 2,2.5 Z M5.5,2.5 V13.5",
        null, 1.2);
    public static readonly Glyph Chart = new("M1.5,1.5 V14.5 H14.5 M3.5,11.5 L6.5,6.5 L9.5,9.5 L14,3.5");
    public static readonly Glyph Gauge = new("M2,12.5 A6.5,6.5 0 1 1 14,12.5 M8,10.5 L11,6", "M7,10.5 A1,1 0 1 0 9,10.5 A1,1 0 1 0 7,10.5 Z");
    public static readonly Glyph FlagCheckered = new(
        "M3,1.5 V15",
        "M3,2 H6.4 V4.4 H3 Z M9.8,2 H13.2 V4.4 H9.8 Z M6.4,4.4 H9.8 V6.8 H6.4 Z M3,6.8 H6.4 V9.2 H3 Z M9.8,6.8 H13.2 V9.2 H9.8 Z M6.4,2 H9.8 V2.4 H6.4 Z",
        1.4);
    public static readonly Glyph TurnDownRight = new("M3.5,2 V8.5 A2,2 0 0 0 5.5,10.5 H13 M10,7.5 L13,10.5 L10,13.5");
    public static readonly Glyph Expand = new("M9.5,1.5 H14.5 V6.5 M14.5,1.5 L9,7 M6.5,14.5 H1.5 V9.5 M1.5,14.5 L7,9");
    public static readonly Glyph Warning = new(null, "M8,1 L15.5,14.5 H0.5 Z");
    public static readonly Glyph Info = new("M8,1.5 A6.5,6.5 0 1 1 7.99,1.5 Z M8,7 V11.5", "M7.1,4.6 A0.9,0.9 0 1 0 8.9,4.6 A0.9,0.9 0 1 0 7.1,4.6 Z");
}

/// Draws an `Glyph` scaled to its size in the inherited foreground (or `Brush`).
public sealed class IconView : Control
{
    private readonly Geometry? _stroke, _fill;
    private readonly double _strokeWidth;

    public IBrush? Brush { get; set; }

    public IconView(Glyph icon)
    {
        _stroke = icon.Stroke is null ? null : StreamGeometry.Parse(icon.Stroke);
        _fill = icon.Fill is null ? null : StreamGeometry.Parse(icon.Fill);
        _strokeWidth = icon.StrokeWidth;
    }

    static IconView()
    {
        AffectsRender<IconView>(TextElement.ForegroundProperty);
    }

    public override void Render(DrawingContext ctx)
    {
        var brush = Brush ?? TextElement.GetForeground(this) ?? MacTheme.Brush(MacTheme.Primary);
        double s = Math.Min(Bounds.Width, Bounds.Height) / 16;
        using var _ = ctx.PushTransform(Matrix.CreateScale(s, s)
            * Matrix.CreateTranslation((Bounds.Width - 16 * s) / 2, (Bounds.Height - 16 * s) / 2));
        if (_fill is not null) ctx.DrawGeometry(brush, null, _fill);
        if (_stroke is not null)
            ctx.DrawGeometry(null, new Pen(brush, _strokeWidth, lineCap: PenLineCap.Round, lineJoin: PenLineJoin.Round), _stroke);
    }
}

/// A macOS segmented control: a rounded track with a raised selected segment.
public sealed class Segmented : Border
{
    private readonly List<Button> _buttons = [];
    private int _selected;

    public event Action<int>? SelectionChanged;

    public Segmented(IEnumerable<string> labels, int selected = 0, double fontSize = MacTheme.Body)
    {
        CornerRadius = new CornerRadius(6);
        Padding = new Thickness(2);
        Ui.Res(this, BackgroundProperty, MacTheme.Keys.SegmentTrack);
        var grid = new UniformGrid { Rows = 1 };
        foreach (var (label, i) in labels.Select((l, i) => (l, i)))
        {
            var b = new Button
            {
                Content = label, FontSize = fontSize, Padding = new Thickness(12, 2),
                MinHeight = 20, CornerRadius = new CornerRadius(5), BorderThickness = new Thickness(0),
                HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Center,
            };
            b.Click += (_, _) => Select(i, notify: true);
            _buttons.Add(b);
            grid.Children.Add(b);
        }
        Child = grid;
        Select(selected, notify: false);
    }

    public int SelectedIndex
    {
        get => _selected;
        set => Select(value, notify: false);
    }

    private void Select(int index, bool notify)
    {
        bool changed = index != _selected;
        _selected = index;
        for (int i = 0; i < _buttons.Count; i++)
        {
            if (i == index) Ui.Res(_buttons[i], BackgroundProperty, MacTheme.Keys.SegmentSelected);
            else _buttons[i].Background = Brushes.Transparent;
        }
        if (notify && changed) SelectionChanged?.Invoke(index);
    }
}

/// Lays children out left to right at their desired size, wrapping onto new lines: the Mac
/// app's FlowLayout, so rows of stats never force the window wider than it is.
public sealed class FlowPanel : Panel
{
    public double Spacing { get; set; } = 16;
    public double LineSpacing { get; set; } = 8;

    protected override Size MeasureOverride(Size available)
    {
        double x = 0, y = 0, line = 0, width = 0;
        foreach (var c in Children)
        {
            c.Measure(Size.Infinity);
            var s = c.DesiredSize;
            if (x > 0 && x + Spacing + s.Width > available.Width)
            {
                y += line + LineSpacing;
                x = 0;
                line = 0;
            }
            x += (x > 0 ? Spacing : 0) + s.Width;
            line = Math.Max(line, s.Height);
            width = Math.Max(width, x);
        }
        return new Size(double.IsInfinity(available.Width) ? width : Math.Min(width, available.Width), y + line);
    }

    protected override Size ArrangeOverride(Size final)
    {
        double x = 0, y = 0, line = 0;
        foreach (var c in Children)
        {
            var s = c.DesiredSize;
            if (x > 0 && x + Spacing + s.Width > final.Width)
            {
                y += line + LineSpacing;
                x = 0;
                line = 0;
            }
            if (x > 0) x += Spacing;
            c.Arrange(new Rect(x, y, s.Width, s.Height));
            x += s.Width;
            line = Math.Max(line, s.Height);
        }
        return final;
    }
}
