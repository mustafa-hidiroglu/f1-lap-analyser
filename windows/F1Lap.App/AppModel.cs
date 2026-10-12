using System.ComponentModel;
using System.Runtime.CompilerServices;
using Avalonia.Threading;
using F1Lap.Core;

namespace F1Lap.App;

/// A finished comparison, with traces prepared for plotting.
public sealed record Comparison(CompareResult Result, PlotTraces Traces);

/// The app's state and the sidecar calls behind it: a port of AppModel.swift. Lives on the UI
/// thread; awaits resume there, and the heavy lifting (sidecar, trace decoding, thinning) runs
/// elsewhere, so the UI never blocks.
public sealed class AppModel(F1LapService service) : INotifyPropertyChanged
{
    public enum Tabs { Compare, Rating }
    public enum Side { Reference, Compared }

    public event PropertyChangedEventHandler? PropertyChanged;

    public F1LapService Service { get; } = service;

    /// Seasons with FastF1 telemetry (2018 on), newest first.
    public static readonly IReadOnlyList<int> Seasons =
        Enumerable.Range(2018, DateTime.Now.Year - 2018 + 1).Reverse().ToList();

    private int _year = DateTime.Now.Year - 1;
    public int Year
    {
        get => _year;
        set
        {
            if (!Set(ref _year, value)) return;
            if (OtherYear == value) OtherYear = null;
            _ = LoadScheduleAsync();
        }
    }

    private IReadOnlyList<Event> _events = [];
    public IReadOnlyList<Event> Events { get => _events; private set => Set(ref _events, value); }

    private int? _eventRound;
    public int? EventRound
    {
        get => _eventRound;
        set
        {
            if (!Set(ref _eventRound, value)) return;
            OnPropertyChanged(nameof(Event));
            SessionName = null;
        }
    }

    private string? _sessionName;
    public string? SessionName
    {
        get => _sessionName;
        set { if (Set(ref _sessionName, value)) LoadSession(); }
    }

    private SessionInfo? _info;
    public SessionInfo? Info { get => _info; private set => Set(ref _info, value); }

    private LapChoice _reference = new();
    public LapChoice Reference { get => _reference; set => Set(ref _reference, value); }

    private LapChoice _other = new();
    public LapChoice Other { get => _other; set => Set(ref _other, value); }

    /// Season for the compared lap; null = the same session as the reference. Another season
    /// loads the same event (matched by circuit) and session name in that year.
    private int? _otherYear;
    public int? OtherYear
    {
        get => _otherYear;
        set { if (Set(ref _otherYear, value)) LoadOtherSession(); }
    }

    private SessionKey? _otherKey;
    public SessionKey? OtherKey { get => _otherKey; private set => Set(ref _otherKey, value); }

    private SessionInfo? _otherInfo;
    public SessionInfo? OtherInfo { get => _otherInfo; private set => Set(ref _otherInfo, value); }

    private Comparison? _comparison;
    public Comparison? Comparison { get => _comparison; private set => Set(ref _comparison, value); }

    private Rating? _rating;
    public Rating? Rating { get => _rating; private set => Set(ref _rating, value); }

    private PerfectPlot? _perfectPlot;
    public PerfectPlot? PerfectPlot { get => _perfectPlot; private set => Set(ref _perfectPlot, value); }

    private Tabs _tab = Tabs.Compare;
    public Tabs Tab { get => _tab; set => Set(ref _tab, value); }

    private Side _ratedSide = Side.Reference;
    public Side RatedSide
    {
        get => _ratedSide;
        set { if (Set(ref _ratedSide, value)) Rate(); }
    }

    /// What the sidecar is working on, for the status line; null when idle.
    private string? _busy;
    public string? Busy { get => _busy; private set => Set(ref _busy, value); }

    /// Latest sidecar progress for the running request (e.g. "Reading 934 laps… 400/934").
    private SidecarProgress? _progress;
    public SidecarProgress? Progress { get => _progress; private set => Set(ref _progress, value); }

    private string? _error;
    public string? Error { get => _error; set => Set(ref _error, value); }

    private Task? _sessionTask, _otherTask;
    private CancellationTokenSource? _sessionCts, _otherCts, _analysisCts, _ratingCts;

    public Event? Event => Events.FirstOrDefault(e => e.Round == EventRound);

    public SessionKey? Key =>
        Event is { } e && SessionName is { } s ? new SessionKey(Year, e.Name, s) : null;

