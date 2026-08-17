# Smart P&ID Instrument Detector

Production-ready Streamlit app for processing P&ID PDFs into a structured instrument register with visual overlays and AI-assisted line-number mapping.

## Features

- PDF upload and cached processing by file hash.
- PDF rendering, tiled YOLO detection, global NMS, OCR, tag extraction, and regex-based PDF text line extraction.
- Structured dataframe with tag, type, confidence, bounding box, page, and associated line number.
- Full P&ID drawing viewer with instrument overlays.
- Instrument counts by type, type filtering, multi-selection, and row-hover highlighting with blinking line markers.
- Modular architecture for future AI P&ID querying.

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Add configuration in `.streamlit/secrets.toml` locally:

```toml
YOLO_MODEL_PATH = "best.pt"
```

On Streamlit Cloud, the YOLO weights are expected at `best.pt`, matching the uploaded model file in this repository.

3. Run:

```bash
streamlit run app.py
```

## Notes

- `YOLO_MODEL_PATH` is required for detection.
- Processing high-resolution P&IDs can be CPU and memory intensive on Streamlit Cloud. Tune `PID_ZOOM`, `PID_GRID`, `PID_OVERLAP`, and `OCR_SCALE` in environment variables or Streamlit secrets as needed.
