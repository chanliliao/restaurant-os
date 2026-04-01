"""
OCR text parser for structured invoice field extraction.

Parses raw OCR text (Tesseract plain text OR GLM-OCR HTML/markdown) into
structured invoice fields using regex patterns and heuristics. Each extracted
field gets a confidence score based on pattern match quality.

This module powers the "OCR-first" pipeline: extract what we can from
OCR, then let the LLM fill gaps and validate.
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

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
# HTML table parsing (for GLM-OCR output)
# ---------------------------------------------------------------------------

class _TableParser(HTMLParser):
    """Extract rows from HTML <table> elements.

    Handles colspan by padding cells with empty strings so that column
    indices in header rows align with data rows.
    """

    def __init__(self):
        super().__init__()
        self.tables: list[list[list[str]]] = []  # tables → rows → cells
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: str = ""
        self._in_cell: bool = False
        self._current_colspan: int = 1

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table":
            self._current_table = []
        elif tag == "tr":
            self._current_row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._current_cell = ""
            try:
                self._current_colspan = int(attrs_dict.get("colspan", 1))
            except (ValueError, TypeError):
                self._current_colspan = 1

    def handle_endtag(self, tag):
        if tag == "table":
            if self._current_table:
                self.tables.append(self._current_table)
            self._current_table = []
        elif tag == "tr":
            if self._current_row:
                self._current_table.append(self._current_row)
            self._current_row = []
        elif tag in ("td", "th"):
            text = self._current_cell.strip()
            self._current_row.append(text)
            # Expand colspan: add empty cells for columns 2..colspan
            for _ in range(self._current_colspan - 1):
                self._current_row.append("")
            self._in_cell = False
            self._current_colspan = 1

    def handle_data(self, data):
        if self._in_cell:
            self._current_cell += data

    def handle_entityref(self, name):
        if self._in_cell:
            entities = {"amp": "&", "lt": "<", "gt": ">", "nbsp": " ", "quot": '"'}
            self._current_cell += entities.get(name, "")

    def handle_charref(self, name):
        if self._in_cell:
            try:
                if name.startswith("x"):
                    self._current_cell += chr(int(name[1:], 16))
                else:
                    self._current_cell += chr(int(name))
            except (ValueError, OverflowError):
                pass


def _normalize_header(s: str) -> str:
    """Normalize a column header for matching."""
    return re.sub(r"[\s/\-_]+", " ", s).lower().strip()


# Flexible column header → field name mapping
_COL_MAP: list[tuple[list[str], str]] = [
    (["description", "item desc", "item description", "package description",
      "product", "item name", "desc"], "name"),
    (["qty each", "qty. each", "quantity each", "each qty"], "quantity_each"),
    (["qty case", "qty. case", "quantity case", "case qty", "cs"], "quantity_case"),
    (["qty", "quantity", "pcs", "count"], "quantity"),
    (["unit price", "unit pr", "each price", "price ea", "unit pr(ea)"], "unit_price"),
    (["amount", "total", "ext", "extended", "total amt", "line total"], "amount"),
    (["uom", "unit", "um"], "unit"),
    (["pack", "package"], "pack"),
]


def _map_columns(header_row: list[str]) -> dict[str, int]:
    """Map column indices from a header row. Returns field_name → col_index."""
    mapping: dict[str, int] = {}
    for col_idx, cell in enumerate(header_row):
        norm = _normalize_header(cell)
        if not norm:
            continue
        for keywords, field_name in _COL_MAP:
            if field_name in mapping:
                continue
            if any(kw in norm for kw in keywords):
                mapping[field_name] = col_idx
                break
    return mapping


def _cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return row[idx].strip()


def _extract_items_from_html_tables(text: str) -> list[ParsedItem]:
    """
    Parse HTML tables from GLM-OCR output and extract line items.

    Returns a list of ParsedItem. Confidence is set to 70 (higher than
    Tesseract regex fallback of 40-50) because HTML table structure is reliable.
    """
    if "<table" not in text.lower():
        return []

    parser = _TableParser()
    try:
        parser.feed(text)
    except Exception:
        return []

    items: list[ParsedItem] = []

    for table_rows in parser.tables:
        if len(table_rows) < 2:
            continue

        # Find header row — first row that contains column-like keywords
        header_idx = None
        for i, row in enumerate(table_rows):
            norm = " ".join(_normalize_header(c) for c in row)
            if any(kw in norm for kw in ["description", "qty", "amount", "price"]):
                header_idx = i
                break

        if header_idx is None:
            continue

        col_map = _map_columns(table_rows[header_idx])
        if "name" not in col_map:
            continue

        name_i = col_map.get("name")
        qty_i = col_map.get("quantity_each") or col_map.get("quantity")
        qty_case_i = col_map.get("quantity_case")
        up_i = col_map.get("unit_price")
        amt_i = col_map.get("amount")
        unit_i = col_map.get("unit")

        for row in table_rows[header_idx + 1:]:
            name = _cell(row, name_i)

            # Check the full row for summary row keywords (label may be in a
            # different column when colspan shifts the name column)
            row_text = " ".join(c.lower() for c in row)
            is_summary = (
                "sub total" in row_text
                or "subtotal" in row_text
                or "grand total" in row_text
                or "( usd )" in row_text
                or re.search(r"\btax\b", row_text) and not name
                or ("---" in row_text)
                or any(k in row_text for k in ["message", "all sales", "all new york"])
            )
            if is_summary:
                continue

            if not name:
                continue

            # Skip pure number names (leaked summary row values after colspan shift)
            if re.match(r'^[\d,.\s]+$', name):
                continue

            # Skip pure category header rows (all-caps short words, no digits)
            if name.isupper() and len(name) < 10 and not any(c.isdigit() for c in name):
                continue

            # Quantity: prefer "qty each"; fall back to "qty case"
            qty_str = _cell(row, qty_i) or _cell(row, qty_case_i)
            quantity = _parse_money(qty_str) if qty_str else None

            unit_price = _parse_money(_cell(row, up_i)) if up_i is not None else None
            total = _parse_money(_cell(row, amt_i)) if amt_i is not None else None
            # Strip asterisks (asterisk often means taxable in these invoices)
            if total is None and amt_i is not None:
                raw_amt = _cell(row, amt_i).rstrip("*").strip()
                total = _parse_money(raw_amt)
            unit = _cell(row, unit_i)

            items.append(ParsedItem(
                name=name,
                quantity=quantity,
                unit=unit,
                unit_price=unit_price,
                total=total,
                confidence=70,
            ))

    return items


def _extract_totals_from_html_tables(
    text: str,
) -> tuple[ParsedField, ParsedField, ParsedField]:
    """
    Try to extract subtotal/tax/total from summary rows inside HTML tables.

    Returns (subtotal, tax, total) ParsedFields; any not found returns missing.
    """
    subtotal = ParsedField(value=None, confidence=0, source="missing")
    tax = ParsedField(value=None, confidence=0, source="missing")
    total = ParsedField(value=None, confidence=0, source="missing")

    if "<table" not in text.lower():
        return subtotal, tax, total

    parser = _TableParser()
    try:
        parser.feed(text)
    except Exception:
        return subtotal, tax, total

    for table_rows in parser.tables:
        for row in table_rows:
            # Look for rows like ["Sub Total", "", "", "97.20"] or ["Total ( USD )", "97.20"]
            row_text = " ".join(row).lower()
            # Find the money value in the row
            amounts = [_parse_money(c) for c in row if _parse_money(c) is not None]
            if not amounts:
                continue
            val = amounts[-1]  # last money value in row

            if "sub total" in row_text or "subtotal" in row_text:
                if subtotal.value is None:
                    subtotal = ParsedField(value=val, confidence=75, source="ocr")
            elif re.search(r"\btax\b", row_text) and "sub" not in row_text:
                if tax.value is None:
                    tax = ParsedField(value=val, confidence=75, source="ocr")
            elif re.search(r"\btotal\b", row_text) and "sub" not in row_text:
                if total.value is None:
                    total = ParsedField(value=val, confidence=75, source="ocr")

    return subtotal, tax, total


def _strip_html(text: str) -> str:
    """Remove HTML tags for plain-text regex extraction."""
    return re.sub(r"<[^>]+>", " ", text)


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

    has_html = "<table" in ocr_text.lower()

    # For header/date/invoice/totals: use plain text (strip HTML tags so
    # regex patterns don't choke on tag attributes).
    plain_text = _strip_html(ocr_text) if has_html else ocr_text
    plain_lines = plain_text.split("\n")

    supplier = _extract_supplier(plain_lines)
    invoice_number = _extract_invoice_number(plain_text)
    date = _extract_date(plain_text)
    subtotal, tax, total = _extract_totals(plain_text)

    # For totals, also try HTML table summary rows (often more reliable)
    if has_html:
        html_sub, html_tax, html_total = _extract_totals_from_html_tables(ocr_text)
        if html_sub.value is not None and subtotal.value is None:
            subtotal = html_sub
        if html_tax.value is not None and tax.value is None:
            tax = html_tax
        if html_total.value is not None and total.value is None:
            total = html_total

    # For items: HTML table parser when available (more reliable than line regex)
    if has_html:
        items = _extract_items_from_html_tables(ocr_text)
        if not items:
            # Fallback to plain-text extraction if table parse yielded nothing
            items = _extract_items(plain_lines)
    else:
        items = _extract_items(plain_lines)

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
