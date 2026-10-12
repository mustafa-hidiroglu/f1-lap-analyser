using Avalonia;
using Avalonia.Media;
using Avalonia.Media.Immutable;
using Avalonia.Styling;

namespace F1Lap.App;

/// macOS system colours in their dark and light variants, so the app reads like the Mac one.
/// Standard controls pick them up as dynamic resources (`Keys`); drawn controls ask `Theme`
/// directly and redraw when the theme changes.
public static class MacTheme
{
    public static bool IsDark => Application.Current?.ActualThemeVariant == ThemeVariant.Dark;

    private static Color Pick(uint dark, uint light) => Color.FromUInt32(IsDark ? dark : light);

    // System colours (NSColor.system*), as SwiftUI's .blue, .orange, ... resolve them.
    public static Color Blue => Pick(0xFF0A84FF, 0xFF007AFF);
    public static Color Orange => Pick(0xFFFF9F0A, 0xFFFF9500);
    public static Color Green => Pick(0xFF30D158, 0xFF28CD41);
    public static Color Red => Pick(0xFFFF453A, 0xFFFF3B30);
    public static Color Purple => Pick(0xFFBF5AF2, 0xFFAF52DE);
    public static Color Yellow => Pick(0xFFFFD60A, 0xFFFFCC00);
    public static Color Gray => Pick(0xFF98989D, 0xFF8E8E93);
    public static Color Amber => Color.FromRgb(255, 184, 0);

    // Text and chrome.
    public static Color Primary => Pick(0xE6FFFFFF, 0xD9000000);
    public static Color Secondary => Pick(0x8CFFFFFF, 0x80000000);
    public static Color Tertiary => Pick(0x40FFFFFF, 0x40000000);
    public static Color Gridline => Pick(0x26FFFFFF, 0x1F000000);
    public static Color WindowBackground => Pick(0xFF1E1E1E, 0xFFFFFFFF);
    public static Color ToolbarBackground => Pick(0xFF2B2B2B, 0xFFF6F6F6);
    public static Color SidebarBackground => Pick(0xFF2A2A2C, 0xFFEDEDED);
    public static Color BarBackground => Pick(0xFF2C2C2E, 0xFFF2F2F2);
    public static Color Separator => Pick(0xFF3A3A3A, 0xFFDCDCDC);
    public static Color ControlBackground => Pick(0xFF3A3A3C, 0xFFFFFFFF);
    public static Color ControlHover => Pick(0xFF454547, 0xFFF4F4F4);
    public static Color ControlBorder => Pick(0x00000000, 0xFFCFCFCF);
    public static Color SegmentSelected => Pick(0xFF636366, 0xFFFFFFFF);
    public static Color SegmentTrack => Pick(0xFF2E2E30, 0xFFE3E3E6);
    public static Color RowAlternate => Pick(0x0AFFFFFF, 0x08000000);

    // Lap colours (Palette in Format.swift).
    public static Color Reference => Blue;
    public static Color Other => Orange;
    public static Color Perfect => Green;
    public static Color Braking => Red;
    public static Color Lifting => Amber;

    /// Negative delta = compared lap gaining.
    public static Color Delta(double s) => s < 0 ? Green : s > 0 ? Red : Secondary;

    public static IBrush Brush(Color c) => new ImmutableSolidColorBrush(c);

    /// `a` mixed toward `b` by `t` (0 = a, 1 = b), like SwiftUI's Color.mix.
    public static Color Mix(Color a, Color b, double t)
    {
        t = Math.Clamp(t, 0, 1);
        byte L(byte x, byte y) => (byte)Math.Round(x + (y - x) * t);
        return Color.FromArgb(L(a.A, b.A), L(a.R, b.R), L(a.G, b.G), L(a.B, b.B));
    }

    public static Color WithAlpha(Color c, double alpha) =>
        Color.FromArgb((byte)Math.Round(c.A * Math.Clamp(alpha, 0, 1)), c.R, c.G, c.B);

    /// Resource keys for standard controls (bound with DynamicResource).
    public static class Keys
    {
        public const string Primary = "F1Primary", Secondary = "F1Secondary",
            WindowBackground = "F1WindowBackground", ToolbarBackground = "F1ToolbarBackground",
            SidebarBackground = "F1SidebarBackground", BarBackground = "F1BarBackground",
            Separator = "F1Separator", ControlBackground = "F1ControlBackground",
            ControlHover = "F1ControlHover", ControlBorder = "F1ControlBorder",
            SegmentSelected = "F1SegmentSelected", SegmentTrack = "F1SegmentTrack",
            RowAlternate = "F1RowAlternate", Accent = "F1Accent";
    }

    /// Writes the current variant's brushes into the application resources.
    public static void Apply(Application app)
    {
        var r = app.Resources;
        r[Keys.Primary] = Brush(Primary);
        r[Keys.Secondary] = Brush(Secondary);
        r[Keys.WindowBackground] = Brush(WindowBackground);
        r[Keys.ToolbarBackground] = Brush(ToolbarBackground);
        r[Keys.SidebarBackground] = Brush(SidebarBackground);
        r[Keys.BarBackground] = Brush(BarBackground);
        r[Keys.Separator] = Brush(Separator);
        r[Keys.ControlBackground] = Brush(ControlBackground);
        r[Keys.ControlHover] = Brush(ControlHover);
        r[Keys.ControlBorder] = Brush(ControlBorder);
        r[Keys.SegmentSelected] = Brush(SegmentSelected);
        r[Keys.SegmentTrack] = Brush(SegmentTrack);
        r[Keys.RowAlternate] = Brush(RowAlternate);
        r[Keys.Accent] = Brush(Blue);
        // Fluent controls (slider, check box, focus) take the Mac accent.
        r["SystemAccentColor"] = Blue;
        r["SystemAccentColorLight1"] = Mix(Blue, Colors.White, 0.15);
        r["SystemAccentColorLight2"] = Mix(Blue, Colors.White, 0.3);
        r["SystemAccentColorDark1"] = Mix(Blue, Colors.Black, 0.15);
        r["SystemAccentColorDark2"] = Mix(Blue, Colors.Black, 0.3);
    }

    /// Body text: Segoe UI Variable on Windows 11, Segoe UI on 10, Inter elsewhere (dev on a Mac).
    public static readonly FontFamily Font =
        new("Segoe UI Variable Text, Segoe UI, avares://Avalonia.Fonts.Inter/Assets#Inter");

    // SwiftUI macOS text styles, in points.
    public const double Body = 13, Callout = 12, Caption = 10.5, Caption2 = 10, Title3 = 15,
        Headline = 13;
}
