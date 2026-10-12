import Foundation
import os

/// How to launch the Python sidecar (`python -m f1lap.server`).
public struct SidecarConfig: Sendable {
    public var executable: URL
    public var arguments: [String]
    public var workingDirectory: URL?
    public var environment: [String: String]

    public init(
        executable: URL, arguments: [String], workingDirectory: URL? = nil,
        environment: [String: String] = [:]
    ) {
        self.executable = executable
        self.arguments = arguments
        self.workingDirectory = workingDirectory
        self.environment = environment
    }

    /// The `f1lap-server` of a repository checkout's virtualenv.
    public static func repository(_ repo: URL, python: URL? = nil) -> SidecarConfig {
        SidecarConfig(
            executable: python ?? repo.appending(path: ".venv/bin/python"),
            arguments: ["-m", "f1lap.server"],
            workingDirectory: repo,
            environment: ["PYTHONUNBUFFERED": "1"]
        )
    }

    /// The interpreter `bundle.sh` embeds at `Contents/Resources/python`, or nil if `resources`
    /// holds none (a bare `swift run` build).
    public static func bundled(resources: URL, home: URL = .homeDirectory) -> SidecarConfig? {
        let python = resources.appending(path: "python/bin/python3")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { return nil }
        // The bundle is read-only and sealed by its signature: cache, data and the working
        // directory live in the user's Library, and no bytecode is written next to the sources.
        let support = home.appending(path: "Library/Application Support/F1Lap")
        try? FileManager.default.createDirectory(at: support, withIntermediateDirectories: true)
        return SidecarConfig(
            executable: python,
            arguments: ["-m", "f1lap.server"],
            workingDirectory: support,
            environment: [
                "PYTHONUNBUFFERED": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
                "F1LAP_CACHE_DIR": home.appending(path: "Library/Caches/F1Lap").path,
                "F1LAP_DATA_DIR": support.appending(path: "data").path,
            ]
        )
    }
}

public enum SidecarError: Error, Equatable, LocalizedError {
    /// JSON-RPC error returned by the sidecar (code, message).
    case rpc(code: Int, message: String)
    /// The sidecar process could not be started.
    case launchFailed(String)
    /// The sidecar exited while requests were in flight; `log` holds its last stderr lines.
    case exited(status: Int32, log: String)
    /// A reply could not be decoded into the expected type.
    case badReply(String)

    public var errorDescription: String? {
        switch self {
        case let .rpc(_, message): message
        case let .launchFailed(why): "Could not start the analysis engine: \(why)"
        case let .exited(status, log):
            "The analysis engine stopped (status \(status)).\(log.isEmpty ? "" : "\n\(log)")"
        case let .badReply(why): "Unexpected reply from the analysis engine: \(why)"
        }
    }

    /// Analysis-level failure (unknown driver, missing data), as opposed to a protocol fault.
    public var isAnalysisError: Bool {
        if case let .rpc(code, _) = self { return code == -32000 }
        return false
    }
}

/// A `progress` notification: what the sidecar is doing during a long request.
public struct SidecarProgress: Decodable, Sendable, Equatable {
    public let message: String
    public let done: Int?
    public let total: Int?

    public init(message: String, done: Int? = nil, total: Int? = nil) {
        self.message = message
        self.done = done
        self.total = total
    }
}

