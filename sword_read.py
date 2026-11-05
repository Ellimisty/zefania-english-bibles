"""Read SWORD compressed modules (zCom commentaries, zText bibles,
zLD lexicons/dictionaries) -- no libsword needed.

Index layout (all u32 little-endian):
  .bzs : compressed data blocks (each independently zlib'd)
  .bzz : block -> (offset, size) in .bzs          [8 B rec]
  .bzv : verse/entry -> (block, start, len)       [12 B rec]
  Lexicons (.bz{u,d,i}): similar; .lzz/.lzu/.lzi for zLD
  RawGenBook: imp -> is NOT compressed here.

Verse indexing for zCom/zText: one 12-byte .bzv rec per verse,
testament-split (ot.* / nt.*); testament order follows SWORD versification.
"""

import os
import struct
import sys
import zlib


def _u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


class ZModule:
    """Generic z-compressed SWORD fileset reader."""

    def __init__(self, dirpath, testament=None):
        """testament: 'ot'/'nt' for zCom/zText; None for lexicons (single)."""
        self.dir = dirpath
        self.t = testament

    def _files(self):
        # .bzz = zlib data, .bzv = 12B idx, .bzs = block idx.
        # chapter-level modules use .cz* variants, same layout.
        for ext in ("bzz", "czz"):
            s = os.path.join(self.dir, f"{self.t}.{ext}")
            if os.path.exists(s):
                return (s, s[:-1] + "v", s[:-1] + "s")
        return (os.path.join(self.dir, f"{self.t}.bzz"),
                os.path.join(self.dir, f"{self.t}.bzv"),
                os.path.join(self.dir, f"{self.t}.bzs"))

    def nverses(self):
        _, v, _ = self._files()
        return os.path.getsize(v) // 12

    def read(self, idx):
        s, v, z = self._files()
        vs = open(v, "rb")
        vs.seek(idx * 12)
        blk, start, ln = struct.unpack("<III", vs.read(12))
        if not blk and not ln:
            return ""
        zs = open(z, "rb")
        zs.seek(4 + blk * 8)  # 4-byte header then (offset, size) recs
        off, size = struct.unpack("<II", zs.read(8))
        data = open(s, "rb").read()[off:off + size]
        raw = zlib.decompress(data)
        return raw[start:start + ln].decode("utf-8", "replace")


def main():
    path = sys.argv[1]
    t = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] in ("ot", "nt") \
        else None
    z = ZModule(path, t)
    print(f"{z.nverses()} entries")
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    for i in range(n):
        print(f"--- [{i}] ---")
        print(z.read(i)[:500])


if __name__ == "__main__":
    main()
