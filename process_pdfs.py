import os
import json
from pathlib import Path

def process_pdfs():
    # Get input and output directories
    input_dir = Path("/app/input")
    output_dir = Path("/app/output")
    
    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Get all PDF files
    pdf_files = list(input_dir.glob("*.pdf"))
    
    for pdf_file in pdf_files:
        # Create dummy JSON data
        dummy_data = {
            "title": "Understanding AI",
            "outline": [
                {
                    "level": "H1",
                    "text": "Introduction",
                    "page": 1
                },
                {
                    "level": "H2",
                    "text": "What is AI?",
                    "page": 2
                },
                {
                    "level": "H3",
                    "text": "History of AI",
                    "page": 3
                }
            ]
        }
        
        # Create output JSON file
        output_file = output_dir / f"{pdf_file.stem}.json"
        with open(output_file, "w") as f:
            json.dump(dummy_data, f, indent=2)
        
        print(f"Processed {pdf_file.name} -> {output_file.name}")

if __name__ == "__main__":
    print("Starting processing pdfs")
    process_pdfs() 
    print("completed processing pdfs")