using System.ComponentModel;
using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace F1Lap.Core;

/// How to launch the Python sidecar (`python -m f1lap.server`).
public sealed record SidecarConfig(
    string Executable, IReadOnlyList<string> Arguments, string? WorkingDirectory = null,
    IReadOnlyDictionary<string, string>? Environment = null)
{
    /// The `f1lap.server` of a repository checkout's virtualenv.
    public static SidecarConfig Repository(string repo, string? python = null) => new(
        python ?? VenvPython(repo), ["-m", "f1lap.server"], repo,
        new Dictionary<string, string> { ["PYTHONUNBUFFERED"] = "1", ["PYTHONIOENCODING"] = "utf-8" });

    /// `.venv\Scripts\python.exe` on Windows, `.venv/bin/python` elsewhere.
    public static string VenvPython(string repo) => OperatingSystem.IsWindows()
        ? Path.Combine(repo, ".venv", "Scripts", "python.exe")
        : Path.Combine(repo, ".venv", "bin", "python");

    /// The interpreter `bundle-python.ps1` embeds at `python\python.exe` next to F1Lap.exe, or
    /// null if `appDir` holds none (a development build).
    public static SidecarConfig? Bundled(string appDir, string localAppData)
    {
        var python = Path.Combine(appDir, "python", OperatingSystem.IsWindows() ? "python.exe" : "bin/python3");
        if (!File.Exists(python)) return null;
        // The install folder may be read-only: cache, data and the working directory live in
        // %LOCALAPPDATA%\f1lap (the sidecar's own default cache root), with no bytecode writes.
        var root = Path.Combine(localAppData, "f1lap");
        Directory.CreateDirectory(root);
        return new(python, ["-m", "f1lap.server"], root, new Dictionary<string, string>
        {
            ["PYTHONUNBUFFERED"] = "1",
            ["PYTHONIOENCODING"] = "utf-8",
            ["PYTHONDONTWRITEBYTECODE"] = "1",
            ["PYTHONNOUSERSITE"] = "1",
            ["F1LAP_CACHE_DIR"] = Path.Combine(root, "Cache"),
            ["F1LAP_DATA_DIR"] = Path.Combine(root, "Data"),
        });
    }
}

public class SidecarException(string message) : Exception(message);

/// JSON-RPC error returned by the sidecar.
public sealed class SidecarRpcException(int code, string message) : SidecarException(message)
{
    public int Code { get; } = code;
    /// Analysis-level failure (unknown driver, missing data), as opposed to a protocol fault.
    public bool IsAnalysisError => Code == -32000;
}

/// The sidecar process could not be started.
public sealed class SidecarLaunchException(string why)
    : SidecarException($"Could not start the analysis engine: {why}");

/// The sidecar exited while requests were in flight; `Log` holds its last stderr lines.
public sealed class SidecarExitedException(int status, string log) : SidecarException(
    $"The analysis engine stopped (status {status}).{(log.Length == 0 ? "" : "\n" + log)}")
{
    public int Status { get; } = status;
    public string Log { get; } = log;
}

/// A reply could not be decoded into the expected type.
public sealed class SidecarBadReplyException(string why)
    : SidecarException($"Unexpected reply from the analysis engine: {why}");

/// A `progress` notification: what the sidecar is doing during a long request.
public sealed record SidecarProgress(string Message, int? Done = null, int? Total = null);

/// JSON-RPC 2.0 client for the sidecar: newline-delimited JSON over the child's stdin/stdout.
///
/// Requests run concurrently and are matched to replies by id. If the sidecar exits, in-flight
/// requests fail with `SidecarExitedException` and the next call starts a fresh process. Pipes are
/// read by async loops on the thread pool, so no caller ever blocks on the child.
public sealed class SidecarClient(SidecarConfig config) : IAsyncDisposable
{
    private readonly object _gate = new();
    private readonly SemaphoreSlim _writeLock = new(1, 1);
    /// In-flight requests with the process generation they were sent to, so a process going away
    /// fails only its own requests, never ones already sent to its replacement.
    private readonly Dictionary<int, (int Gen, TaskCompletionSource<JsonElement> Tcs)> _pending = [];
    private readonly Queue<string> _stderrTail = new();
    private Process? _process;
    private StreamWriter? _input;
    private int _generation;
    private int _nextId = 1;
    private bool _closed;

    /// Progress notifications from the sidecar; raised on a thread-pool thread.
    public event Action<SidecarProgress>? Progress;

