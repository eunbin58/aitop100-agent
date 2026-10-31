import html
import json
import re
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).parent
KNOWLEDGE_DIR = ROOT / "knowledge"
INDEX_PATH = KNOWLEDGE_DIR / "knowledge_index.json"


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden_depth += 1
        elif tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.hidden_depth:
            self.hidden_depth -= 1
        elif tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def normalize(text: str) -> str:
    text = html.unescape(text).replace("\u00a0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def read_html(path: Path) -> str:
    parser = VisibleTextParser()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    return normalize("".join(parser.parts))


def read_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    parts: list[str] = []
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            parts.append(node.text)
        elif node.tag.endswith("}p"):
            parts.append("\n")
    return normalize(" ".join(parts))


def read_xlsx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in shared_root:
                shared.append("".join(node.text or "" for node in item.iter() if node.tag.endswith("}t")))

        rows: list[str] = []
        sheets = sorted(name for name in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))
        for sheet in sheets:
            root = ET.fromstring(archive.read(sheet))
            rows.append(f"[{Path(sheet).stem}]")
            for row in (node for node in root.iter() if node.tag.endswith("}row")):
                values: list[str] = []
                for cell in (node for node in row if node.tag.endswith("}c")):
                    cell_type = cell.attrib.get("t")
                    value_node = next((node for node in cell.iter() if node.tag.endswith("}v")), None)
                    inline = "".join(node.text or "" for node in cell.iter() if node.tag.endswith("}t"))
                    value = inline or (value_node.text if value_node is not None else "") or ""
                    if cell_type == "s" and value.isdigit() and int(value) < len(shared):
                        value = shared[int(value)]
                    if value.strip():
                        values.append(value.strip())
                if values:
                    rows.append(" | ".join(values))
    return normalize("\n".join(rows))


def read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    return normalize("\n".join(page.extract_text() or "" for page in PdfReader(path).pages))


def read_source(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return normalize(path.read_text(encoding="utf-8", errors="ignore"))
    if suffix == ".html":
        return read_html(path)
    if suffix == ".docx":
        return read_docx(path)
    if suffix == ".xlsx":
        return read_xlsx(path)
    if suffix == ".pdf":
        return read_pdf(path)
    return ""


def chunks(text: str, size: int = 1400, overlap: int = 180):
    paragraphs = [part.strip() for part in re.split(r"\n{1,}", text) if part.strip()]
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > size:
            if current:
                yield current
                current = ""
            start = 0
            while start < len(paragraph):
                yield paragraph[start : start + size]
                start += size - overlap
        elif not current:
            current = paragraph
        elif len(current) + len(paragraph) + 1 <= size:
            current += "\n" + paragraph
        else:
            yield current
            current = paragraph
    if current:
        yield current


def source_paths() -> list[Path]:
    paths = [
        KNOWLEDGE_DIR / "notion_knowledge_hub.md",
        KNOWLEDGE_DIR / "notion_operation_notes.md",
    ]
    for folder in (KNOWLEDGE_DIR / "raw", KNOWLEDGE_DIR / "extracted"):
        paths.extend(
            path
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.lower() in {".html", ".pdf", ".xlsx", ".docx"}
        )
    return sorted(set(paths))


def main() -> None:
    records: list[dict[str, str]] = []
    skipped: list[str] = []
    for path in source_paths():
        try:
            text = read_source(path)
        except Exception as exc:
            skipped.append(f"{path.relative_to(KNOWLEDGE_DIR)}: {type(exc).__name__}")
            continue
        if not text:
            skipped.append(f"{path.relative_to(KNOWLEDGE_DIR)}: no text")
            continue
        source = str(path.relative_to(KNOWLEDGE_DIR)).replace("\\", "/")
        records.extend({"source": source, "text": chunk} for chunk in chunks(text))

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "chunk_count": len(records),
        "skipped": skipped,
        "chunks": records,
    }
    INDEX_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"created {INDEX_PATH} with {len(records)} chunks; skipped={len(skipped)}")


if __name__ == "__main__":
    main()
