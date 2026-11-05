"""Process chats/*.mhtml -> chats/_<stem>.txt (idempotent).

Extracts the HTML part, strips script/style/tags, writes plain text.
Skips files already processed (txt newer than source mhtml).

Then prints the user-message lines (heuristic: lines near 'You said')
for feature mining.
"""

import email
import glob
import os
import re

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chats")


def mhtml_to_text(path):
    msg = email.message_from_bytes(open(path, "rb").read())
    html = None
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            html = part.get_payload(decode=True).decode("utf-8", "replace")
            break
    if not html:
        return ""
    txt = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html)
    txt = re.sub(r"<[^>]+>", "\n", txt)
    txt = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), txt)
    txt = re.sub(r"&amp;", "&", txt)
    txt = re.sub(r"&lt;", "<", txt)
    txt = re.sub(r"&gt;", ">", txt)
    txt = re.sub(r"&quot;", '"', txt)
    txt = re.sub(r"&nbsp;", " ", txt)
    txt = re.sub(r"&#39;", "'", txt)
    return re.sub(r"\n\s*\n+", "\n", txt).strip()


def main():
    os.makedirs(DIR, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(DIR, "*.mhtml"))):
        out = os.path.join(DIR, "_" + os.path.splitext(
            os.path.basename(path))[0] + ".txt")
        if os.path.exists(out) and os.path.getmtime(out) > os.path.getmtime(path):
            print(f"skip (fresh): {os.path.basename(out)}")
            continue
        txt = mhtml_to_text(path)
        open(out, "w", encoding="utf-8").write(txt)
        print(f"{os.path.basename(out)}: {len(txt):,} chars")


if __name__ == "__main__":
    main()
