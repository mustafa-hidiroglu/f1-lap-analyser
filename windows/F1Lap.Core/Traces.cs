using System.Buffers.Binary;

namespace F1Lap.Core;

/// Layout entry of a Structure-of-Arrays trace file (see `f1lap/binary.py`).
public sealed record SoAColumnLayout(string Name, string Dtype, long Offset, long Count);

public sealed class SoAException(string message) : Exception(message)
{
    public static SoAException UnsupportedDType(string dtype) => new($"unsupported dtype {dtype}");
    public static SoAException OutOfBounds(string column) => new($"column {column} out of bounds");
}

/// Columns of a trace file, all converted to double (integer channels are small: gear, DRS).
public sealed class Traces(IReadOnlyDictionary<string, double[]> columns)
{
    public IReadOnlyDictionary<string, double[]> Columns { get; } = columns;

    /// The column, or an empty array when the file has none of that name.
    public double[] this[string name] => Columns.TryGetValue(name, out var c) ? c : [];

    /// Reads every column of `path`. The whole file is read once and the handle closed straight
    /// away, so the sidecar can prune it later (Windows won't delete a file that is open).
    public static Traces Read(string path, IEnumerable<SoAColumnLayout> layout) =>
        Decode(File.ReadAllBytes(path), layout);

    public static Traces Decode(ReadOnlySpan<byte> raw, IEnumerable<SoAColumnLayout> layout)
    {
        var columns = new Dictionary<string, double[]>();
        foreach (var col in layout)
        {
            int width = col.Dtype switch
            {
                "f64" => 8,
                "i16" => 2,
                _ => throw SoAException.UnsupportedDType(col.Dtype),
            };
            if (col.Offset < 0 || col.Count < 0 || col.Count > long.MaxValue / width
                || col.Offset > raw.Length || col.Count * width > raw.Length - col.Offset)
                throw SoAException.OutOfBounds(col.Name);
            var bytes = raw.Slice((int)col.Offset, (int)(col.Count * width));
            var values = new double[col.Count];
            for (int i = 0; i < values.Length; i++)
                values[i] = width == 8
                    ? BinaryPrimitives.ReadDoubleLittleEndian(bytes[(i * 8)..])
                    : BinaryPrimitives.ReadInt16LittleEndian(bytes[(i * 2)..]);
            columns[col.Name] = values;
        }
        return new Traces(columns);
    }
}
