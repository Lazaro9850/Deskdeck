"""Gera o icone do app (PNG) sem dependencias externas."""
import struct, sys, zlib, os


def png(path, size):
    bg = (11, 15, 20)
    cyan = (62, 199, 224)
    green = (70, 211, 126)
    rows = []
    r = size * 0.18
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            # quadrado arredondado
            dx = max(r - x, 0, x - (size - 1 - r))
            dy = max(r - y, 0, y - (size - 1 - r))
            inside = dx * dx + dy * dy <= r * r
            if not inside:
                row += bytes((0, 0, 0, 0))
                continue
            c = bg
            # tres barras (graficos) e um ponto verde
            u, v = x / size, y / size
            bars = [(0.22, 0.30, 0.62), (0.42, 0.50, 0.40), (0.62, 0.70, 0.52)]
            for x0, x1, top in bars:
                if x0 <= u <= x1 and top <= v <= 0.78:
                    c = cyan
            if (u - 0.74) ** 2 + (v - 0.26) ** 2 <= 0.07 ** 2:
                c = green
            row += bytes((c[0], c[1], c[2], 255))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    data += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


if __name__ == "__main__":
    res = sys.argv[1]
    for folder, size in (("drawable-ldpi", 36), ("drawable-mdpi", 48), ("drawable-hdpi", 72), ("drawable-xhdpi", 96)):
        png(os.path.join(res, folder, "icon.png"), size)
