namespace F1Lap.Core;

/// One lap picked in the UI; `Lap == null` is the driver's fastest (mirrors AppModel.swift).
public sealed record LapChoice(LapChoice.Pick? Choice = null, int? Lap = null)
{
    /// A driver, or whoever set the session's fastest lap (resolved against the loaded session,
    /// so it follows session changes; `Lap` is unused then).
    public abstract record Pick
    {
        public sealed record Driver(string Code) : Pick;
        public sealed record SessionFastest : Pick
        {
            public static readonly SessionFastest Instance = new();
        }
    }

    public static LapChoice ForDriver(string? code) => new(code is null ? null : new Pick.Driver(code));

    /// `fastest` (any case) picks the session's fastest lap; anything else is a driver code.
    public static LapChoice FromSpec(string spec) =>
        spec.Equals("fastest", StringComparison.OrdinalIgnoreCase)
            ? new(Pick.SessionFastest.Instance)
            : new(new Pick.Driver(spec));

    public bool IsSessionFastest => Choice is Pick.SessionFastest;

    public string? DriverCode => Choice is Pick.Driver d ? d.Code : null;

    public LapRef? RefIn(SessionInfo? info) => Choice switch
    {
        Pick.Driver d => new LapRef(d.Code, Lap),
        Pick.SessionFastest => info?.FastestLap() is { } best ? new LapRef(best.Driver, best.Lap) : null,
        _ => null,
    };
}
