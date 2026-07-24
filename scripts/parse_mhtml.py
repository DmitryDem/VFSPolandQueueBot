"""Извлекает читаемый текст из mhtml-файлов VFS (документы/фото по визам)."""
import email
import quopri
import re
import sys
from pathlib import Path

SRC = Path(r"c:\Work\Скриншоты\VFS")
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("mhtml_txt")
OUT.mkdir(parents=True, exist_ok=True)

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t]+")
BLANK_RE = re.compile(r"\n\s*\n\s*\n+")


def extract(path: Path) -> str:
    msg = email.message_from_bytes(path.read_bytes())
    html = None
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                html = payload.decode(charset, "replace")
                break
    if not html:
        return ""
    # выкидываем скрипты/стили
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    html = re.sub(r"</(p|div|li|tr|h[1-6]|br)[^>]*>", "\n", html, flags=re.I)
    html = re.sub(r"<br[^>]*>", "\n", html, flags=re.I)
    text = TAG_RE.sub("", html)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
            .replace("&laquo;", "«").replace("&raquo;", "»")
            .replace("&mdash;", "—").replace("&ndash;", "–").replace("&quot;", '"'))
    text = WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = BLANK_RE.sub("\n\n", text)
    return text.strip()


for f in sorted(SRC.glob("*.mhtml")):
    txt = extract(f)
    out = OUT / (f.stem + ".txt")
    out.write_text(txt, encoding="utf-8")
    print(f"{f.name}: {len(txt)} символов -> {out.name}")
