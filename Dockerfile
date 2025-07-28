FROM --platform=linux/amd64 python:3.10-slim

WORKDIR /app

# Install system dependencies (for PyMuPDF)
RUN apt-get update && apt-get install -y \
    libmupdf-dev build-essential \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Copy code & schema
COPY process_pdfs.py .
COPY sample_dataset/schema/ ./schema/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Command to run script
CMD ["python", "process_pdfs.py"]