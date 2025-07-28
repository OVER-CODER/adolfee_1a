import os
import json
import time
import re
from pathlib import Path
import fitz  # PyMuPDF
from jsonschema import validate, ValidationError
from itertools import groupby
from collections import Counter, defaultdict

# Load schema once at startup - try multiple possible paths
SCHEMA = {}
possible_schema_paths = [
    Path("schema/output_schema.json"),        # Docker container path
    Path("sample_dataset/schema/output_schema.json"),    # Local development path
    Path("/app/schema/output_schema.json")    # Absolute container path
]

for schema_path in possible_schema_paths:
    if schema_path.exists():
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                SCHEMA = json.load(f)
            break
        except Exception as e:
            continue
else:
    pass  # Schema validation will be skipped

def clean_text(text):
    """Clean and normalize text."""
    if not text:
        return ""
    
    # Remove excessive whitespace and normalize
    text = re.sub(r'\s+', ' ', text.strip())
    
    # Remove common artifacts
    text = re.sub(r'[^\w\s\-\.\,\:\;\!\?\(\)\[\]\/\"\'&]', '', text)
    
    return text

def is_likely_heading(text, font_size, is_bold, avg_font_size, doc_stats):
    """Determine if text is likely a heading based on multiple criteria."""
    if not text or len(text.strip()) < 3:
        return False
    
    # Filter out very long texts (likely paragraphs)
    if len(text.split()) > 20:
        return False
    
    # Filter out texts with too many numbers (likely data/tables)
    number_ratio = len(re.findall(r'\d', text)) / len(text)
    if number_ratio > 0.3:
        return False
    
    # Check font size criteria
    size_threshold = avg_font_size * 1.1  # At least 10% larger than average
    is_large_font = font_size >= size_threshold
    
    # Check if it's significantly larger than body text
    is_significantly_larger = font_size >= avg_font_size * 1.3
    
    # Common heading patterns
    heading_patterns = [
        r'^(\d+\.?\s*)+',  # Numbered sections (1. 1.1 etc.)
        r'^[A-Z][A-Z\s]{2,}$',  # ALL CAPS short text
        r'^(Chapter|Section|Part|Appendix)\s+\d+',  # Chapter/Section patterns
        r'^[IVX]+\.\s+',  # Roman numerals
        r'^\w+\s*:$',  # Single word followed by colon
    ]
    
    has_heading_pattern = any(re.match(pattern, text.strip()) for pattern in heading_patterns)
    
    # Title case pattern (Most Words Capitalized)
    words = text.split()
    if len(words) >= 2:
        capitalized_words = sum(1 for word in words if word and word[0].isupper())
        is_title_case = capitalized_words / len(words) >= 0.7
    else:
        is_title_case = False
    
    # Score-based decision
    score = 0
    if is_large_font: score += 2
    if is_significantly_larger: score += 2
    if is_bold: score += 2
    if has_heading_pattern: score += 3
    if is_title_case: score += 1
    if len(text.split()) <= 8: score += 1  # Prefer shorter headings
    
    return score >= 3

def extract_font_statistics(doc):
    """Extract font statistics from the document."""
    font_sizes = []
    font_counts = Counter()
    
    for page in doc:
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if text and len(text) > 2:
                        size = round(span["size"], 1)
                        font = span.get("font", "")
                        font_sizes.append(size)
                        font_counts[(size, font)] += len(text)
    
    avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else 12
    most_common_font = font_counts.most_common(1)[0][0] if font_counts else (12, "")
    
    return {
        "avg_font_size": avg_font_size,
        "most_common_font": most_common_font,
        "all_sizes": sorted(set(font_sizes), reverse=True)
    }

def determine_heading_levels(headings, font_stats):
    """Assign hierarchical levels to headings based on font sizes and patterns."""
    if not headings:
        return []
    
    # Group by font size and analyze patterns
    size_groups = defaultdict(list)
    for heading in headings:
        size_groups[heading["size"]].append(heading)
    
    # Sort sizes in descending order
    sorted_sizes = sorted(size_groups.keys(), reverse=True)
    
    # Assign levels based on size hierarchy
    level_map = {}
    level_counter = 1
    
    for size in sorted_sizes:
        if level_counter <= 6:  # Limit to H1-H6
            level_map[size] = f"H{level_counter}"
            level_counter += 1
    
    # Apply levels to headings
    for heading in headings:
        heading["level"] = level_map.get(heading["size"], "H6")
    
    return headings

