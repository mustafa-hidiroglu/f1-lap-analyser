using System.Buffers.Binary;
using System.Text.Json;
using F1Lap.Core;
using Xunit;

namespace F1Lap.Core.Tests;

// Port of app/Tests/F1LapKitTests/F1LapKitTests.swift (decoding, SoA, transport, Fmt).

public class DecodingTests
{
    private static T Fixture<T>(string name)
    {
        var path = Path.Combine(AppContext.BaseDirectory, "Fixtures", name + ".json");
        return JsonSerializer.Deserialize<T>(File.ReadAllText(path), Json.Options)!;
    }

    [Fact]
    public void Schedule()
    {
        var events = Fixture<List<Event>>("schedule");
        var monza = events.First(e => e.Location == "Monza");
        Assert.Contains("Qualifying", monza.Sessions);
    }

    [Fact]
    public void Session()
    {
        var info = Fixture<SessionInfo>("session");
        Assert.Equal(20, info.Drivers.Count);
        Assert.Contains(info.LapsOf("LEC"), l => l.Valid && l.PersonalBest);
    }

    [Fact]
    public void SessionFastestLap()
    {
        var info = Fixture<SessionInfo>("session");
        var best = info.FastestLap();
        Assert.NotNull(best);
        Assert.True(best.Driver == "NOR" && best.Lap == 11 && best.TimeS == 79.327);

        // Only valid laps count, even when an invalid one is faster.
        static LapRow Row(string driver, double? time, bool valid) =>
            new(driver, 1, time, null, false, valid);
        static SessionInfo Sess(params LapRow[] laps) => new(2024, "X", "R", [], laps);

        var mixed = Sess(Row("AAA", 80, false), Row("BBB", 81, true), Row("CCC", null, true));
        Assert.Equal("BBB", mixed.FastestLap()?.Driver);
        // No valid lap: nothing stands in.
        Assert.Null(Sess(Row("AAA", 82, false), Row("BBB", 81, false), Row("CCC", null, false)).FastestLap());
        // Equal times: the first in array order wins.
        Assert.Equal("AAA", Sess(Row("AAA", 81, true), Row("BBB", 81, true)).FastestLap()?.Driver);
        Assert.Null(Sess().FastestLap());
    }

    [Fact]
    public void Compare()
    {
        var c = Fixture<CompareResult>("compare");
        Assert.True(c.Reference.Driver == "LEC" && c.Other.Driver == "SAI");
        Assert.Equal(2, c.Metrics.Count);
        Assert.NotEmpty(c.Corners);
        Assert.All(c.Corners, k => Assert.True(k.PhaseDeltaS.ContainsKey("braking")));
        var track = c.Circuit.Track;
        Assert.NotNull(track);
        Assert.True(track.X.Count == track.Y.Count && track.X.Count > 100);
        Assert.All(c.Traces.Columns, col => Assert.Equal(c.Grid.Samples, col.Count));
    }

    [Fact]
    public void Rate()
    {
        var r = Fixture<Rating>("rate");
        Assert.Equal("LEC", r.Driver);
        Assert.InRange(r.Score, 0, 100);
        Assert.True(r.TheoreticalBestS <= r.LapTimeS);
        var p = r.Perfect;
        Assert.NotNull(p);
        Assert.Null(p.Error);
        Assert.True(p.SimLapTimeS!.Value < r.LapTimeS);
        Assert.StartsWith("LEC L20 was", p.Summary?.FirstOrDefault());
        Assert.True(p.Corners is { Count: > 0 } && p.Traces is not null);
    }

    [Fact]
    public void LapRefWireForm()
    {
        Assert.Equal("fastest", new LapRef("LEC").LapParam);
        Assert.Equal(12, new LapRef("LEC", 12).LapParam);
        Assert.Equal("\"fastest\"", JsonSerializer.Serialize(new LapRef("LEC").LapParam));
        Assert.Equal("12", JsonSerializer.Serialize(new LapRef("LEC", 12).LapParam));
    }
}

