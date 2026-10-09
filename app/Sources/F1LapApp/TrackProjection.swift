import CoreGraphics

/// Track x/y rotated by the circuit's angle and fitted into a canvas with an inset, y up.
struct TrackProjection {
    /// The rotated track's extent: computed once, then fitted to any canvas size.
    struct Bounds {
        fileprivate let cosR: Double, sinR: Double
        fileprivate let minX: Double, maxX: Double, minY: Double, maxY: Double

        /// `nil` when there are no points.
        init?(x: [Double], y: [Double], rotationDeg: Double) {
            let rot = rotationDeg * .pi / 180
            let c = cos(rot), s = sin(rot)
            let rx = zip(x, y).map { $0 * c - $1 * s }
            let ry = zip(x, y).map { $0 * s + $1 * c }
            guard let minX = rx.min(), let maxX = rx.max(), let minY = ry.min(), let maxY = ry.max()
            else { return nil }
            (cosR, sinR) = (c, s)
            (self.minX, self.maxX, self.minY, self.maxY) = (minX, maxX, minY, maxY)
        }

        /// A square `2 * half` wide around (x, y), in x/y units (the caller converts from metres):
        /// a camera window following the cars.
        init(around x: Double, _ y: Double, half: Double, rotationDeg: Double) {
            let rot = rotationDeg * .pi / 180
            (cosR, sinR) = (cos(rot), sin(rot))
            let cx = x * cosR - y * sinR, cy = x * sinR + y * cosR
            (minX, maxX, minY, maxY) = (cx - half, cx + half, cy - half, cy + half)
        }
    }

    private let b: Bounds
    private let scale: Double, ox: Double, oy: Double, height: Double

    /// `nil` when there are no points.
    init?(x: [Double], y: [Double], rotationDeg: Double, size: CGSize, inset: Double = 18) {
        guard let b = Bounds(x: x, y: y, rotationDeg: rotationDeg) else { return nil }
        self.init(b, size: size, inset: inset)
    }

    init(_ b: Bounds, size: CGSize, inset: Double = 18) {
        self.b = b
        scale = min((size.width - 2 * inset) / max(b.maxX - b.minX, 1),
                    (size.height - 2 * inset) / max(b.maxY - b.minY, 1))
        ox = (size.width - (b.maxX - b.minX) * scale) / 2
        oy = (size.height - (b.maxY - b.minY) * scale) / 2
        height = size.height
    }

    func callAsFunction(_ x: Double, _ y: Double) -> CGPoint {
        let rx = x * b.cosR - y * b.sinR, ry = x * b.sinR + y * b.cosR
        return CGPoint(x: ox + (rx - b.minX) * scale, y: height - oy - (ry - b.minY) * scale)
    }
}