def extract_title_from_pdf(doc):
    """Extract title using multiple strategies."""
    # Strategy 1: Use document metadata
    metadata_title = doc.metadata.get('title', '').strip()
    if metadata_title and len(metadata_title) > 3:
        return clean_text(metadata_title)
    
    # Strategy 2: Find largest text on first page
    first_page = doc[0]
    blocks = first_page.get_text("dict")["blocks"]
    
    candidates = []
    for block in blocks:
        if "lines" not in block:
            continue
        
        for line in block["lines"]:
            for span in line["spans"]:
                text = clean_text(span["text"])
                if text and len(text.split()) >= 2 and len(text) >= 10:  # Reasonable title length
                    candidates.append({
                        "text": text,
                        "size": span["size"],
                        "y": line["bbox"][1],  # Y position
                        "bold": "Bold" in span.get("font", "")
                    })
    
    if not candidates:
        return "Untitled Document"
    
    # Sort by font size (descending) and Y position (ascending - higher on page)
    candidates.sort(key=lambda x: (-x["size"], x["y"]))
    
    # Filter out very similar texts (OCR duplicates)
    filtered_candidates = []
    for candidate in candidates:
        is_duplicate = False
        for existing in filtered_candidates:
            if abs(candidate["y"] - existing["y"]) < 10:  # Same line
                if candidate["text"].lower() in existing["text"].lower() or existing["text"].lower() in candidate["text"].lower():
                    is_duplicate = True
                    break
        if not is_duplicate:
            filtered_candidates.append(candidate)
    
    # Return the top candidate
    if filtered_candidates:
        return filtered_candidates[0]["text"]
    
    return "Untitled Document"

def extract_outline(pdf_path):
    """Extract document outline with improved heading detection."""
    try:
        doc = fitz.open(pdf_path)
        text_blocks = []
        
        # Get font statistics for the entire document
        font_stats = extract_font_statistics(doc)
        avg_font_size = font_stats["avg_font_size"]
        
        # Extract text blocks with detailed font information
        for page_num, page in enumerate(doc, start=1):
            blocks = page.get_text("dict")["blocks"]
            
            for block in blocks:
                if "lines" not in block:
                    continue
                    
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = clean_text(span["text"])
                        if not text or len(text) < 3:
                            continue
                        
                        # Extract font properties
                        font_name = span.get("font", "")
                        is_bold = "Bold" in font_name or "bold" in font_name.lower()
                        is_italic = "Italic" in font_name or "italic" in font_name.lower()
                        font_size = round(span["size"], 1)
                        
                        text_blocks.append({
                            "text": text,
                            "page": page_num,
                            "x": line["bbox"][0],
                            "y": line["bbox"][1],
                            "size": font_size,
                            "font": font_name,
                            "bold": is_bold,
                            "italic": is_italic,
                            "flags": span.get("flags", 0)
                        })
        # Filter potential headings
        headings = []
        for block in text_blocks:
            if is_likely_heading(
                block["text"], 
                block["size"], 
                block["bold"], 
                avg_font_size, 
                font_stats
            ):
                headings.append(block)
        
        # Assign hierarchical levels
        headings_with_levels = determine_heading_levels(headings, font_stats)
        
        # Sort by page and position
        headings_with_levels.sort(key=lambda x: (x["page"], x["y"]))
        
        # Extract title
        title = extract_title_from_pdf(doc)
        
        # Format output
        outline = []
        for heading in headings_with_levels:
            outline.append({
                "level": heading["level"],
                "text": heading["text"],
                "page": heading["page"]
            })
        
        doc.close()
        
        return {
            "title": title,
            "outline": outline
        }
        
    except Exception as e:
        return {
            "title": "Error Processing Document",
            "outline": []
        }

def validate_output(data):
    """Validate against JSON schema."""
    if not SCHEMA:
        return True  # Skip validation if no schema
    
    try:
        validate(instance=data, schema=SCHEMA)
        return True
    except ValidationError as e:
        return False

def process_pdfs():
    """Main processing function with enhanced performance and error handling."""
    input_dir = Path("/app/input") if Path("/app/input").exists() else Path("./sample_dataset/pdfs")
    output_dir = Path("/app/output") if Path("/app/output").exists() else Path("./sample_dataset/outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = [f for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]

    total_start_time = time.time()
    total_pages_processed = 0
    successful_files = 0
    failed_files = 0

    for pdf_file in pdf_files:
        start = time.time()
        try:
            # Extract outline data
            data = extract_outline(pdf_file)
            duration = time.time() - start

            # Save JSON with proper formatting
            output_file = output_dir / f"{pdf_file.stem}.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Get page count for reporting
            try:
                with fitz.open(pdf_file) as doc:
                    pages = len(doc)
            except:
                pages = 0
            
            total_pages_processed += pages

            # Validation
            valid = validate_output(data)
            
            successful_files += 1

        except Exception as e:
            failed_files += 1
            
            # Create minimal output for failed files
            try:
                output_file = output_dir / f"{pdf_file.stem}.json"
                error_data = {
                    "title": f"Error Processing: {pdf_file.name}",
                    "outline": []
                }
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(error_data, f, indent=2, ensure_ascii=False)
            except:
                pass

    # Final summary - keeping minimal output for completion status
    total_time = time.time() - total_start_time

if __name__ == "__main__":
    process_pdfs()