public class SoATests
{
    /// f64 column at 0, i16 column at an 8-aligned offset after padding, as `write_soa` lays out.
    private static string WriteFile(byte[] bytes)
    {
        var path = Path.Combine(Path.GetTempPath(), Guid.NewGuid() + ".f1soa");
        File.WriteAllBytes(path, bytes);
        return path;
    }

    [Fact]
    public void ReadsF64AndI16()
    {
        var bytes = new List<byte>();
        foreach (var v in new[] { 1.5, -2.25, 300.0 })
        {
            var b = new byte[8];
            BinaryPrimitives.WriteDoubleLittleEndian(b, v);
            bytes.AddRange(b);
        }
        foreach (var g in new short[] { 3, -1, 8 })
        {
            var b = new byte[2];
            BinaryPrimitives.WriteInt16LittleEndian(b, g);
            bytes.AddRange(b);
        }
        var path = WriteFile([.. bytes]);
        try
        {
            var t = Traces.Read(path,
            [
                new SoAColumnLayout("speed", "f64", 0, 3),
                new SoAColumnLayout("gear", "i16", 24, 3),
            ]);
            Assert.Equal([1.5, -2.25, 300.0], t["speed"]);
            Assert.Equal([3.0, -1.0, 8.0], t["gear"]);
            Assert.Empty(t["missing"]);
        }
        finally { File.Delete(path); }
    }

    [Fact]
    public void RejectsBadLayout()
    {
        var path = WriteFile(new byte[16]);
        try
        {
            var e1 = Assert.Throws<SoAException>(() =>
                Traces.Read(path, [new SoAColumnLayout("x", "f64", 8, 2)]));
            Assert.Equal(SoAException.OutOfBounds("x").Message, e1.Message);
            var e2 = Assert.Throws<SoAException>(() =>
                Traces.Read(path, [new SoAColumnLayout("x", "f64", 0, long.MaxValue)]));
            Assert.Equal(SoAException.OutOfBounds("x").Message, e2.Message);
            var e3 = Assert.Throws<SoAException>(() =>
                Traces.Read(path, [new SoAColumnLayout("x", "f32", 0, 1)]));
            Assert.Equal(SoAException.UnsupportedDType("f32").Message, e3.Message);
        }
        finally { File.Delete(path); }
    }
}

public class TransportTests
{
    private static SidecarClient Shell(string script) =>
        new(new SidecarConfig("/bin/sh", ["-c", script]));

    [Fact]
    public async Task MapsRpcErrors()
    {
        if (OperatingSystem.IsWindows()) return;
        await using var client = Shell(
            """read l; echo '{"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"no lap"}}'; read l""");
        var e = await Assert.ThrowsAsync<SidecarRpcException>(() => client.CallAsync<int>("rate"));
        Assert.Equal(-32000, e.Code);
        Assert.Equal("no lap", e.Message);
        Assert.True(e.IsAnalysisError);
    }

    [Fact]
    public async Task FailsInFlightRequestsWhenSidecarExits()
    {
        if (OperatingSystem.IsWindows()) return;
        await using var client = Shell("read l; echo 'boom' >&2; exit 3");
        var e = await Assert.ThrowsAsync<SidecarExitedException>(() => client.CallAsync<int>("compare"));
        Assert.True(e.Log.Contains("boom") || e.Log.Length == 0);  // stderr may race the stdout close
    }

    [Fact]
    public async Task RestartsAfterExit()
    {
        if (OperatingSystem.IsWindows()) return;
        // Each process answers one request with result 7 and exits; the next call must relaunch.
        await using var client = Shell(
            """read l; echo '{"jsonrpc":"2.0","id":'$(echo "$l" | sed 's/.*"id":\([0-9]*\).*/\1/')',"result":7}'""");
        for (int round = 0; round < 2; round++)
        {
            int? value = null;
            for (int attempt = 0; attempt < 20 && value is null; attempt++)  // the exit may race the next send: retry
            {
                try { value = await client.CallAsync<int>("ping"); }
                catch (SidecarException) { }
            }
            Assert.Equal(7, value);
        }
    }

