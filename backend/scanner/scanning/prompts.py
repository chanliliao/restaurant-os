"""
Prompt templates for invoice scanning with Claude.

Builds structured prompts that instruct Claude to extract invoice data
from images and return JSON with confidence scores and inference sources.
"""


def build_scan_prompt(ocr_text: str = "") -> str:
    """
    Build the prompt for single-pass invoice scanning.

    Args:
        ocr_text: Supplementary OCR text extracted by Tesseract pre-pass.
            May be empty if OCR was unavailable or failed.

    Returns:
        Prompt string to send to Claude along with invoice images.
    """
    ocr_section = ""
    if ocr_text.strip():
        ocr_section = (
            "\n\n## Supplementary OCR Text\n"
            "The following text was extracted from the invoice via OCR pre-pass. "
            "Use it as supplementary data to cross-reference with what you see "
            "in the images. The OCR may contain errors — trust the images as the "
            "primary source.\n\n"
            f"```\n{ocr_text.strip()}\n```"
        )

    prompt = f"""You are an expert invoice data extraction system for restaurant suppliers.

## Task
Extract structured data from the provided invoice image(s). You are given two image variants:
1. The original image (orientation-corrected only)
2. A preprocessed image (contrast-enhanced, denoised, grayscale)

Use both images together to maximize extraction accuracy.

## Instructions
- Extract every field listed in the output schema below.
- For each top-level field, provide a confidence score from 0 to 100.
- For each top-level field, provide an inference_source:
  - "scanned" — the value was clearly read from the invoice
  - "inferred" — the value was deduced from context (e.g., subtotal calculated from items)
  - "missing" — the field could not be found or determined
- For line items, include a per-item confidence score.
- Use null for numeric fields that cannot be determined.
- Use empty string for text fields that cannot be determined.
- Dates should be in ISO format (YYYY-MM-DD) when possible.
- Currency values should be plain numbers without currency symbols.
- Respond ONLY with valid JSON — no markdown fences, no explanation.
{ocr_section}

## Required JSON Output Schema
{{
    "supplier": "string — supplier/vendor name",
    "date": "string — invoice date in YYYY-MM-DD format",
    "invoice_number": "string — invoice or receipt number",
    "items": [
        {{
            "name": "string — item description",
            "quantity": 0,
            "unit": "string — unit of measure (ea, kg, lb, case, etc.)",
            "unit_price": 0.00,
            "total": 0.00,
            "confidence": 0
        }}
    ],
    "subtotal": 0.00,
    "tax": 0.00,
    "total": 0.00,
    "confidence": {{
        "supplier": 0,
        "date": 0,
        "invoice_number": 0,
        "subtotal": 0,
        "tax": 0,
        "total": 0
    }},
    "inference_sources": {{
        "supplier": "scanned|inferred|missing",
        "date": "scanned|inferred|missing",
        "invoice_number": "scanned|inferred|missing",
        "subtotal": "scanned|inferred|missing",
        "tax": "scanned|inferred|missing",
        "total": "scanned|inferred|missing"
    }}
}}"""
    return prompt
