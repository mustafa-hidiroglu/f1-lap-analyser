using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Media.Imaging;
using Avalonia.Threading;

namespace F1Lap.App;

/// Development aid, as in the Mac app: `F1LAP_SNAPSHOT=/path/shot.png` writes the window to a PNG
/// once the model is idle with results, then quits. `F1LAP_SNAPSHOT_SIZE=1600x1000` resizes the
/// window first; `F1LAP_SNAPSHOT_SIDEBAR=reopen` hides the sidebar, sizes the window, then shows
/// the sidebar again (the case that used to clip it). Waits on a timer, never blocking the UI.
public static class DevSnapshot
{
    public static void ScheduleIfRequested(MainWindow window, AppModel model)
    {
        if (Environment.GetEnvironmentVariable("F1LAP_SNAPSHOT") is not { Length: > 0 } path) return;
        var deadline = DateTime.UtcNow.AddSeconds(180);
        var poll = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(500) };
        poll.Tick += (_, _) =>
        {
            bool done = model.Tab == AppModel.Tabs.Compare ? model.Comparison is not null : model.Rating is not null;
            if (!(model.Busy is null && (done || model.Error is not null)) && DateTime.UtcNow < deadline) return;
            poll.Stop();
            Capture(window, path);
        };
        poll.Start();
    }

    private static void Capture(MainWindow window, string path)
    {
        bool reopen = Environment.GetEnvironmentVariable("F1LAP_SNAPSHOT_SIDEBAR") == "reopen";
        var steps = new Queue<(TimeSpan Delay, Action Step)>();
        if (reopen) steps.Enqueue((TimeSpan.Zero, window.ToggleSidebar));
        if (Environment.GetEnvironmentVariable("F1LAP_SNAPSHOT_SIZE")?.Split('x') is [var w, var h]
            && double.TryParse(w, out var width) && double.TryParse(h, out var height))
            steps.Enqueue((TimeSpan.FromMilliseconds(500), () => { window.Width = width; window.Height = height; }));
        if (reopen) steps.Enqueue((TimeSpan.FromMilliseconds(500), window.ToggleSidebar));
        steps.Enqueue((TimeSpan.FromSeconds(1), () =>  // let charts lay out
        {
            var size = new PixelSize((int)(window.Bounds.Width * window.RenderScaling),
                                     (int)(window.Bounds.Height * window.RenderScaling));
            using var bitmap = new RenderTargetBitmap(size, new Vector(96 * window.RenderScaling, 96 * window.RenderScaling));
            bitmap.Render(window);
            bitmap.Save(path);
            if (Application.Current?.ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
                desktop.Shutdown();
        }));
        Next();

        void Next()
        {
            if (!steps.TryDequeue(out var s)) return;
            DispatcherTimer.RunOnce(() => { s.Step(); Next(); }, s.Delay == TimeSpan.Zero ? TimeSpan.FromMilliseconds(1) : s.Delay);
        }
    }
}
