"""
OCR text parser for structured invoice field extraction.

Parses raw Tesseract OCR text into structured invoice fields using
regex patterns and heuristics. Each extracted field gets a confidence
score based on pattern match quality.

This module powers the "OCR-first" pipeline: extract what we can from
OCR, then let the LLM fill gaps and validate.
"""

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ParsedField:
    """A single extracted field with value and confidence."""
    value: str | float | None
    confidence: int  # 0-100
    source: str = "ocr"  # "ocr" or "missing"


@dataclass
class ParsedItem:
    """A partially-parsed line item from OCR."""
    name: str = ""
    quantity: float | None = None
    unit: str = ""
    unit_price: float | None = None
    total: float | None = None
    confidence: int = 0


@dataclass
class OCRParseResult:
    """Structured result from parsing OCR text."""
    supplier: ParsedField = field(default_factory=lambda: ParsedField(None, 0, "missing"))
    invoice_number: ParsedField = field(default_factory=lambda: ParsedField(None, 0, "missing"))
    date: ParsedField = field(default_factory=lambda: ParsedField(None, 0, "missing"))
    subtotal: ParsedField = field(default_factory=lambda: ParsedField(None, 0, "missing"))
    tax: ParsedField = field(default_factory=lambda: ParsedField(None, 0, "missing"))
    total: ParsedField = field(default_factory=lambda: ParsedField(None, 0, "missing"))
    items: list[ParsedItem] = field(default_factory=list)
    raw_text: str = ""

    def to_dict(self) -> dict:
        """Convert to a dict summary for embedding in an LLM prompt."""
        result = {}
        for fname in ("supplier", "invoice_number", "date", "subtotal", "tax", "total"):
            pf: ParsedField = getattr(self, fname)
            if pf.value is not None and pf.confidence > 0:
                result[fname] = {"value": pf.value, "confidence": pf.confidence}
        if self.items:
            result["items"] = []
            for item in self.items:
                d = {"name": item.name}
                if item.quantity is not None:
                    d["quantity"] = item.quantity
                if item.unit:
                    d["unit"] = item.unit
                if item.unit_price is not None:
                    d["unit_price"] = item.unit_price
                if item.total is not None:
                    d["total"] = item.total
                d["confidence"] = item.confidence
                result["items"].append(d)
        return result

    def fields_needing_llm(self) -> list[str]:
        """Return field names that are missing or low-confidence (<60)."""
        needs = []
        for fname in ("supplier", "invoice_number", "date", "subtotal", "tax", "total"):
            pf: ParsedField = getattr(self, fname)
            if pf.value is None or pf.confidence < 60:
                needs.append(fname)
        # Items always need LLM help for numeric columns
        if not self.items or any(
            i.quantity is None or i.unit_price is None or i.total is None
            for i in self.items
        ):
            needs.append("items")
        return needs


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Invoice number patterns
_INVOICE_NUM_PATTERNS = [
    # "Invoice #: X", "Invoice No: X", "Invoice Number: X"
    re.compile(r"invoice\s*(?:#|no\.?|number)\s*[:.]?\s*([A-Z0-9][\w\-/]+)", re.IGNORECASE),
    # "INV-12345", "INV12345"
    re.compile(r"\b(INV[\-]?\d{3,})\b", re.IGNORECASE),
    # Standalone pattern near "INVOICE" keyword — alphanumeric code
    re.compile(r"INVOICE\s+.*?([A-Z]\d{5,})", re.IGNORECASE),
    # Generic: hash followed by alphanumeric
    re.compile(r"#\s*([A-Z0-9][\w\-]{4,})", re.IGNORECASE),
]

