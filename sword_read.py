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


class ZLD:
    """zLD lexicon reader.

    dict.zdt = zlib blocks -> stream of 8B (offset,size) pairs + text.
    Pair i -> entry i text. dict.dat = key list ('name\\r\\n'+u32+u32+'\\r\\n').
    """

    def __init__(self, dirpath):
        import glob as _g
        zdtp = (_g.glob(os.path.join(dirpath, "*.zdt")) or [None])[0]
        zdxp = (_g.glob(os.path.join(dirpath, "*.zdx")) or [None])[0]
        idxp = (_g.glob(os.path.join(dirpath, "*.idx")) or [None])[0]
        datp = (_g.glob(os.path.join(dirpath, "*.dat")) or [None])[0]
        self.raw = b""
        if zdtp and zdxp:
            zdt = open(zdtp, "rb").read()
            zdx = open(zdxp, "rb").read()
            for i in range(len(zdx) // 8):
                off, _usize = struct.unpack_from("<II", zdx, i * 8)
                self.raw += zlib.decompress(zdt[off:])
        self.idx = open(idxp, "rb").read() if idxp else b""
        dat = open(datp, "rb").read() if datp else b""
        self.keys = []
        self.pair_idx = []
        if not self.raw:
            # rawld: uncompressed .dat records, .idx = (off,size) pairs
            self.raw = dat
            n = len(self.idx) // 8
            for i in range(n):
                off, size = struct.unpack_from("<II", self.idx, i * 8)
                rec = dat[off:off + size]
                k = rec.split(b"\r\n", 1)[0].split(b"\\", 1)[0]
                self.keys.append(k.decode("utf-8", "replace").strip())
                self.pair_idx.append((off, size))
        else:
            # zld: dat records = key\r\n + u32 + u32(pair ordinal) + \r\n
            pos = 0
            while pos < len(dat):
                eol = dat.find(b"\r\n", pos)
                if eol < 0:
                    break
                self.keys.append(dat[pos:eol].decode("utf-8", "replace"))
                pos = eol + 2
                _a, b = struct.unpack_from("<II", dat, pos)
                self.pair_idx.append(b)
                pos += 8
                if dat[pos:pos + 2] == b"\r\n":
                    pos += 2
        self.n = len(self.keys)

    def entry(self, i):
        p = self.pair_idx[i]
        if isinstance(p, tuple):
            off, size = p  # rawld direct (offset,size)
        else:            # zld: embedded pair stream
            off, size = struct.unpack_from("<II", self.raw, p * 8)
        return self.raw[off:off + size].decode("utf-8", "replace")


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
