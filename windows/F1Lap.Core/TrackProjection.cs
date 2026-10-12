namespace F1Lap.Core;

/// Track x/y rotated by the circuit's angle and fitted into a canvas with an inset, y up
/// (mirrors TrackProjection.swift).
public readonly struct TrackProjection
{
    /// The rotated track's extent: computed once, then fitted to any canvas size.
    public readonly struct Bounds
    {
        internal readonly double CosR, SinR, MinX, MaxX, MinY, MaxY;

        private Bounds(double cosR, double sinR, double minX, double maxX, double minY, double maxY) =>
            (CosR, SinR, MinX, MaxX, MinY, MaxY) = (cosR, sinR, minX, maxX, minY, maxY);

        /// Null when there are no points.
        public static Bounds? Of(IReadOnlyList<double> x, IReadOnlyList<double> y, double rotationDeg)
        {
            int n = Math.Min(x.Count, y.Count);
            if (n == 0) return null;
            double rot = rotationDeg * Math.PI / 180, c = Math.Cos(rot), s = Math.Sin(rot);
            double minX = double.PositiveInfinity, maxX = double.NegativeInfinity;
            double minY = double.PositiveInfinity, maxY = double.NegativeInfinity;
            for (int i = 0; i < n; i++)
            {
                double rx = x[i] * c - y[i] * s, ry = x[i] * s + y[i] * c;
                minX = Math.Min(minX, rx); maxX = Math.Max(maxX, rx);
                minY = Math.Min(minY, ry); maxY = Math.Max(maxY, ry);
            }
            return new Bounds(c, s, minX, maxX, minY, maxY);
        }

        /// A square `2 * half` wide around (x, y), in x/y units: a camera window following the cars.
        public static Bounds Around(double x, double y, double half, double rotationDeg)
        {
            double rot = rotationDeg * Math.PI / 180, c = Math.Cos(rot), s = Math.Sin(rot);
            double cx = x * c - y * s, cy = x * s + y * c;
            return new Bounds(c, s, cx - half, cx + half, cy - half, cy + half);
        }
    }

    private readonly Bounds _b;
    private readonly double _scale, _ox, _oy, _height;

    public TrackProjection(Bounds b, double width, double height, double inset = 18)
    {
        _b = b;
        _scale = Math.Min((width - 2 * inset) / Math.Max(b.MaxX - b.MinX, 1),
                          (height - 2 * inset) / Math.Max(b.MaxY - b.MinY, 1));
        _ox = (width - (b.MaxX - b.MinX) * _scale) / 2;
        _oy = (height - (b.MaxY - b.MinY) * _scale) / 2;
        _height = height;
    }

    public (double X, double Y) Project(double x, double y)
    {
        double rx = x * _b.CosR - y * _b.SinR, ry = x * _b.SinR + y * _b.CosR;
        return (_ox + (rx - _b.MinX) * _scale, _height - _oy - (ry - _b.MinY) * _scale);
    }
}
