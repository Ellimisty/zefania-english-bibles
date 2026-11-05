"""Download ALL CrossWire SWORD rawzip modules -> sword/mods/<Name>/.

  python sword_get.py [--only TSK,BDB,Thayer] [--max 20]

Fetches the rawzip index, downloads each <Name>.zip, extracts into
sword/mods/<Name>/ (mods.d/*.conf + modules/**). Resumable: skips
existing complete extracts. ~464 modules, a few GB total.
"""

import os
import sys
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

BASE = "https://www.crosswire.org/ftpmirror/pub/sword/packages/rawzip/"
OUT = "sword/mods"
UA = {"User-Agent": "sword_get/1.0"}


def fetch(url, path=None):
    req = urllib.request.Request(url, headers=UA)
    data = urllib.request.urlopen(req, timeout=120).read()
    if path:
        open(path, "wb").write(data)
    return data


def get_index():
    html = fetch(BASE).decode("utf-8", "replace")
    import re
    return sorted(set(re.findall(r'href="([A-Za-z0-9_\-+.]+)\.zip"', html)))


def dl(name):
    dest = os.path.join(OUT, name)
    marker = os.path.join(dest, ".done")
    if os.path.exists(marker):
        return f"skip {name}"
    zpath = os.path.join("sword", name + ".zip")
    try:
        if not os.path.exists(zpath):
            fetch(BASE + name + ".zip", zpath)
        os.makedirs(dest, exist_ok=True)
        zipfile.ZipFile(zpath).extractall(dest)
        open(marker, "w").write("ok")
        return f"ok   {name} ({os.path.getsize(zpath) >> 10} KB)"
    except Exception as e:
        return f"FAIL {name}: {e}"


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs("sword", exist_ok=True)
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    names = get_index()
    if only:
        keep = {s.lower() for s in only.split(",")}
        names = [n for n in names if n.lower() in keep]
    if "--max" in sys.argv:
        names = names[:int(sys.argv[sys.argv.index("--max") + 1])]
    print(f"{len(names)} modules")
    with ThreadPoolExecutor(8) as ex:
        for r in ex.map(dl, names):
            print(r)


if __name__ == "__main__":
    main()
