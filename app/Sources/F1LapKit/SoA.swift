import Foundation

/// Layout entry of a Structure-of-Arrays trace file (see `f1lap/binary.py`).
public struct SoAColumnLayout: Codable, Sendable, Equatable {
    public let name: String
    public let dtype: String  // "f64" or "i16", little-endian
    public let offset: Int
    public let count: Int

    public init(name: String, dtype: String, offset: Int, count: Int) {
        self.name = name
        self.dtype = dtype
        self.offset = offset
        self.count = count
    }
}

public enum SoAError: Error, Equatable {
    case unsupportedDType(String)
    case outOfBounds(String)
}

/// Columns of a trace file, all converted to `Double` (integer channels are small: gear, DRS).
public struct Traces: Sendable {
    public let columns: [String: [Double]]

    public init(columns: [String: [Double]]) {
        self.columns = columns
    }

    public subscript(name: String) -> [Double] {
        columns[name] ?? []
    }

    /// Reads every column of `url`. The file is memory-mapped and each column copied out once.
    public static func read(_ url: URL, layout: [SoAColumnLayout]) throws -> Traces {
        let data = try Data(contentsOf: url, options: .alwaysMapped)
        var columns: [String: [Double]] = [:]
        try data.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
            for col in layout {
                let width: Int
                switch col.dtype {
                case "f64": width = 8
                case "i16": width = 2
                default: throw SoAError.unsupportedDType(col.dtype)
                }
                let (bytes, overflow) = col.count.multipliedReportingOverflow(by: width)
                guard col.offset >= 0, col.count >= 0, !overflow,
                      col.offset <= raw.count, bytes <= raw.count - col.offset
                else { throw SoAError.outOfBounds(col.name) }
                let start = raw.baseAddress! + col.offset
                // loadUnaligned: no alignment assumptions about the mapping.
                if width == 8 {
                    columns[col.name] = (0..<col.count).map {
                        Double(bitPattern: UInt64(littleEndian:
                            start.loadUnaligned(fromByteOffset: $0 * 8, as: UInt64.self)))
                    }
                } else {
                    columns[col.name] = (0..<col.count).map {
                        Double(Int16(littleEndian:
                            start.loadUnaligned(fromByteOffset: $0 * 2, as: Int16.self)))
                    }
                }
            }
        }
        return Traces(columns: columns)
    }
}