# Date patterns
_DATE_PATTERNS = [
    # MM/DD/YYYY or MM-DD-YYYY
    re.compile(r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\b"),
    # YYYY-MM-DD (ISO)
    re.compile(r"\b(\d{4}[/\-]\d{1,2}[/\-]\d{1,2})\b"),
    # "Date: ..." context
    re.compile(r"date\s*[:.]?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", re.IGNORECASE),
    # Month name formats: "Jan 15, 2025"
    re.compile(
        r"\b(\w{3,9}\s+\d{1,2},?\s+\d{4})\b",
    ),
]

# Total/subtotal/tax patterns
_MONEY_PATTERN = re.compile(r"\$?\s*([\d,]+\.\d{2})\b")

_TOTAL_PATTERNS = [
    re.compile(r"(?:grand\s+)?total\s*[:.]?\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE),
]
_SUBTOTAL_PATTERNS = [
    re.compile(r"sub\s*total\s*[:.]?\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE),
]
_TAX_PATTERNS = [
    re.compile(r"(?:sales\s+)?tax\s*[:.]?\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Parsing functions
# ---------------------------------------------------------------------------

def _parse_money(s: str) -> float | None:
    """Parse a money string like '1,234.56' into a float."""
    try:
        return float(s.replace(",", ""))
    except (ValueError, TypeError):
        return None


def _extract_supplier(lines: list[str]) -> ParsedField:
    """
    Extract supplier name from the first ~10 lines of OCR text.

    Heuristic: Look for a line that looks like a company name
    (contains Inc, LLC, Corp, Co., Ltd, or is a prominent multi-word line
    near the top that isn't an address).
    """
    company_suffixes = re.compile(
        r"\b(Inc\.?|LLC|Corp\.?|Co\.?|Ltd\.?|Company|Imports?|Import,?\s+Inc|"
        r"Distribution|Distributors?|Supply|Supplies|Foods?|Wholesale)\b",
        re.IGNORECASE,
    )

    # Search first 15 lines for company-like names
    for line in lines[:15]:
        stripped = line.strip()
        if not stripped or len(stripped) < 3:
            continue
        if company_suffixes.search(stripped):
            # Clean up the line
            name = stripped.strip()
            # Remove leading/trailing punctuation noise from OCR
            name = re.sub(r"^[^A-Za-z]+", "", name)
            name = re.sub(r"[^A-Za-z.)]+$", "", name)
            if len(name) >= 3:
                return ParsedField(value=name, confidence=75, source="ocr")

    return ParsedField(value=None, confidence=0, source="missing")


def _extract_invoice_number(text: str) -> ParsedField:
    """Extract invoice number using regex patterns."""
    for pattern in _INVOICE_NUM_PATTERNS:
        m = pattern.search(text)
        if m:
            value = m.group(1).strip()
            # Higher confidence if it has a clear prefix letter + digits
            if re.match(r"^[A-Z]\d+$", value):
                return ParsedField(value=value, confidence=80, source="ocr")
            return ParsedField(value=value, confidence=65, source="ocr")
    return ParsedField(value=None, confidence=0, source="missing")


def _extract_date(text: str) -> ParsedField:
    """Extract date using regex patterns."""
    for pattern in _DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            value = m.group(1).strip()
            # Basic validation: should have digits
            if any(c.isdigit() for c in value):
                return ParsedField(value=value, confidence=70, source="ocr")
    return ParsedField(value=None, confidence=0, source="missing")


def _extract_totals(text: str) -> tuple[ParsedField, ParsedField, ParsedField]:
    """Extract subtotal, tax, and total from OCR text."""
    subtotal = ParsedField(value=None, confidence=0, source="missing")
    tax = ParsedField(value=None, confidence=0, source="missing")
    total = ParsedField(value=None, confidence=0, source="missing")

    for pattern in _SUBTOTAL_PATTERNS:
        m = pattern.search(text)
        if m:
            val = _parse_money(m.group(1))
            if val is not None:
                subtotal = ParsedField(value=val, confidence=70, source="ocr")
                break

    for pattern in _TAX_PATTERNS:
        m = pattern.search(text)
        if m:
            val = _parse_money(m.group(1))
            if val is not None:
                tax = ParsedField(value=val, confidence=70, source="ocr")
                break

    for pattern in _TOTAL_PATTERNS:
        m = pattern.search(text)
        if m:
            val = _parse_money(m.group(1))
            if val is not None:
                total = ParsedField(value=val, confidence=70, source="ocr")
                break

    return subtotal, tax, total


def _extract_items(lines: list[str]) -> list[ParsedItem]:
    """
    Extract line items from OCR text.

    Looks for lines that contain product descriptions — typically lines
    with both text words and numbers that look like quantities/prices.
    This is a best-effort extraction; the LLM will refine it.
    """
    items = []

    # Pattern: a line with a product name followed by numbers
    # e.g., "Case Sapporo Light 120z DP (4/6/355ml)"
    # or "2  Sapporo Light  12.50  25.00"
    item_line_pattern = re.compile(
        r"^(\d+)?\s*(.{5,}?)\s+(\d+\.?\d*)\s+(\d+\.?\d*)$"
    )

    # Simpler: just find lines that look like product names
    product_keywords = re.compile(
        r"\b(case|bottle|can|pack|box|bag|lb|kg|oz|gallon|each|ea)\b",
        re.IGNORECASE,
    )

    for line in lines:
        stripped = line.strip()
        if not stripped or len(stripped) < 5:
            continue

        # Try structured pattern first
        m = item_line_pattern.match(stripped)
        if m:
            item = ParsedItem(
                name=m.group(2).strip(),
                quantity=float(m.group(1)) if m.group(1) else None,
                confidence=50,
            )
            items.append(item)
            continue

        # Fallback: lines with product keywords
        if product_keywords.search(stripped):
            # Looks like a product line — extract the name part
            # Remove leading numbers that might be item codes
            name = re.sub(r"^\d+\s+", "", stripped)
            # Remove trailing numbers (prices)
            name = re.sub(r"\s+[\d$.]+\s*$", "", name)
            if len(name) >= 3:
                item = ParsedItem(name=name.strip(), confidence=40)
                items.append(item)

    return items


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def parse_ocr_text(ocr_text: str) -> OCRParseResult:
    """
    Parse raw OCR text into structured invoice fields.

    Args:
        ocr_text: Raw text from Tesseract OCR.

    Returns:
        OCRParseResult with extracted fields and confidence scores.
    """
    if not ocr_text or not ocr_text.strip():
        return OCRParseResult(raw_text="")

    lines = ocr_text.split("\n")
    text = ocr_text

    supplier = _extract_supplier(lines)
    invoice_number = _extract_invoice_number(text)
    date = _extract_date(text)
    subtotal, tax, total = _extract_totals(text)
    items = _extract_items(lines)

    return OCRParseResult(
        supplier=supplier,
        invoice_number=invoice_number,
        date=date,
        subtotal=subtotal,
        tax=tax,
        total=total,
        items=items,
        raw_text=ocr_text,
    )
