import argparse
import html
import json
import posixpath
import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}
REL_NS = {"pr": "http://schemas.openxmlformats.org/package/2006/relationships"}
ANSWER_KEYS = ["a", "b", "c", "d"]


def qn(prefix, name):
    return f"{{{NS[prefix]}}}{name}"


def attr_val(node, name):
    if node is None:
        return None
    return node.attrib.get(qn("w", name))


def child_val(parent, child_name):
    child = parent.find(f"w:{child_name}", NS) if parent is not None else None
    return attr_val(child, "val") if child is not None else None


def normalize_text(value):
    return " ".join((value or "").split())


def normalize_option(value):
    text = normalize_text(value)
    text = re.sub(r"^(?:(?:Question|Câu)\s*\d+\s*:)+\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^[a-dA-D]\s*[\.\)]\s*", "", text).strip()
    return text


def normalize_key(value):
    return re.sub(r"\s+", " ", normalize_option(value).lower())


def paragraph_style(paragraph):
    return child_val(paragraph.find("w:pPr", NS), "pStyle")


def paragraph_num(paragraph):
    props = paragraph.find("w:pPr", NS)
    num = props.find("w:numPr", NS) if props is not None else None
    if num is None:
        return None, None
    return child_val(num, "numId"), child_val(num, "ilvl")


def load_numbering_formats(archive):
    if "word/numbering.xml" not in archive.namelist():
        return {}

    root = ET.fromstring(archive.read("word/numbering.xml"))
    num_to_abstract = {}
    for num in root.findall("w:num", NS):
        num_id = num.attrib.get(qn("w", "numId"))
        abstract = num.find("w:abstractNumId", NS)
        if num_id and abstract is not None:
            num_to_abstract[num_id] = attr_val(abstract, "val")

    formats = {}
    for abstract in root.findall("w:abstractNum", NS):
        abstract_id = abstract.attrib.get(qn("w", "abstractNumId"))
        num_ids = [num_id for num_id, mapped_id in num_to_abstract.items() if mapped_id == abstract_id]
        if not num_ids:
            continue
        for level in abstract.findall("w:lvl", NS):
            ilvl = level.attrib.get(qn("w", "ilvl"))
            num_fmt = child_val(level, "numFmt")
            lvl_text = child_val(level, "lvlText")
            for num_id in num_ids:
                formats[(num_id, ilvl)] = {"numFormat": num_fmt, "levelText": lvl_text}
    return formats


def paragraph_prop_bold(paragraph):
    props = paragraph.find("w:pPr", NS)
    run_props = props.find("w:rPr", NS) if props is not None else None
    return run_props is not None and run_props.find("w:b", NS) is not None


