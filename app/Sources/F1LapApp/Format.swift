import F1LapKit
import SwiftUI

enum Fmt {
    static func lapTime(_ s: Double?) -> String {
        guard let s, s.isFinite else { return "—" }
        let m = Int(s) / 60
        return m > 0 ? String(format: "%d:%06.3f", m, s - Double(m * 60)) : String(format: "%.3f", s)
    }

    /// Signed seconds; positive = compared lap slower.
    static func delta(_ s: Double?, digits: Int = 3) -> String {
        guard let s, s.isFinite else { return "—" }
        return String(format: "%+.\(digits)f", s)
    }

    static func speed(_ v: Double?) -> String {
        guard let v, v.isFinite else { return "—" }
        return String(format: "%.0f", v)
    }

    static func lap(_ label: LapLabel, year: Bool = false) -> String {
        let name = label.lapNumber.map { "\(label.driver) L\($0)" } ?? label.driver
        return year ? label.year.map { "\(name) · \($0)" } ?? name : name
    }
}

enum Palette {
    static let reference = Color.blue
    static let other = Color.orange
    /// Negative delta = compared lap gaining.
    static func delta(_ s: Double) -> Color { s < 0 ? .green : s > 0 ? .red : .secondary }
}

extension Color {
    init?(hex: String?) {
        guard let hex, hex.hasPrefix("#"), let v = UInt32(hex.dropFirst(), radix: 16) else {
            return nil
        }
        self.init(red: Double(v >> 16 & 0xFF) / 255, green: Double(v >> 8 & 0xFF) / 255,
                  blue: Double(v & 0xFF) / 255)
    }
}
