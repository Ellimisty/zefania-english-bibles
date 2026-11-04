import os
import re
import xml.etree.ElementTree as ET

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SRC_DIR, "split")


def safe_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name or "unknown"


def indent(elem, level=0):
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        for e in elem:
            indent(e, level + 1)
        if not e.tail or not e.tail.strip():
            e.tail = i
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = i


def split_file(path):
    tree = ET.parse(path)
    root = tree.getroot()
    biblename = root.get("biblename", "").strip()
    folder = safe_name(os.path.splitext(os.path.basename(path))[0])

    books = root.findall("BIBLEBOOK")
    if not books:
        books = root.findall(".//BIBLEBOOK")

    count = 0
    for book in books:
        bname = safe_name(book.get("bname") or book.get("bsname") or "book")
        bnumber = book.get("bnumber", "")
        book_dir = os.path.join(OUT_DIR, folder, f"{int(bnumber):02d}_{bname}" if bnumber.isdigit() else bname)
        os.makedirs(book_dir, exist_ok=True)
        for ch in book.findall("CHAPTER"):
            cnum = ch.get("cnumber", "0")
            out = ET.Element("XMLBIBLE", {
                "version": root.get("version", "2.0.1.18"),
                "biblename": biblename,
                "type": root.get("type", "x-bible"),
            })
            b = ET.SubElement(out, "BIBLEBOOK", {k: v for k, v in book.attrib.items()})
            c = ET.SubElement(b, "CHAPTER", {k: v for k, v in ch.attrib.items()})
            for child in ch:
                c.append(child)
            indent(out)
            fname = f"{int(cnum):03d}.xml" if cnum.isdigit() else f"{safe_name(cnum)}.xml"
            ET.ElementTree(out).write(
                os.path.join(book_dir, fname),
                encoding="utf-8",
                xml_declaration=True,
            )
            count += 1
    return folder, len(books), count


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for fn in sorted(os.listdir(SRC_DIR)):
        if not fn.lower().endswith(".xml"):
            continue
        path = os.path.join(SRC_DIR, fn)
        try:
            folder, nbooks, nch = split_file(path)
            print(f"{fn}: -> {folder}/ ({nbooks} books, {nch} chapters)")
        except Exception as e:
            print(f"{fn}: FAILED ({e})")


if __name__ == "__main__":
    main()