    [Fact]
    public async Task DeliversProgressNotifications()
    {
        if (OperatingSystem.IsWindows()) return;
        await using var client = Shell(
            """read l; echo '{"jsonrpc":"2.0","method":"progress","params":{"message":"Reading laps","done":25,"total":900}}'; echo '{"jsonrpc":"2.0","id":1,"result":7}'; read l""");
        var updates = new List<SidecarProgress>();
        client.Progress += p => { lock (updates) updates.Add(p); };
        var value = await client.CallAsync<int>("rate");
        Assert.Equal(7, value);
        lock (updates)
            Assert.Equal([new SidecarProgress("Reading laps", 25, 900)], updates);
    }

    [Fact]
    public async Task TerminateFailsInFlightAndRefusesNewCalls()
    {
        if (OperatingSystem.IsWindows()) return;
        var client = Shell("read l; sleep 30");  // never answers
        var inFlight = client.CallAsync<int>("compare");
        await Task.Delay(200);
        client.Terminate();  // app exit: no waiting
        await Assert.ThrowsAsync<SidecarExitedException>(() => inFlight);
        // A closed client must not relaunch a sidecar nobody will stop.
        await Assert.ThrowsAsync<SidecarExitedException>(() => client.CallAsync<int>("ping"));
    }

    [Fact]
    public async Task MalformedReplyDoesNotStallTheReader()
    {
        if (OperatingSystem.IsWindows()) return;
        await using var client = Shell(
            """read l; echo '{"jsonrpc":"2.0","id":"x","method":5}'; echo '{"jsonrpc":"2.0","id":1,"result":7}'; read l""");
        Assert.Equal(7, await client.CallAsync<int>("ping"));
    }

    [Fact]
    public async Task LaunchFailure()
    {
        await using var client = new SidecarClient(new SidecarConfig("/nonexistent/python", []));
        await Assert.ThrowsAsync<SidecarLaunchException>(() => client.CallAsync<int>("ping"));
    }
}

public class FmtTests
{
    [Fact]
    public void LapTime()
    {
        Assert.Equal("1:19.461", Fmt.LapTime(79.461));
        Assert.Equal("59.500", Fmt.LapTime(59.5));
        Assert.Equal("—", Fmt.LapTime(null));
    }

    [Fact]
    public void Delta()
    {
        Assert.Equal("+0.006", Fmt.Delta(0.006));
        Assert.Equal("-0.180", Fmt.Delta(-0.18));
    }

    [Fact]
    public void Speed() => Assert.Equal("288", Fmt.Speed(287.6));
}

public class BundledConfigTests
{
    private static string Scratch() => Directory.CreateTempSubdirectory().FullName;

    [Fact]
    public void NullWithoutEmbeddedPython() => Assert.Null(SidecarConfig.Bundled(Scratch(), Scratch()));

    [Fact]
    public void RunsEmbeddedPythonWithStateInLocalAppData()
    {
        var app = Scratch();
        var local = Scratch();
        var python = Path.Combine(app, "python", OperatingSystem.IsWindows() ? "python.exe" : "bin/python3");
        Directory.CreateDirectory(Path.GetDirectoryName(python)!);
        File.WriteAllText(python, "");

        var config = SidecarConfig.Bundled(app, local);
        var root = Path.Combine(local, "f1lap");
        Assert.NotNull(config);
        Assert.Equal(python, config.Executable);
        Assert.Equal(["-m", "f1lap.server"], config.Arguments);
        Assert.Equal(root, config.WorkingDirectory);
        Assert.True(Directory.Exists(root));
        Assert.Equal("1", config.Environment!["PYTHONDONTWRITEBYTECODE"]);
        Assert.Equal(Path.Combine(root, "Cache"), config.Environment["F1LAP_CACHE_DIR"]);
        Assert.Equal(Path.Combine(root, "Data"), config.Environment["F1LAP_DATA_DIR"]);
    }
}