def run_flags(run):
    props = run.find("w:rPr", NS)
    if props is None:
        return {"bold": False, "italic": False, "underline": False, "red": False, "highlight": False}
    underline = props.find("w:u", NS)
    color = props.find("w:color", NS)
    highlight = props.find("w:highlight", NS)
    return {
        "bold": props.find("w:b", NS) is not None,
        "italic": props.find("w:i", NS) is not None,
        "underline": underline is not None and attr_val(underline, "val") != "none",
        "red": color is not None and (attr_val(color, "val") or "").upper() == "FF0000",
        "highlight": highlight is not None,
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
    target = target.replace("\\", "/")
    if target.startswith("/"):
        target = target.lstrip("/")
    if not target.startswith("word/"):
        target = posixpath.normpath(posixpath.join("word", target))
    return target


def extract_media_files(docx_path, output_dir):
    media_dir = output_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(docx_path) as archive:
        for name in [item for item in archive.namelist() if item.startswith("word/media/")]:
            with archive.open(name) as src, (media_dir / Path(name).name).open("wb") as dst:
                shutil.copyfileobj(src, dst)


def drawing_html(drawing_node, rel_map):
    parts = []
    for blip in drawing_node.findall(".//a:blip", NS):
        rid = blip.attrib.get(qn("r", "embed"))
        target = rel_map.get(rid)
        if not target:
            continue
        src = f"data/media/{Path(normalize_target(target)).name}"
        parts.append(f'<img class="card-image" src="{html.escape(src)}" alt="Hinh cau hoi">')
    return parts


def paragraph_to_text_and_html(paragraph, rel_map):
    plain_parts = []
    html_parts = []
    has_run_bold = False
    has_red = False
    has_highlight = False

    for run in paragraph.findall("w:r", NS):
        flags = run_flags(run)
        has_run_bold = has_run_bold or flags["bold"]
        has_red = has_red or flags["red"]
        has_highlight = has_highlight or flags["highlight"]
        run_parts = []
        plain_run = []

        for child in run:
            if child.tag == qn("w", "t"):
                raw = child.text or ""
                plain_run.append(raw)
                run_parts.append(html.escape(raw))
            elif child.tag == qn("w", "tab"):
                plain_run.append("\t")
                run_parts.append('<span class="tab"></span>')
            elif child.tag == qn("w", "br"):
                plain_run.append("\n")
                run_parts.append("<br>")
            elif child.tag == qn("w", "drawing"):
                plain_run.append("[IMAGE]")
                run_parts.extend(drawing_html(child, rel_map))

        content = "".join(run_parts)
        plain_parts.append("".join(plain_run))
        if not content:
            continue

        classes = []
        if flags["bold"]:
            classes.append("b")
        if flags["italic"]:
            classes.append("i")
        if flags["underline"]:
            classes.append("u")
        if flags["red"]:
            classes.append("red")
        if flags["highlight"]:
            classes.append("hl")
        if classes and "<img " not in content:
            html_parts.append(f'<span class="{" ".join(classes)}">{content}</span>')
        else:
            html_parts.append(content)

    text = normalize_text("".join(plain_parts))
    return text, f"<p>{''.join(html_parts)}</p>", has_run_bold, has_red, has_highlight


def paragraph_records(docx_path):
    rel_map = load_relationships(docx_path)
    with zipfile.ZipFile(docx_path) as archive:
        numbering_formats = load_numbering_formats(archive)
        root = ET.fromstring(archive.read("word/document.xml"))

    records = []
    for paragraph in root.findall(".//w:p", NS):
        text, paragraph_html, has_run_bold, has_red, has_highlight = paragraph_to_text_and_html(paragraph, rel_map)
        if not text and "<img " not in paragraph_html:
            continue
        style = paragraph_style(paragraph)
        num_id, ilvl = paragraph_num(paragraph)
        numbering = numbering_formats.get((num_id, ilvl), {})
        strong = style in {"Heading1", "Heading2"} or has_run_bold or paragraph_prop_bold(paragraph)
        records.append(
            {
                "text": text,
                "html": paragraph_html,
                "style": style,
                "numId": num_id,
                "ilvl": ilvl,
                "numFormat": numbering.get("numFormat"),
                "levelText": numbering.get("levelText"),
                "strong": strong,
                "priority": has_red or has_highlight,
            }
        )
    return records


def is_section_heading(record):
    text = record["text"].strip()
    if record.get("numFormat") == "lowerLetter":
        return False
    if text.lower() == "ngân hàng thương mại 3":
        return True
    short_answer_like = len(text) <= 6 or "/" in text or re.match(r"^[A-D]\b", text)
    return bool(text and text.isupper() and len(text) < 80 and not short_answer_like)


def is_question_start(record):
    text = record["text"].strip()
    if text == "?":
        return False
    return bool(
        re.match(r"^(?:câu|question)\s*\d+\s*:", text, flags=re.IGNORECASE)
        or text.endswith("?")
        or re.match(r"^\d+\.", text)
    )


def is_bare_question_label(record):
    return bool(re.match(r"^(?:câu|question)\s*\d+\s*:\s*$", record["text"].strip(), flags=re.IGNORECASE))


def is_option_record(record):
    text = record["text"].strip()
    return record.get("numFormat") == "lowerLetter" or bool(re.match(r"^[a-dA-D]\s*[\.\)]", text))


def segments_from_records(records):
    segments = []
    current = None
    for record in records:
        if current and is_bare_question_label(record):
            continue

        if current and is_option_record(record):
            current["items"].append({ **record, "text": normalize_option(record["text"]) })
            continue

        if is_section_heading(record):
            if current:
                segments.append(current)
                current = None
            continue

        if is_question_start(record):
            if current and not current["items"] and is_bare_question_label(current["question"]):
                current["question"]["text"] = normalize_text(current["question"]["text"] + " " + record["text"])
                current["question"]["html"] = current["question"]["html"].replace(
                    "</p>",
                    f" {record['html']}</p>",
                )
                continue
            if current:
                segments.append(current)
            current = {"question": record, "items": []}
            continue

        if current:
            if record["text"].strip() == "?":
                current["question"]["text"] = normalize_text(current["question"]["text"] + "?")
                current["question"]["html"] = current["question"]["html"].replace("</p>", "? </p>")
            else:
                current["items"].append(record)

    if current:
        segments.append(current)
    return segments


def segments_from_numbered_records(records):
    segments = []
    current = None
    for record in records:
        if is_section_heading(record):
            if current:
                segments.append(current)
                current = None
            continue

        if record.get("ilvl") == "0":
            if current:
                segments.append(current)
            current = {"question": record, "items": []}
            continue

        if current and record.get("ilvl") == "1":
            current["items"].append({ **record, "text": normalize_option(record["text"]) })
            continue

        if current and current["items"]:
            current["items"][-1]["text"] = normalize_text(current["items"][-1]["text"] + " " + record["text"])
            current["items"][-1]["html"] = current["items"][-1]["html"].replace("</p>", f" {record['html']}</p>")
            current["items"][-1]["priority"] = current["items"][-1]["priority"] or record["priority"]
            current["items"][-1]["strong"] = current["items"][-1]["strong"] or record["strong"]
            continue

        if current:
            current["question"]["text"] = normalize_text(current["question"]["text"] + " " + record["text"])
            current["question"]["html"] = current["question"]["html"].replace("</p>", f" {record['html']}</p>")

    if current:
        segments.append(current)
    return segments


def unique_items(items):
    seen = set()
    unique = []
    for item in items:
        key = normalize_key(item["text"])
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def answer_index(options):
    priority = [index for index, option in enumerate(options) if option["priority"]]
    if len(priority) == 1:
        return priority[0]
    strong = [index for index, option in enumerate(options) if option["strong"]]
    if len(strong) == 1:
        return strong[0]
    return None


def title_for(question, fallback_index):
    match = re.match(r"^((?:câu|question)\s*\d+\s*:)", question, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return f"Câu {fallback_index}:"


def build_cards(segments, *, context, id_prefix, start_index):
    cards = []
    for segment in segments:
        card_number = len(cards) + 1
        question = segment["question"]
        items = unique_items(segment["items"])
        first_four = items[:4]
        selected = answer_index(first_four) if 3 <= len(first_four) <= 4 else None
        title = title_for(question["text"], card_number)
        base = {
            "id": f"{id_prefix}_{card_number:04d}",
            "index": start_index + card_number,
            "title": title,
            "context": context,
        }

        if selected is not None:
            options = [normalize_option(option["text"]) for option in first_four]
            text = "\n".join([question["text"], *[f"{ANSWER_KEYS[i].upper()}. {option}" for i, option in enumerate(options)]])
            cards.append(
                {
                    **base,
                    "type": "choice",
                    "question": question["text"],
                    "text": text,
                    "options": options,
                    "answerKey": ANSWER_KEYS[selected],
                    "answerIndex": selected,
                    "frontHtml": question["html"],
                    "originalHtml": "\n".join([question["html"], *[option["html"] for option in first_four]]),
                }
            )
            continue

        body = [question["html"], *[item["html"] for item in items]]
        cards.append(
            {
                **base,
                "text": "\n".join([question["text"], *[item["text"] for item in items]]),
                "frontHtml": question["html"],
                "originalHtml": "\n".join(body),
            }
        )
    return cards


def main():
    parser = argparse.ArgumentParser(description="Append formatted DOCX questions to quiz data.")
    parser.add_argument("docx", type=Path, help="Path to the source .docx file")
    parser.add_argument("-o", "--output", type=Path, default=Path("data/cards.json"), help="Quiz JSON output")
    parser.add_argument("--context", default="TRẮC NGHIỆM_CK", help="Quiz context/chapter label")
    parser.add_argument("--id-prefix", default="tn_ck", help="ID prefix for imported cards")
    parser.add_argument(
        "--segment-mode",
        choices=["mixed", "numbered"],
        default="mixed",
        help="Question segmentation strategy",
    )
    args = parser.parse_args()

    if not args.docx.exists():
        raise SystemExit(f"Cannot find DOCX file: {args.docx}")
    if not args.output.exists():
        raise SystemExit(f"Cannot find existing quiz data: {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    extract_media_files(args.docx, args.output.parent)

    payload = json.loads(args.output.read_text(encoding="utf-8"))
    existing_cards = [
        card for card in payload.get("cards", []) if not str(card.get("id", "")).startswith(f"{args.id_prefix}_")
    ]

    records = paragraph_records(args.docx)
    segments = segments_from_numbered_records(records) if args.segment_mode == "numbered" else segments_from_records(records)
    imported_cards = build_cards(segments, context=args.context, id_prefix=args.id_prefix, start_index=len(existing_cards))
    payload["cards"] = existing_cards + imported_cards
    payload["cardCount"] = len(payload["cards"])

    sources = payload.get("sources")
    if not isinstance(sources, list):
        sources = [payload.get("source")] if payload.get("source") else []
    source = str(args.docx)
    if source not in sources:
        sources.append(source)
    payload["sources"] = sources

    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    args.output.write_text(json_text, encoding="utf-8")
    args.output.with_suffix(".js").write_text(f"window.QUIZ_DATA = {json_text};\n", encoding="utf-8")

    choice_count = sum(1 for card in imported_cards if card.get("type") == "choice")
    print(f"Imported {len(imported_cards)} cards from {args.docx}")
    print(f"Choice cards: {choice_count}; flashcards: {len(imported_cards) - choice_count}")
    print(f"Wrote {len(payload['cards'])} cards to {args.output} and {args.output.with_suffix('.js')}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
