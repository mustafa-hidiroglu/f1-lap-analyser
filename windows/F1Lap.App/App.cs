using System.Reflection;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Controls.Presenters;
using Avalonia.Controls.Primitives;
using Avalonia.Data;
using Avalonia.Layout;
using Avalonia.Markup.Xaml.MarkupExtensions;
using Avalonia.Media;
using Avalonia.Styling;
using Avalonia.Themes.Fluent;
using F1Lap.Core;

namespace F1Lap.App;

public sealed class App : Application
{
    public override void Initialize()
    {
        Name = "F1 Lap Analyser";
        RequestedThemeVariant = ThemeVariant.Default;  // follow the system, like the Mac app
        Styles.Add(new FluentTheme());
        Styles.Add(MacStyles());
        MacTheme.Apply(this);
        ActualThemeVariantChanged += (_, _) => MacTheme.Apply(this);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            var config = LocateSidecar();
            var client = new SidecarClient(config ?? SidecarConfig.Repository(AppContext.BaseDirectory));
            var model = new AppModel(new F1LapService(client));
            var window = new MainWindow(model);
            desktop.MainWindow = window;
            desktop.ShutdownMode = ShutdownMode.OnMainWindowClose;
            // Never wait on the UI thread at exit: stop the sidecar (and anything it spawned) now.
            desktop.Exit += (_, _) => client.Terminate();
            DevSnapshot.ScheduleIfRequested(window, model);
            if (config is null) model.Error = MissingRepo;
            else _ = model.StartAsync();
        }
        base.OnFrameworkInitializationCompleted();
    }

    /// `F1LAP_REPO` if set, else the checkout this was built from, else the nearest folder
    /// above the executable with a `.venv` (personal use: the app runs the repository's
    /// virtualenv rather than a bundled interpreter, like the Mac app).
    private static SidecarConfig? LocateSidecar()
    {
        static bool HasVenv(string? dir) => dir is not null && File.Exists(SidecarConfig.VenvPython(dir));
        var env = Environment.GetEnvironmentVariable("F1LAP_REPO");
        var built = typeof(App).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>()
            .FirstOrDefault(a => a.Key == "F1LapRepo")?.Value;
        string? repo = !string.IsNullOrEmpty(env) ? env : HasVenv(built) ? built : null;
        for (var dir = new DirectoryInfo(AppContext.BaseDirectory); repo is null && dir is not null;
             dir = dir.Parent)
            if (HasVenv(dir.FullName)) repo = dir.FullName;
        return repo is null ? null : SidecarConfig.Repository(repo);
    }

    /// Shown when no checkout is found (the exe was moved, or built on another machine), rather
    /// than failing on a path that only existed where it was built.
    private const string MissingRepo = "No f1lap checkout with a .venv found. Set F1LAP_REPO to the "
        + "repository, or keep F1Lap.exe inside it, and run `uv sync` there.";

    /// Fluent controls reshaped toward their macOS counterparts: popup buttons, bordered
    /// buttons, sidebar selection.
    private static Styles MacStyles()
    {
        static IBinding Res(string key) => new DynamicResourceExtension(key);
        var styles = new Styles
        {
            new Style(x => x.OfType<Window>())
            {
                Setters =
                {
                    new Setter(TemplatedControl.FontFamilyProperty, MacTheme.Font),
                    new Setter(TemplatedControl.FontSizeProperty, MacTheme.Body),
                },
            },
            new Style(x => x.OfType<TextBlock>())
            {
                Setters = { new Setter(TextBlock.ForegroundProperty, Res(MacTheme.Keys.Primary)) },
            },
            // Popup buttons (NSPopUpButton): compact, rounded, filled.
            new Style(x => x.OfType<ComboBox>())
            {
                Setters =
                {
                    new Setter(TemplatedControl.CornerRadiusProperty, new CornerRadius(5)),
                    new Setter(Layoutable.MinHeightProperty, 24.0),
                    new Setter(Layoutable.HeightProperty, 26.0),
                    new Setter(TemplatedControl.PaddingProperty, new Thickness(10, 0, 4, 0)),
                    new Setter(TemplatedControl.FontSizeProperty, MacTheme.Body),
                    new Setter(TemplatedControl.BackgroundProperty, Res(MacTheme.Keys.ControlBackground)),
                    new Setter(TemplatedControl.BorderBrushProperty, Res(MacTheme.Keys.ControlBorder)),
                    new Setter(TemplatedControl.BorderThicknessProperty, new Thickness(0.5)),
                    new Setter(TemplatedControl.ForegroundProperty, Res(MacTheme.Keys.Primary)),
                },
            },
            new Style(x => x.OfType<ComboBoxItem>())
            {
                Setters =
                {
                    new Setter(Layoutable.MinHeightProperty, 24.0),
                    new Setter(TemplatedControl.PaddingProperty, new Thickness(10, 3)),
                    new Setter(TemplatedControl.FontSizeProperty, MacTheme.Body),
                },
            },
            // Bordered push buttons.
            new Style(x => x.OfType<Button>())
            {
                Setters =
                {
                    new Setter(TemplatedControl.CornerRadiusProperty, new CornerRadius(6)),
                    new Setter(Layoutable.MinHeightProperty, 24.0),
                    new Setter(TemplatedControl.PaddingProperty, new Thickness(10, 3)),
                    new Setter(TemplatedControl.FontSizeProperty, MacTheme.Body),
                    new Setter(TemplatedControl.BackgroundProperty, Res(MacTheme.Keys.ControlBackground)),
                    new Setter(TemplatedControl.BorderBrushProperty, Res(MacTheme.Keys.ControlBorder)),
                    new Setter(TemplatedControl.BorderThicknessProperty, new Thickness(0.5)),
                    new Setter(TemplatedControl.ForegroundProperty, Res(MacTheme.Keys.Primary)),
                },
            },
            new Style(x => x.OfType<Button>().Class(":pointerover").Template().OfType<ContentPresenter>())
            {
                Setters = { new Setter(ContentPresenter.BackgroundProperty, Res(MacTheme.Keys.ControlHover)) },
            },
            new Style(x => x.OfType<Button>().Class("plain"))
            {
                Setters =
                {
                    new Setter(TemplatedControl.BackgroundProperty, Brushes.Transparent),
                    new Setter(TemplatedControl.BorderThicknessProperty, new Thickness(0)),
                    new Setter(TemplatedControl.PaddingProperty, new Thickness(6, 3)),
                },
            },
            new Style(x => x.OfType<CheckBox>())
            {
                Setters =
                {
                    new Setter(TemplatedControl.FontSizeProperty, MacTheme.Caption),
                    new Setter(Layoutable.MinHeightProperty, 20.0),
                    new Setter(TemplatedControl.PaddingProperty, new Thickness(4, 0, 0, 0)),
                },
            },
            // Sidebar list: accent-filled rounded selection, like a source list.
            new Style(x => x.OfType<ListBox>().Class("sidebar"))
            {
                Setters =
                {
                    new Setter(TemplatedControl.BackgroundProperty, Brushes.Transparent),
                    new Setter(TemplatedControl.BorderThicknessProperty, new Thickness(0)),
                },
            },
            new Style(x => x.OfType<ListBox>().Class("sidebar").Descendant().OfType<ListBoxItem>())
            {
                Setters =
                {
                    new Setter(TemplatedControl.PaddingProperty, new Thickness(8, 4)),
                    new Setter(Layoutable.MarginProperty, new Thickness(8, 0)),
                    new Setter(TemplatedControl.CornerRadiusProperty, new CornerRadius(6)),
                },
            },
            SelectedItem(),
            SelectedItem(":pointerover"),
            SelectedItem(":pressed"),
            SelectedItem(":focus"),
            new Style(x => x.OfType<ListBox>().Class("sidebar").Descendant().OfType<ListBoxItem>()
                .Class(":selected").Descendant().OfType<TextBlock>())
            {
                Setters = { new Setter(TextBlock.ForegroundProperty, Brushes.White) },
            },
        };
        return styles;

        // Fluent restyles a selected item per state, so the accent fill is set for each.
        static Style SelectedItem(string? state = null) =>
            new(x =>
            {
                var item = x.OfType<ListBox>().Class("sidebar").Descendant().OfType<ListBoxItem>()
                    .Class(":selected");
                if (state is not null) item = item.Class(state);
                return item.Template().OfType<ContentPresenter>();
            })
            {
                Setters = { new Setter(ContentPresenter.BackgroundProperty, Res(MacTheme.Keys.Accent)) },
            };
    }
}