    /// Calls `method` and decodes its `result` as `T`.
    public async Task<T> CallAsync<T>(string method, object? parameters = null,
                                      CancellationToken ct = default)
    {
        var reply = await SendAsync(method, parameters ?? new Dictionary<string, object?>(), ct);
        try
        {
            return reply.GetProperty("result").Deserialize<T>(Json.Options)
                ?? throw new JsonException("null result");
        }
        catch (Exception e) when (e is JsonException or KeyNotFoundException or InvalidOperationException)
        {
            throw new SidecarBadReplyException($"{method}: {e.Message}");
        }
    }

    /// Stops the sidecar for good. Closing stdin lets it finish cleanly; it is killed if still
    /// running after two seconds. Later calls fail instead of starting a new process.
    public async Task ShutdownAsync()
    {
        var process = Detach();
        if (process is null) return;
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(2));
        // Not on the caller's context: a UI thread may be the one waiting for this.
        try { await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false); }
        catch (OperationCanceledException) { TryKill(process); }
    }

    /// Stops the sidecar at once without waiting (app exit): closes stdin and kills the process
    /// tree, so a sidecar busy downloading a session never outlives the app.
    public void Terminate()
    {
        if (Detach() is { } process) TryKill(process);
    }

    public async ValueTask DisposeAsync() => await ShutdownAsync().ConfigureAwait(false);

    /// Marks the client closed, fails what is in flight and hands back the process to stop.
    private Process? Detach()
    {
        Process? process;
        StreamWriter? input;
        int gen;
        lock (_gate)
        {
            _closed = true;
            (process, input, gen) = (_process, _input, _generation);
            _process = null;
            _input = null;
            _generation++;  // the old process's stdout closing is no longer news
        }
        try { input?.Close(); } catch (IOException) { }
        FailPending(gen, new SidecarExitedException(0, ""));
        return process;
    }

    // MARK: transport

    private async Task<JsonElement> SendAsync(string method, object parameters, CancellationToken ct)
    {
        int id;
        StreamWriter input;
        var tcs = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        lock (_gate)
        {
            if (_closed) throw new SidecarExitedException(0, "");
            input = StartIfNeeded();
            id = _nextId++;
            _pending[id] = (_generation, tcs);
        }
        var line = JsonSerializer.Serialize(
            new Dictionary<string, object?>
            {
                ["jsonrpc"] = "2.0", ["id"] = id, ["method"] = method, ["params"] = parameters,
            }, Json.Options);
        try
        {
            await _writeLock.WaitAsync(ct);
            try
            {
                await input.WriteAsync(line + "\n");
                await input.FlushAsync(ct);
            }
            finally { _writeLock.Release(); }
        }
        catch (Exception e) when (e is IOException or ObjectDisposedException)
        {
            lock (_gate) _pending.Remove(id);
            throw new SidecarExitedException(-1, StderrTail());
        }
        catch (OperationCanceledException)
        {
            lock (_gate) _pending.Remove(id);
            throw;
        }
        await using (ct.Register(() =>
        {
            lock (_gate) _pending.Remove(id);
            tcs.TrySetCanceled(ct);
        }))
        {
            return await tcs.Task;
        }
    }

    /// Starts the process unless one is running. Call with `_gate` held.
    private StreamWriter StartIfNeeded()
    {
        if (_process is { HasExited: false } && _input is not null) return _input;
        if (_process is { HasExited: true } dead)
        {
            // Its stdout loop may not have reported yet; requests sent to it will never be answered.
            var error = new SidecarExitedException(dead.ExitCode, string.Join("\n", _stderrTail.TakeLast(5)));
            foreach (var (id, (sentTo, tcs)) in _pending.ToList())
            {
                if (sentTo != _generation) continue;
                _pending.Remove(id);
                tcs.TrySetException(error);  // continuations run asynchronously: safe under the lock
            }
        }
        var info = new ProcessStartInfo(config.Executable)
        {
            UseShellExecute = false,
            CreateNoWindow = true,  // no console window flashing up on Windows
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardInputEncoding = new UTF8Encoding(false),
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
            WorkingDirectory = config.WorkingDirectory ?? "",
        };
        foreach (var a in config.Arguments) info.ArgumentList.Add(a);
        foreach (var (k, v) in config.Environment ?? new Dictionary<string, string>())
            info.Environment[k] = v;
        Process process;
        try
        {
            process = Process.Start(info) ?? throw new SidecarLaunchException(config.Executable);
        }
        catch (Exception e) when (e is Win32Exception or FileNotFoundException or DirectoryNotFoundException
                                       or InvalidOperationException)
        {
            throw new SidecarLaunchException($"{config.Executable}: {e.Message}");
        }
        var gen = ++_generation;
        _process = process;
        _input = process.StandardInput;
        _input.AutoFlush = false;
        _stderrTail.Clear();

        var stdout = process.StandardOutput;
        _ = Task.Run(async () =>
        {
            try
            {
                while (await stdout.ReadLineAsync() is { } line)
                {
                    if (line.Length == 0) continue;
                    // Keep draining stdout whatever one line does: a stalled reader would block
                    // the sidecar's writes and hang every call.
                    try { Deliver(line); }
                    catch (Exception e) { Debug.WriteLine($"[sidecar] dropped reply: {e.Message}"); }
                }
            }
            catch (Exception e) when (e is IOException or ObjectDisposedException) { }
            await StdoutClosed(gen, process);
        });
        var stderr = process.StandardError;
        _ = Task.Run(async () =>
        {
            try
            {
                while (await stderr.ReadLineAsync() is { } line)
                    lock (_gate)
                    {
                        Debug.WriteLine($"[sidecar] {line}");
                        _stderrTail.Enqueue(line);
                        while (_stderrTail.Count > 20) _stderrTail.Dequeue();
                    }
            }
            catch (Exception e) when (e is IOException or ObjectDisposedException) { }
        });
        return _input;
    }

    private void Deliver(string line)
    {
        JsonElement root;
        try
        {
            using var doc = JsonDocument.Parse(line);
            root = doc.RootElement.Clone();
        }
        catch (JsonException)
        {
            Debug.WriteLine($"[sidecar] unparseable reply: {line[..Math.Min(line.Length, 200)]}");
            return;
        }
        if (root.ValueKind != JsonValueKind.Object) return;
        bool hasId = root.TryGetProperty("id", out var idEl) && idEl.ValueKind == JsonValueKind.Number
                     && idEl.TryGetInt32(out _);
        if (!hasId)
        {
            if (root.TryGetProperty("method", out var m) && m.ValueKind == JsonValueKind.String
                && m.GetString() == "progress" && root.TryGetProperty("params", out var p))
            {
                try
                {
                    if (p.Deserialize<SidecarProgress>(Json.Options) is { } note) Progress?.Invoke(note);
                }
                catch (JsonException) { }
            }
            return;
        }
        TaskCompletionSource<JsonElement> tcs;
        lock (_gate)
        {
            if (!_pending.Remove(idEl.GetInt32(), out var entry)) return;
            tcs = entry.Tcs;
        }
        if (root.TryGetProperty("error", out var error) && error.ValueKind == JsonValueKind.Object)
        {
            int code = error.TryGetProperty("code", out var c) && c.TryGetInt32(out var ci) ? ci : 0;
            string message = error.TryGetProperty("message", out var msg) && msg.ValueKind == JsonValueKind.String
                ? msg.GetString() ?? "" : "";
            tcs.TrySetException(new SidecarRpcException(code, message));
        }
        else
        {
            tcs.TrySetResult(root);
        }
    }

    private async Task StdoutClosed(int gen, Process process)
    {
        // Give the exit status a moment to land; stdout can close just before the process exits.
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(1));
        try { await process.WaitForExitAsync(timeout.Token); } catch (OperationCanceledException) { }
        int status = process.HasExited ? process.ExitCode : -1;
        lock (_gate)
        {
            if (gen == _generation)  // not already replaced or shut down
            {
                _process = null;
                _input = null;
            }
        }
        FailPending(gen, new SidecarExitedException(status, StderrTail()));
    }

    private string StderrTail()
    {
        lock (_gate) return string.Join("\n", _stderrTail.TakeLast(5));
    }

    /// Fails the requests sent to process generation `gen`.
    private void FailPending(int gen, SidecarException error)
    {
        List<TaskCompletionSource<JsonElement>> waiting = [];
        lock (_gate)
        {
            foreach (var (id, entry) in _pending.ToList())
            {
                if (entry.Gen != gen) continue;
                _pending.Remove(id);
                waiting.Add(entry.Tcs);
            }
        }
        foreach (var t in waiting) t.TrySetException(error);
    }

    private static void TryKill(Process p)
    {
        try { p.Kill(entireProcessTree: true); }
        catch (Exception e) when (e is InvalidOperationException or Win32Exception) { }
    }
}