/// JSON-RPC 2.0 client for the sidecar: newline-delimited JSON over the child's stdin/stdout.
///
/// Requests run concurrently and are matched to replies by id. If the sidecar exits, in-flight
/// requests fail with `SidecarError.exited` and the next call starts a fresh process.
public actor SidecarClient {
    private let config: SidecarConfig
    private let log = Logger(subsystem: "f1lap", category: "sidecar")
    private var process: Process?
    private var input: FileHandle?
    private var generation = 0
    private var nextID = 1
    private var pending: [Int: CheckedContinuation<Data, any Error>] = [:]
    private var stderrTail: [String] = []
    private let progressSink: AsyncStream<SidecarProgress>.Continuation

    /// Progress notifications from the sidecar, newest only (for a single status line).
    public nonisolated let progress: AsyncStream<SidecarProgress>

    public init(config: SidecarConfig) {
        self.config = config
        (progress, progressSink) = AsyncStream.makeStream(bufferingPolicy: .bufferingNewest(1))
    }

    /// Calls `method` and decodes its `result` as `R`.
    public func call<P: Encodable & Sendable, R: Decodable & Sendable>(
        _ method: String, _ params: P, as type: R.Type = R.self
    ) async throws -> R {
        let raw = try await send(method, params)
        do {
            return try Self.decoder.decode(ResultEnvelope<R>.self, from: raw).result
        } catch {
            throw SidecarError.badReply("\(method): \(error)")
        }
    }

    /// Stops the sidecar. Closing stdin lets it finish cleanly; it is terminated if still running.
    public func shutdown() {
        guard let process else { return }
        try? input?.close()
        if process.isRunning { process.terminate() }
        self.process = nil
        input = nil
        failPending(with: SidecarError.exited(status: 0, log: ""))
    }

    // MARK: - Transport

    private func send<P: Encodable & Sendable>(_ method: String, _ params: P) async throws -> Data {
        try startIfNeeded()
        let id = nextID
        nextID += 1
        var line = try Self.encoder.encode(Request(id: id, method: method, params: params))
        line.append(0x0A)
        let handle = input
        return try await withCheckedThrowingContinuation { continuation in
            pending[id] = continuation
            do {
                guard let handle else { throw SidecarError.launchFailed("no stdin") }
                try handle.write(contentsOf: line)
            } catch {
                pending.removeValue(forKey: id)?.resume(throwing: error)
            }
        }
    }

    private func startIfNeeded() throws {
        if let process, process.isRunning { return }
        let process = Process()
        process.executableURL = config.executable
        process.arguments = config.arguments
        process.currentDirectoryURL = config.workingDirectory
        process.environment = ProcessInfo.processInfo.environment.merging(config.environment) {
            $1
        }
        let stdin = Pipe()
        let stdout = Pipe()
        let stderr = Pipe()
        process.standardInput = stdin
        process.standardOutput = stdout
        process.standardError = stderr
        do {
            try process.run()
        } catch {
            throw SidecarError.launchFailed("\(config.executable.path): \(error.localizedDescription)")
        }
        generation += 1
        let gen = generation
        self.process = process
        input = stdin.fileHandleForWriting
        stderrTail = []
        log.info("sidecar started (pid \(process.processIdentifier))")

        let replies = Self.lines(stdout.fileHandleForReading)
        Task.detached { [weak self] in
            for await line in replies {
                await self?.deliver(line)
            }
            await self?.stdoutClosed(generation: gen)
        }
        let errors = Self.lines(stderr.fileHandleForReading)
        Task.detached { [weak self] in
            for await line in errors {
                await self?.logStderr(String(decoding: line, as: UTF8.self))
            }
        }
    }

    /// Non-empty lines of a pipe until EOF. Reads happen in a dispatch-source handler: blocking
    /// `read()`s (as `FileHandle.bytes` does) would pin Swift concurrency's cooperative threads.
    nonisolated static func lines(_ handle: FileHandle) -> AsyncStream<Data> {
        AsyncStream { continuation in
            let buffer = OSAllocatedUnfairLock(initialState: Data())
            handle.readabilityHandler = { handle in
                let chunk = handle.availableData
                let lines = buffer.withLock { pending -> [Data] in
                    if chunk.isEmpty {  // EOF: flush an unterminated last line
                        defer { pending = Data() }
                        return pending.isEmpty ? [] : [pending]
                    }
                    pending.append(chunk)
                    var out: [Data] = []
                    while let newline = pending.firstIndex(of: 0x0A) {
                        let line = Data(pending[..<newline])
                        if !line.isEmpty { out.append(line) }
                        pending = Data(pending[pending.index(after: newline)...])
                    }
                    return out
                }
                for line in lines { continuation.yield(line) }
                if chunk.isEmpty {
                    handle.readabilityHandler = nil
                    continuation.finish()
                }
            }
        }
    }

    private func deliver(_ line: Data) {
        guard let head = try? Self.decoder.decode(Head.self, from: line) else {
            log.error("unparseable reply: \(String(decoding: line.prefix(200), as: UTF8.self))")
            return
        }
        if head.id == nil, head.method == "progress" {
            if let note = try? Self.decoder.decode(Notification.self, from: line) {
                progressSink.yield(note.params)
            }
            return
        }
        guard let id = head.id, let continuation = pending.removeValue(forKey: id) else {
            if let error = head.error {
                log.error("sidecar error without request: \(error.message)")
            }
            return
        }
        if let error = head.error {
            continuation.resume(throwing: SidecarError.rpc(code: error.code, message: error.message))
        } else {
            continuation.resume(returning: line)
        }
    }

    private func logStderr(_ line: String) {
        log.debug("\(line, privacy: .public)")
        stderrTail.append(line)
        if stderrTail.count > 20 { stderrTail.removeFirst(stderrTail.count - 20) }
    }

    private func stdoutClosed(generation gen: Int) {
        guard gen == generation else { return }  // an older, already replaced process
        let status: Int32
        if let process, !process.isRunning {
            status = process.terminationStatus
        } else {
            status = -1
        }
        log.notice("sidecar stdout closed (status \(status))")
        process = nil
        input = nil
        failPending(with: SidecarError.exited(
            status: status, log: stderrTail.suffix(5).joined(separator: "\n")))
    }

    private func failPending(with error: SidecarError) {
        let waiting = pending
        pending = [:]
        for continuation in waiting.values {
            continuation.resume(throwing: error)
        }
    }

    // MARK: - Envelopes

    static let encoder = JSONEncoder()
    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private struct Request<P: Encodable>: Encodable {
        let jsonrpc = "2.0"
        let id: Int
        let method: String
        let params: P
    }

    private struct Head: Decodable {
        struct ErrorBody: Decodable {
            let code: Int
            let message: String
        }
        let id: Int?
        let method: String?
        let error: ErrorBody?
    }

    private struct Notification: Decodable {
        let params: SidecarProgress
    }

    private struct ResultEnvelope<R: Decodable>: Decodable {
        let result: R
    }
}

/// Parameter-less requests.
public struct NoParams: Encodable, Sendable {
    public init() {}
}
