import argparse
import html
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
REL_NS = {"pr": "http://schemas.openxmlformats.org/package/2006/relationships"}
ANSWER_KEYS = {"a": 0, "b": 1, "c": 2, "d": 3}
NUMERIC_ANSWER_KEYS = {"1": "a", "2": "b", "3": "c", "4": "d"}


def column_letters(ref):
    match = re.match(r"([A-Z]+)", ref or "")
    return match.group(1) if match else "A"


def column_index(letters):
    index = 0
    for char in letters:
        index = index * 26 + ord(char) - 64
    return index - 1


def cell_text(cell, shared_strings):
    cell_type = cell.attrib.get("t")
    value = cell.find("a:v", NS)
    inline = cell.find("a:is", NS)
    if cell_type == "s" and value is not None:
        return shared_strings[int(value.text or "0")]
    if cell_type == "inlineStr" and inline is not None:
        return "".join(node.text or "" for node in inline.findall(".//a:t", NS))
    if value is not None:
        return value.text or ""
    return ""


def load_shared_strings(archive):
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.findall(".//a:t", NS)) for item in root.findall("a:si", NS)]


def workbook_sheets(archive):
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels.findall("pr:Relationship", REL_NS)}
    for sheet in workbook.findall("a:sheets/a:sheet", NS):
        rel_id = sheet.attrib[f"{{{NS['r']}}}id"]
        yield sheet.attrib["name"], "xl/" + rel_map[rel_id].lstrip("/")


def load_rows(xlsx_path, sheet_name):
    with zipfile.ZipFile(xlsx_path) as archive:
        shared_strings = load_shared_strings(archive)
        sheets = dict(workbook_sheets(archive))
        if sheet_name not in sheets:
            names = ", ".join(sheets)
            raise SystemExit(f"Cannot find sheet {sheet_name!r}. Available sheets: {names}")

        root = ET.fromstring(archive.read(sheets[sheet_name]))
        rows = []
        for row in root.findall("a:sheetData/a:row", NS):
            values = []
            for cell in row.findall("a:c", NS):
                index = column_index(column_letters(cell.attrib.get("r", "")))
                while len(values) <= index:
                    values.append("")
                values[index] = cell_text(cell, shared_strings).strip()
            rows.append(values)
        return rows


def strip_option_prefix(value):
    return re.sub(r"^\s*[a-dA-D]\s*[\.\)]\s*", "", value or "").strip()


def normalize_answer_key(value):
    raw = (value or "").strip().lower()
    if raw in ANSWER_KEYS:
        return raw

    numeric = raw
    if re.fullmatch(r"\d+\.0+", numeric):
        numeric = numeric.split(".", 1)[0]
    return NUMERIC_ANSWER_KEYS.get(numeric, raw)


def paragraph(value):
    return f"<p>{html.escape(value).replace(chr(10), '<br>')}</p>"


def choice_cards_from_rows(rows, *, context, id_prefix, start_index):
    cards = []
    for row in rows[1:]:
        question = row[0].strip() if len(row) > 0 else ""
        options = [row[index].strip() if len(row) > index else "" for index in range(1, 5)]
        answer_key = normalize_answer_key(row[5] if len(row) > 5 else "")
        if not question and not any(options) and not answer_key:
            continue
        if not question or not all(options) or answer_key not in ANSWER_KEYS:
            continue

        card_number = len(cards) + 1
        display_options = [strip_option_prefix(option) for option in options]
        text = "\n".join(
            [question, *[f"{chr(65 + index)}. {option}" for index, option in enumerate(display_options)]]
        )
        cards.append(
            {
                "id": f"{id_prefix}_{card_number:04d}",
                "index": start_index + card_number,
                "title": f"Câu {card_number}:",
                "context": context,
                "type": "choice",
                "question": question,
                "text": text,
                "options": display_options,
                "answerKey": answer_key,
                "answerIndex": ANSWER_KEYS[answer_key],
                "frontHtml": paragraph(question),
                "originalHtml": paragraph(text),
            }
        )
    return cards


def main():
    parser = argparse.ArgumentParser(description="Append XLSX multiple-choice questions to quiz data.")
    parser.add_argument("xlsx", type=Path, help="Path to the source .xlsx file")
    parser.add_argument("-o", "--output", type=Path, default=Path("data/cards.json"), help="Quiz JSON output")
    parser.add_argument("--sheet", default="Sheet1", help="Worksheet name")
    parser.add_argument("--context", default="Commercial Banking 3 - Cuối kỳ 01", help="Quiz context/chapter label")
    parser.add_argument("--id-prefix", default="cb3_final", help="ID prefix for imported cards")
    args = parser.parse_args()

    if not args.xlsx.exists():
        raise SystemExit(f"Cannot find XLSX file: {args.xlsx}")
    if not args.output.exists():
        raise SystemExit(f"Cannot find existing quiz data: {args.output}")

    payload = json.loads(args.output.read_text(encoding="utf-8"))
    existing_cards = [
        card for card in payload.get("cards", []) if not str(card.get("id", "")).startswith(f"{args.id_prefix}_")
    ]
    rows = load_rows(args.xlsx, args.sheet)
    imported_cards = choice_cards_from_rows(
        rows,
        context=args.context,
        id_prefix=args.id_prefix,
        start_index=len(existing_cards),
    )

    payload["cards"] = existing_cards + imported_cards
    payload["cardCount"] = len(payload["cards"])
    sources = payload.get("sources")
    if not isinstance(sources, list):
        sources = [payload.get("source")] if payload.get("source") else []
    source = str(args.xlsx)
    if source not in sources:
        sources.append(source)
    payload["sources"] = sources

    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    args.output.write_text(json_text, encoding="utf-8")
    args.output.with_suffix(".js").write_text(f"window.QUIZ_DATA = {json_text};\n", encoding="utf-8")
    print(f"Imported {len(imported_cards)} cards from {args.xlsx}")
    print(f"Wrote {len(payload['cards'])} cards to {args.output} and {args.output.with_suffix('.js')}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