    /// Session of the compared lap: its own season's, or the reference session.
    public SessionKey? OtherSessionKey => OtherYear is null ? Key : OtherKey;
    public SessionInfo? OtherSessionInfo => OtherYear is null ? Info : OtherInfo;

    public bool CanCompare
    {
        get
        {
            if (Key is not { } key || OtherSessionKey is not { } otherKey
                || Reference.RefIn(Info) is not { } r || Other.RefIn(OtherSessionInfo) is not { } o)
                return false;
            return key != otherKey || r != o;
        }
    }

    public async Task StartAsync()
    {
        try
        {
            await Service.PingAsync();
        }
        catch (Exception e)
        {
            Error = e.Message;
            return;
        }
        Service.Client.Progress += p => Dispatcher.UIThread.Post(() => { if (Busy is not null) Progress = p; });
        await LoadScheduleAsync();
        if (Environment.GetEnvironmentVariable("F1LAP_OPEN") is { Length: > 0 } spec) await OpenAsync(spec);
    }

    /// Development shortcut: `F1LAP_OPEN=2024/Monza/Qualifying/LEC/SAI[/rating]` opens that
    /// session and compares the two drivers' fastest laps; `…/HAM/HAM@2025` takes the compared
    /// lap from the same event in another season; `fastest` picks the session's fastest lap.
    private async Task OpenAsync(string spec)
    {
        var parts = spec.Split('/');
        if (parts.Length < 5 || !int.TryParse(parts[0], out var y)) return;
        if (y != Year)
        {
            _year = y;
            OnPropertyChanged(nameof(Year));
            await LoadScheduleAsync();
        }
        var needle = parts[1].ToLowerInvariant();
        EventRound = Events.FirstOrDefault(e => e.Name.ToLowerInvariant().Contains(needle)
                                                || e.Location.ToLowerInvariant().Contains(needle))?.Round;
        SessionName = parts[2];
        if (_sessionTask is not null) await _sessionTask;
        Reference = LapChoice.FromSpec(parts[3]);
        var otherSpec = parts[4].Split('@');
        if (otherSpec.Length == 2 && int.TryParse(otherSpec[1], out var oy))
        {
            OtherYear = oy;
            if (_otherTask is not null) await _otherTask;
        }
        Other = LapChoice.FromSpec(otherSpec[0]);
        if (parts.Length > 5 && parts[5] == "rating") Tab = Tabs.Rating;
        Compare();
    }

    public async Task LoadScheduleAsync()
    {
        int year = Year;
        await Run($"Loading {year} calendar", async () =>
        {
            var events = await Service.ScheduleAsync(year);
            if (year != Year) return;
            Events = events;
            if (!events.Any(e => e.Round == EventRound)) EventRound = null;
            OnPropertyChanged(nameof(Event));
        });
    }

    private void LoadSession()
    {
        _sessionCts?.Cancel();
        Info = null;
        Comparison = null;
        Rating = null;
        PerfectPlot = null;
        if (Key is not { } key)
        {
            _sessionTask = null;
            LoadOtherSession();
            return;
        }
        var cts = _sessionCts = new CancellationTokenSource();
        _sessionTask = Run($"Loading {key.Event} {key.Session} (first load downloads telemetry)", async () =>
        {
            var info = await Service.SessionAsync(key, cts.Token);
            if (cts.IsCancellationRequested || key != Key) return;
            Info = info;
            // Default to the top two finishers' fastest laps; a session-fastest pick stays.
            var order = info.Drivers.OrderBy(d => d.Position ?? 99).ToList();
            if (!Reference.IsSessionFastest) Reference = LapChoice.ForDriver(order.FirstOrDefault()?.Code);
            if (OtherYear is null && !Other.IsSessionFastest)
                Other = LapChoice.ForDriver(order.Skip(1).FirstOrDefault()?.Code);
        }, cts.Token);
        LoadOtherSession();
    }

