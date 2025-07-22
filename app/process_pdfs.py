import os
import json
import time
from pathlib import Path
import fitz  # PyMuPDF
from jsonschema import validate, ValidationError

# Load schema once at startup
SCHEMA_PATH = Path("app/schema/output_schema.json")
SCHEMA = {}
if SCHEMA_PATH.exists():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        SCHEMA = json.load(f)

def extract_outline(pdf_path):
    doc = fitz.open(pdf_path)
    font_stats = {}
    blocks_per_page = []

    for page_num, page in enumerate(doc, start=1):
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span["text"].strip()
                    size = round(span["size"], 1)
                    if not text or len(text) < 3:
                        continue
                    font_stats[size] = font_stats.get(size, 0) + 1
                    blocks_per_page.append({
                        "text": text,
                        "size": size,
                        "page": page_num
                    })

    # Map largest fonts to H1–H4
    font_sizes = sorted(font_stats.keys(), reverse=True)
    level_map = {size: f"H{i+1}" for i, size in enumerate(font_sizes[:4])}

    # Guess title (largest font, page 1)
    title = next((b["text"] for b in blocks_per_page
                  if b["page"] == 1 and b["size"] == font_sizes[0]), "")

    outline = []
    for block in blocks_per_page:
        level = level_map.get(block["size"])
        if level:
            outline.append({
                "level": level,
                "text": block["text"],
                "page": block["page"]
            })

    return {
        "title": title.strip(),
        "outline": outline
    }

def validate_output(data):
    """Validate against JSON schema."""
    try:
        validate(instance=data, schema=SCHEMA)
        return True
    except ValidationError as e:
        print(f"❌ Schema Validation Error: {e.message}")
        return False

def process_pdfs():
    input_dir = Path("input")
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = [f for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
    print(f"Found {len(pdf_files)} PDF(s) for processing.")

    total_start_time = time.time()
    total_pages_processed = 0

    for pdf_file in pdf_files:
        print("\n==============================")
        print(f"Processing: {pdf_file.name}")

        start = time.time()
        try:
            data = extract_outline(pdf_file)
            duration = time.time() - start

            # Save JSON
            output_file = output_dir / f"{pdf_file.stem}.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Validation
            valid = validate_output(data)
            pages = len(fitz.open(pdf_file))
            total_pages_processed += pages

            print(f"✅ Pages: {pages}")
            print(f"✅ Processing Time: {duration:.2f} sec")
            print(f"✅ JSON Validation: {'PASS' if valid else 'FAIL'}")
            print(f"✅ Output Saved: {output_file.name} ({output_file.stat().st_size / 1024:.2f} KB)")

            if duration > 10:
                print("⚠️ WARNING: Exceeded 10s processing requirement!")
        except Exception as e:
            print(f"❌ Error processing {pdf_file.name}: {e}")

    total_time = time.time() - total_start_time
    print("\n==============================")
    print(f"✅ All PDFs Processed in {total_time:.2f} sec")
    print(f"✅ Total Pages Processed: {total_pages_processed}")
    print(f"✅ Avg Time per PDF: {total_time / max(len(pdf_files),1):.2f} sec")
    if total_time > 10:
        print("⚠️ WARNING: Might fail the 10s/50-pages requirement.")
    print("==============================")

if __name__ == "__main__":
    print("Starting PDF processing...")
    process_pdfs()
    print("Completed all processing.")
