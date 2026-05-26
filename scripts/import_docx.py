import argparse
import html
import json
import posixpath
import re
import shutil
import sys
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}
REL_NS = {"pr": "http://schemas.openxmlformats.org/package/2006/relationships"}

SOLUTION_MARKERS = [
    "solution:",
    "answer:",
    "explanation:",
    "dap an:",
    "loi giai:",
]


def qn(prefix, name):
    return f"{{{NS[prefix]}}}{name}"


def normalize_text(value):
    lowered = (value or "").lower()
    normalized = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def find_solution_marker_index(text):
    normalized = normalize_text(text)
    indexes = [normalized.find(marker) for marker in SOLUTION_MARKERS]
    indexes = [idx for idx in indexes if idx >= 0]
    return min(indexes) if indexes else -1


def is_solution_start(text):
    t = normalize_text((text or "").strip())
    return any(t.startswith(marker) for marker in SOLUTION_MARKERS)


def text_of_paragraph(paragraph):
    chunks = []
    for run in paragraph.findall("w:r", NS):
        for child in run:
            if child.tag == qn("w", "t"):
                chunks.append(child.text or "")
            elif child.tag == qn("w", "tab"):
                chunks.append("\t")
            elif child.tag == qn("w", "br"):
                chunks.append("\n")
            elif child.tag == qn("w", "drawing"):
                chunks.append(" [IMAGE] ")
    return " ".join("".join(chunks).split())


def run_flags(run):
    props = run.find("w:rPr", NS)
    if props is None:
        return {"bold": False, "italic": False, "underline": False}
    underline = props.find("w:u", NS)
    underline_on = underline is not None and underline.attrib.get(qn("w", "val"), "single") != "none"
    return {
        "bold": props.find("w:b", NS) is not None,
        "italic": props.find("w:i", NS) is not None,
        "underline": underline_on,
    }


def load_relationships(docx_path):
    rel_map = {}
    with zipfile.ZipFile(docx_path) as archive:
        if "word/_rels/document.xml.rels" not in archive.namelist():
            return rel_map
        rel_root = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
    for rel in rel_root.findall("pr:Relationship", REL_NS):
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target", "")
        rel_type = rel.attrib.get("Type", "")
        if rid and rel_type.endswith("/image"):
            rel_map[rid] = target
    return rel_map


def normalize_target(target):
    t = target.replace("\\", "/")
    if t.startswith("/"):
        t = t.lstrip("/")
    if not t.startswith("word/"):
        t = posixpath.normpath(posixpath.join("word", t))
    return t


def extract_media_files(docx_path, output_dir):
    media_dir = output_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(docx_path) as archive:
        names = [n for n in archive.namelist() if n.startswith("word/media/")]
        for name in names:
            out_file = media_dir / Path(name).name
            with archive.open(name) as src, out_file.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    return media_dir


def drawing_html(drawing_node, rel_map):
    blips = drawing_node.findall(".//a:blip", NS)
    imgs = []
    for blip in blips:
        rid = blip.attrib.get(qn("r", "embed"))
        if not rid:
            continue
        target = rel_map.get(rid)
        if not target:
            continue
        src_name = Path(normalize_target(target)).name
        if not src_name:
            continue
        src = f"data/media/{src_name}"
        imgs.append(f'<img class="card-image" src="{html.escape(src)}" alt="Hinh cau hoi">')
    return imgs


def paragraph_to_html(paragraph, rel_map, *, hide_underline, cutoff_at_solution=False):
    parts = []
    consumed = ""
    stop = False
    for run in paragraph.findall("w:r", NS):
        if stop:
            break
        flags = run_flags(run)
        run_parts = []
        for child in run:
            if stop:
                break
            if child.tag == qn("w", "t"):
                raw = child.text or ""
                if cutoff_at_solution:
                    marker_idx = find_solution_marker_index(consumed + raw)
                    if marker_idx >= 0:
                        keep = max(0, marker_idx - len(consumed))
                        raw = raw[:keep]
                        stop = True
                consumed += raw
                if raw:
                    run_parts.append(html.escape(raw))
            elif child.tag == qn("w", "tab"):
                run_parts.append('<span class="tab"></span>')
            elif child.tag == qn("w", "br"):
                run_parts.append("<br>")
            elif child.tag == qn("w", "drawing"):
                run_parts.extend(drawing_html(child, rel_map))

        if not run_parts:
            continue

        classes = []
        if flags["bold"]:
            classes.append("b")
        if flags["italic"]:
            classes.append("i")
        if flags["underline"] and not hide_underline:
            classes.append("u")

        content = "".join(run_parts)
        if classes and "<img " not in content:
            parts.append(f'<span class="{" ".join(classes)}">{content}</span>')
        else:
            parts.append(content)
    return f'<p>{"".join(parts)}</p>'