    /// Finds this event in `OtherYear`'s calendar and loads that session for the compared lap.
    private void LoadOtherSession()
    {
        _otherCts?.Cancel();
        OtherKey = null;
        OtherInfo = null;
        Comparison = null;
        if (OtherYear is not { } otherYear || Event is not { } ev || SessionName is not { } sessionName)
        {
            _otherTask = null;
            return;
        }
        var cts = _otherCts = new CancellationTokenSource();
        var sessionTask = _sessionTask;
        _otherTask = Run($"Finding {ev.Name} in {otherYear}", async () =>
        {
            if (sessionTask is not null) await sessionTask;  // default to the reference driver
            var events = await Service.ScheduleAsync(otherYear, cts.Token);
            // Same circuit; names change (sponsors, "Mexican" → "Mexico City").
            var match = events.FirstOrDefault(e => e.Location == ev.Location)
                ?? events.FirstOrDefault(e => e.Name == ev.Name)
                ?? throw new InvalidOperationException($"No {ev.Location} round in {otherYear}.");
            if (!match.Sessions.Contains(sessionName))
                throw new InvalidOperationException($"{match.Name} {otherYear} has no {sessionName} session.");
            var key = new SessionKey(otherYear, match.Name, sessionName);
            if (cts.IsCancellationRequested || otherYear != OtherYear) return;
            OtherKey = key;
            var info = await Service.SessionAsync(key, cts.Token);
            if (cts.IsCancellationRequested || key != OtherKey) return;
            OtherInfo = info;
            // Default to the reference pick: the point is usually one driver (or the session's
            // fastest lap) across years.
            if (Reference.IsSessionFastest)
            {
                Other = new LapChoice(LapChoice.Pick.SessionFastest.Instance);
                return;
            }
            if (Other.IsSessionFastest) return;
            var codes = info.Drivers.Select(d => d.Code).ToHashSet();
            var driver = Reference.DriverCode is { } c && codes.Contains(c) ? c
                : info.Drivers.OrderBy(d => d.Position ?? 99).FirstOrDefault()?.Code;
            Other = LapChoice.ForDriver(driver);
        }, cts.Token);
    }

    public void Compare()
    {
        if (Key is not { } key || OtherSessionKey is not { } otherKey
            || Reference.RefIn(Info) is not { } r || Other.RefIn(OtherSessionInfo) is not { } o)
            return;
        _analysisCts?.Cancel();
        var cts = _analysisCts = new CancellationTokenSource();
        _ = Run($"Comparing {r.Driver} and {o.Driver}", async () =>
        {
            var (result, traces) = await Service.CompareAsync((key, r), (otherKey, o), cts.Token);
            var plot = await Task.Run(() => PlotTraces.Prepare(traces, result.Grid), cts.Token);
            if (cts.IsCancellationRequested) return;
            Comparison = new Comparison(result, plot);
        }, cts.Token);
        Rate();
    }

    public void Rate()
    {
        var choice = RatedSide == Side.Reference ? Reference : Other;
        var (key, info) = RatedSide == Side.Reference ? (Key, Info) : (OtherSessionKey, OtherSessionInfo);
        if (key is null || choice.RefIn(info) is not { } lap) return;
        _ratingCts?.Cancel();
        var cts = _ratingCts = new CancellationTokenSource();
        _ = Run($"Rating {lap.Driver} against the {key.Year} field", async () =>
        {
            var rating = await Service.RateAsync(key, lap, cts.Token);
            PerfectPlot? plot = null;
            // The rating stands even if the perfect-lap trace file cannot be read.
            if (rating.Perfect is { } perfect)
            {
                try
                {
                    if (await Service.PerfectTracesAsync(perfect) is { } traces)
                        plot = await Task.Run(() => PerfectPlot.Prepare(traces), cts.Token);
                }
                catch (Exception e) when (e is IOException or SoAException or UnauthorizedAccessException) { }
            }
            if (cts.IsCancellationRequested) return;
            Rating = rating;
            PerfectPlot = plot;
        }, cts.Token);
    }

    public IReadOnlyList<LapRow> LapsOf(string? driver, SessionInfo? info) =>
        driver is null || info is null ? [] : info.LapsOf(driver).Where(l => l.TimeS is not null).ToList();

    private async Task Run(string label, Func<Task> work, CancellationToken ct = default)
    {
        Busy = label;
        Progress = null;
        try
        {
            await work();
            if (!ct.IsCancellationRequested) Error = null;
        }
        catch (OperationCanceledException) { }
        catch (Exception e)
        {
            if (!ct.IsCancellationRequested) Error = e.Message;
        }
        finally
        {
            if (Busy == label)
            {
                Busy = null;
                Progress = null;
            }
        }
    }

    private bool Set<T>(ref T field, T value, [CallerMemberName] string? name = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return false;
        field = value;
        OnPropertyChanged(name);
        if (name is nameof(Reference) or nameof(Other) or nameof(Info) or nameof(OtherInfo)
            or nameof(OtherKey) or nameof(SessionName) or nameof(EventRound) or nameof(OtherYear))
            OnPropertyChanged(nameof(CanCompare));
        return true;
    }

    private void OnPropertyChanged(string? name) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}
