namespace F1Lap.Core;

/// Typed API over the sidecar's JSON-RPC methods (mirrors F1LapService.swift).
public sealed class F1LapService(SidecarClient client)
{
    public SidecarClient Client { get; } = client;

    public Task<Ping> PingAsync(CancellationToken ct = default) =>
        Client.CallAsync<Ping>("ping", null, ct);

    public Task<List<Event>> ScheduleAsync(int year, CancellationToken ct = default) =>
        Client.CallAsync<List<Event>>("schedule", new Dictionary<string, object?> { ["year"] = year }, ct);

    public Task<SessionInfo> SessionAsync(SessionKey key, CancellationToken ct = default) =>
        Client.CallAsync<SessionInfo>("session", KeyParams(key), ct);

    /// Compares laps from two sessions (e.g. one driver at one track in different years) and
    /// loads the trace file the sidecar wrote. The reference session supplies the circuit and
    /// corner segments.
    public async Task<(CompareResult Result, Traces Traces)> CompareAsync(
        (SessionKey Key, LapRef Lap) reference, (SessionKey Key, LapRef Lap) other,
        CancellationToken ct = default)
    {
        var p = KeyParams(reference.Key);
        p["reference"] = Side(reference.Key, reference.Lap);
        p["other"] = Side(other.Key, other.Lap);
        var result = await Client.CallAsync<CompareResult>("compare", p, ct);
        var traces = await LoadTracesAsync(result.Traces);
        return (result, traces);
    }

    public Task<Rating> RateAsync(SessionKey key, LapRef lap, CancellationToken ct = default)
    {
        var p = KeyParams(key);
        p["driver"] = lap.Driver;
        p["lap"] = lap.LapParam;
        return Client.CallAsync<Rating>("rate", p, ct);
    }

    /// The rated lap and the perfect lap on one grid (distance, delta, sim/lap speed and brake).
    public async Task<Traces?> PerfectTracesAsync(PerfectLap perfect) =>
        perfect.Traces is { } file ? await LoadTracesAsync(file) : null;

    /// Reads and decodes a trace file off the caller's thread.
    public static Task<Traces> LoadTracesAsync(TraceFile file) =>
        Task.Run(() => Traces.Read(file.Path, file.Columns));

    private static Dictionary<string, object?> KeyParams(SessionKey key) => new()
    {
        ["year"] = key.Year, ["event"] = key.Event, ["session"] = key.Session,
    };

    private static Dictionary<string, object?> Side(SessionKey key, LapRef lap)
    {
        var p = KeyParams(key);
        p["driver"] = lap.Driver;
        p["lap"] = lap.LapParam;
        return p;
    }
}
