"""
Helpers for integration tests.

Provides:
- make_receipt_image_bytes(): synthetic PIL image as PNG bytes
- make_claude_response(): builds a JSON string matching engine expectations
"""

import io
import json

from PIL import Image, ImageDraw


def make_receipt_image_bytes(
    text_lines: list[str] | None = None,
    width: int = 400,
    height: int = 600,
) -> bytes:
    """Create a synthetic receipt-like PNG image.

    Draws white background with black text lines. Does not require
    Tesseract to parse -- used only to feed the pipeline's image-open step.

    Args:
        text_lines: Lines of text to draw. Defaults to a generic receipt.
        width: Image width in pixels.
        height: Image height in pixels.

    Returns:
        PNG bytes.
    """
    if text_lines is None:
        text_lines = [
            "FRESH FOODS INC",
            "123 Market Street",
            "Invoice: INV-1234",
            "Date: 2026-03-15",
            "",
            "Organic Tomatoes  5 kg  $3.50  $17.50",
            "Fresh Basil       2 bch $2.00  $4.00",
            "",
            "Subtotal: $21.50",
            "Tax (10%): $2.15",
            "Total: $23.65",
        ]

    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)

    # Use default bitmap font (always available, no TTF required)
    y = 10
    for line in text_lines:
        draw.text((10, y), line, fill="black")
        y += 20

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_claude_response(
    supplier: str = "Fresh Foods Inc.",
    date: str = "2026-03-15",
    invoice_number: str = "INV-1234",
    items: list[dict] | None = None,
    subtotal: float | None = 21.50,
    tax: float | None = 2.15,
    total: float | None = 23.65,
    confidence_override: dict | None = None,
    inference_sources_override: dict | None = None,
) -> str:
    """Build a JSON string matching the schema scan_invoice() expects from Claude.

    This is used as the return value of the mocked _call_claude().

    Args:
        supplier: Supplier name.
        date: Invoice date (YYYY-MM-DD).
        invoice_number: Invoice number string.
        items: Line items list. Defaults to two standard items.
        subtotal: Invoice subtotal.
        tax: Tax amount.
        total: Invoice total.
        confidence_override: Override specific confidence values.
        inference_sources_override: Override specific inference_sources values.

    Returns:
        JSON string.
    """
    if items is None:
        items = [
            {
                "name": "Organic Tomatoes",
                "quantity": 5,
                "unit": "kg",
                "unit_price": 3.50,
                "total": 17.50,
                "confidence": 92,
            },
            {
                "name": "Fresh Basil",
                "quantity": 2,
                "unit": "bunch",
                "unit_price": 2.00,
                "total": 4.00,
                "confidence": 88,
            },
        ]

    confidence = {
        "supplier": 95,
        "date": 90,
        "invoice_number": 85,
        "subtotal": 88,
        "tax": 80,
        "total": 92,
    }
    if confidence_override:
        confidence.update(confidence_override)

    inference_sources = {
        "supplier": "scanned",
        "date": "scanned",
        "invoice_number": "scanned",
        "subtotal": "scanned",
        "tax": "scanned",
        "total": "scanned",
    }
    if inference_sources_override:
        inference_sources.update(inference_sources_override)

    payload = {
        "supplier": supplier,
        "date": date,
        "invoice_number": invoice_number,
        "items": items,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "confidence": confidence,
        "inference_sources": inference_sources,
    }
    return json.dumps(payload)