def is_card_start(text):
    return bool(re.match(r"^(?:Câu\s*\d+|\d+)\s*:", text, flags=re.IGNORECASE))


def is_context_line(text):
    stripped = text.strip()
    return bool(
        re.match(r"^(?:Chapter|Chương)\b", stripped, flags=re.IGNORECASE)
        or re.match(r"^TCQT", stripped, flags=re.IGNORECASE)
    )


def next_context(existing, text):
    if re.match(r"^(?:Chapter|Chương)\b", text.strip(), flags=re.IGNORECASE):
        return [text]
    if re.match(r"^TCQT", text.strip(), flags=re.IGNORECASE):
        return [text]
    return [*existing, text][-3:]


def extract_paragraphs(docx_path, rel_map):
    with zipfile.ZipFile(docx_path) as archive:
        document_xml = archive.read("word/document.xml")
    root = ET.fromstring(document_xml)

    paragraphs = []
    for paragraph in root.findall(".//w:p", NS):
        text = text_of_paragraph(paragraph)
        marker_idx = find_solution_marker_index(text)
        visible_text = text[:marker_idx].strip() if marker_idx >= 0 else text

        front = paragraph_to_html(paragraph, rel_map, hide_underline=True, cutoff_at_solution=True)
        original = paragraph_to_html(paragraph, rel_map, hide_underline=False, cutoff_at_solution=False)
        has_image = "<img " in front or "<img " in original
        if not visible_text and not has_image and marker_idx < 0:
            continue
        paragraphs.append(
            {
                "text": visible_text or "[IMAGE]",
                "front": front,
                "original": original,
                "is_solution_start": is_solution_start(text) or marker_idx >= 0,
            }
        )
    return paragraphs


def build_cards(paragraphs):
    cards = []
    current = None
    context = []

    def close_current():
        nonlocal current
        if current is None:
            return
        card_index = len(cards) + 1
        first_line = current["plain"][0]
        title_match = re.match(r"^((?:Câu\s*\d+|\d+)\s*:)", first_line, flags=re.IGNORECASE)
        title = title_match.group(1) if title_match else f"Câu {card_index}"
        cards.append(
            {
                "id": f"q{card_index:04d}",
                "index": card_index,
                "title": title,
                "context": " / ".join(current["context"]),
                "text": "\n".join(current["plain"]),
                "frontHtml": "\n".join(current["front"]),
                "originalHtml": "\n".join(current["original"]),
            }
        )
        current = None

    for paragraph in paragraphs:
        text = paragraph["text"]
        if is_card_start(text):
            close_current()
            current = {
                "context": list(context),
                "plain": [text],
                "front": [paragraph["front"]],
                "original": [paragraph["original"]],
                "in_solution": False,
            }
            continue

        if current is None:
            if is_context_line(text):
                context = next_context(context, text)
            continue

        if is_context_line(text):
            close_current()
            context = next_context(context, text)
            continue

        if paragraph.get("is_solution_start"):
            current["in_solution"] = True

        if current.get("in_solution"):
            current["original"].append(paragraph["original"])
            continue

        current["plain"].append(text)
        current["front"].append(paragraph["front"])
        current["original"].append(paragraph["original"])

    close_current()
    return cards


def main():
    parser = argparse.ArgumentParser(description="Import DOCX quiz bank into static flashcard data.")
    parser.add_argument("docx", type=Path, help="Path to the source .docx file")
    parser.add_argument("-o", "--output", type=Path, default=Path("data/cards.json"), help="Output JSON path")
    args = parser.parse_args()

    if not args.docx.exists():
        raise SystemExit(f"Cannot find DOCX file: {args.docx}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    extract_media_files(args.docx, args.output.parent)
    rel_map = load_relationships(args.docx)
    paragraphs = extract_paragraphs(args.docx, rel_map)
    cards = build_cards(paragraphs)
    payload = {"source": str(args.docx), "cardCount": len(cards), "cards": cards}

    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    args.output.write_text(json_text, encoding="utf-8")

    js_output = args.output.with_suffix(".js")
    js_output.write_text(f"window.QUIZ_DATA = {json_text};\n", encoding="utf-8")
    print(f"Wrote {len(cards)} cards to {args.output} and {js_output}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
