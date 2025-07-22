FROM --platform=linux/amd64 python:3.10-slim

WORKDIR /app

# Install system dependencies (for PyMuPDF)
RUN apt-get update && apt-get install -y \
    libmupdf-dev build-essential \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy code & schema
COPY app/process_pdfs.py .
COPY app/schema/ ./schema/

# Install Python dependencies
RUN pip install --no-cache-dir PyMuPDF jsonschema

# Command to run script
CMD ["python", "process_pdfs.py"]