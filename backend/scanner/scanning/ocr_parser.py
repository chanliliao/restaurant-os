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
    # "Invoice #: X", "Invoice No: X", "Invoice Number: X" (same line)
    re.compile(r"invoice\s*(?:#|no\.?|number)\s*[:.]?\s*([A-Z0-9][\w\-/]+)", re.IGNORECASE),
    # "INVOICE NO." followed by number on next line or after <br>/colon/period
    re.compile(r"INVOICE\s*NO\.?\s*(?:<br\s*/?>|\n|[:.]\s*)?\s*(\d[\d\-/]+)", re.IGNORECASE),
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


_SUPPLIER_SKIP_RE = re.compile(
    r"\b(ship\s+to|bill\s+to|sold\s+to|customer|remit\s+to|license|plenary|"
    r"tax\s+reg|tax\s+registration|reg\s*#|registration\s*#)\b",
    re.IGNORECASE,
)


def _extract_supplier(lines: list[str]) -> ParsedField:
    """
    Extract supplier name from the first ~15 lines of OCR text.

    Heuristic: Look for a line that looks like a company name
    (contains Inc, LLC, Corp, Co., Ltd, or is a prominent multi-word line
    near the top that isn't an address or shipping/billing section).

    Prefers matches in the first 5 lines (header zone).
    Strips leading GLM markdown headers (## ).
    Skips lines containing SHIP TO, BILL TO, SOLD TO, CUSTOMER, REMIT TO, LICENSE, PLENARY.
    """
    company_suffixes = re.compile(
        r"\b(Inc\.?|LLC|Corp\.?|Co\.?|Ltd\.?|Company|Imports?|Import,?\s+Inc|"
        r"Distribution|Distributors?|Supply|Supplies|Foods?|Wholesale|International)\b",
        re.IGNORECASE,
    )

    best: ParsedField | None = None

    for idx, line in enumerate(lines[:15]):
        stripped = line.strip()
        if not stripped or len(stripped) < 3:
            continue

        # Skip lines that belong to shipping/billing/license sections
        if _SUPPLIER_SKIP_RE.search(stripped):
            continue

        # Strip GLM markdown header prefix (## )
        conf_boost = 0
        if stripped.startswith("## "):
            stripped = stripped[3:].strip()
            conf_boost = 10

        if not company_suffixes.search(stripped):
            continue

        # Clean up the line
        name = stripped
        name = re.sub(r"^[^A-Za-z]+", "", name)
        name = re.sub(r"[^A-Za-z.)]+$", "", name)
        if len(name) < 3:
            continue

        # Skip candidates that look like regulatory/ID lines (contain #, REG, or 4+ digit sequences)
        if re.search(r'(#|\bREG\b|\d{4,})', name, re.IGNORECASE):
            continue

        # Lines in first 5 get higher confidence
        conf = 85 if idx < 5 else 75
        conf += conf_boost
        field = ParsedField(value=name, confidence=conf, source="ocr")

        # Keep the highest-confidence match; first-5-lines wins
        if best is None or conf > best.confidence:
            best = field
            if idx < 5:
                # First strong match in the header zone — stop looking
                break

    return best if best is not None else ParsedField(value=None, confidence=0, source="missing")


# Words that look like invoice number captures but are actually column headers
_INVOICE_NUM_SKIP = re.compile(
    r"^(PAGE|DATE|NO|NUMBER|REF|PO|COPY|CUSTOMER|ORDER|TERMS?|AMOUNT|TOTAL|QTY|UNIT|PRICE|DESC|ITEM)$",
    re.IGNORECASE,
)


def _extract_invoice_number(text: str) -> ParsedField:
    """Extract invoice number using regex patterns."""
    for pattern in _INVOICE_NUM_PATTERNS:
        m = pattern.search(text)
        if m:
            value = m.group(1).strip()
            # Must contain at least one digit — pure words are column headers, not numbers
            if not any(c.isdigit() for c in value):
                continue
            # Skip known header words even if they somehow contained a digit
            if _INVOICE_NUM_SKIP.match(value):
                continue
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
    # "each price" listed first so it wins when both columns exist (JFC invoices)
    (["each price", "price ea"], "each_price"),
    (["unit price", "unit pr", "unit pr(ea)"], "unit_price"),
    (["amount", "total", "ext", "extended", "total amt", "line total"], "amount"),
    # "less" is NY Mutual's unit column (CS/EA/TUB/CAN)
    (["uom", "unit", "um", "less"], "unit"),
    (["pack", "package"], "pack"),
]


def _kw_matches(kw: str, norm: str) -> bool:
    """Return True if keyword matches the normalized header string.

    Short keywords (≤3 chars) must match as whole words to avoid substring false
    positives — e.g. "um" in _COL_MAP must NOT match "costumer", and "cs" must
    NOT match "description".  Longer keywords use plain substring matching.
    """
    if len(kw) <= 3:
        return bool(re.search(r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])", norm))
    return kw in norm


def _map_columns(header_row: list[str]) -> dict[str, int]:
    """Map column indices from a header row. Returns field_name → col_index.

    When both "each_price" and "unit_price" columns are present (e.g. JFC invoices
    have EACH PRICE per unit and UNIT PRICE per case), keep both. The item
    extractor will prefer unit_price (the per-case price = qty * unit_price = amount)
    and fall back to each_price only when unit_price is absent.
    """
    mapping: dict[str, int] = {}
    for col_idx, cell in enumerate(header_row):
        norm = _normalize_header(cell)
        if not norm:
            continue
        for keywords, field_name in _COL_MAP:
            if field_name in mapping:
                continue
            if any(_kw_matches(kw, norm) for kw in keywords):
                mapping[field_name] = col_idx
                break

    return mapping


def _cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return row[idx].strip()


def _extract_header_from_html_tables(text: str) -> dict[str, ParsedField]:
    """
    Extract header fields (invoice_number, date) from HTML table structure.

    GLM-OCR returns header info in tables like:
        <th>INVOICE NO.</th><td>80-3860822</td>
        <th>INVOICE DATE</th><td>02/26/2025</td>

    Returns dict with any of: invoice_number, date — as ParsedField objects
    with confidence=85. Only returns keys where a value was found.
    """
    result: dict[str, ParsedField] = {}

    if "<table" not in text.lower():
        return result

    parser = _TableParser()
    try:
        parser.feed(text)
    except Exception:
        return result

    # Keywords mapping normalized cell text → field name
    _HEADER_KEY_MAP: list[tuple[str, str]] = [
        ("invoice no", "invoice_number"),
        ("invoice number", "invoice_number"),
        ("inv no", "invoice_number"),
        ("invoice date", "date"),
        ("inv date", "date"),
        ("ship date", "date"),   # fallback if no invoice date
        ("order date", "date"),
    ]

    for table_rows in parser.tables:
        for row in table_rows:
            for col_idx, cell in enumerate(row):
                norm = _normalize_header(cell)
                for keyword, field_name in _HEADER_KEY_MAP:
                    if field_name in result:
                        continue
                    if keyword not in norm:
                        continue
                    # Value is either in the same cell after a <br> / newline,
                    # or in the next cell (col_idx + 1).
                    # Since _TableParser strips tags, try splitting the cell text.
                    # _TableParser keeps text but strips tags, so "INVOICE NO.\n80-3860822"
                    # or "INVOICE NO. 80-3860822" would both appear as the full cell text.
                    # First try: remainder of cell after the label
                    cell_remainder = re.sub(
                        re.escape(keyword), "", norm, flags=re.IGNORECASE
                    ).strip(" :.\n\r\t")
                    if cell_remainder and re.search(r"\d", cell_remainder):
                        result[field_name] = ParsedField(
                            value=cell_remainder.strip(),
                            confidence=85,
                            source="ocr",
                        )
                        break

                    # Second try: value in the next cell
                    if col_idx + 1 < len(row):
                        next_val = row[col_idx + 1].strip()
                        if next_val and re.search(r"\d", next_val):
                            result[field_name] = ParsedField(
                                value=next_val,
                                confidence=85,
                                source="ocr",
                            )
                            break

    return result


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
        # Prefer unit_price (per-case price); fall back to each_price (per-unit price)
        up_i = col_map.get("unit_price") if col_map.get("unit_price") is not None else col_map.get("each_price")
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

    # Supplier is always in the header (above any table). When HTML is present,
    # restrict supplier search to pre-table text to prevent item names inside
    # table rows (e.g. "Food Plastie Wrap") from matching company_suffixes.
    if has_html:
        pre_table = ocr_text[:ocr_text.lower().index("<table")]
        supplier_lines = _strip_html(pre_table).split("\n")
    else:
        supplier_lines = plain_lines
    supplier = _extract_supplier(supplier_lines)
    invoice_number = _extract_invoice_number(plain_text)
    date = _extract_date(plain_text)
    subtotal, tax, total = _extract_totals(plain_text)

    # For invoice_number / date: HTML table header rows are most reliable
    if has_html:
        html_header = _extract_header_from_html_tables(ocr_text)
        if "invoice_number" in html_header and (
            invoice_number.value is None or invoice_number.confidence < 85
        ):
            invoice_number = html_header["invoice_number"]
        if "date" in html_header and (
            date.value is None or date.confidence < 85
        ):
            date = html_header["date"]

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


# ---------------------------------------------------------------------------
# Supplier identification & profile-driven parsing (Phase 21)
# ---------------------------------------------------------------------------

def identify_supplier(ocr_text: str, supplier_index: dict[str, str]) -> str | None:
    """Match OCR text against known supplier names.

    Searches the first 500 characters of OCR text for known supplier names.
    Uses case-insensitive substring matching.

    Args:
        ocr_text: Raw OCR text from GLM-OCR.
        supplier_index: Dict mapping supplier_id -> display name.

    Returns:
        supplier_id if a known supplier name is found, None otherwise.
    """
    if not ocr_text or not supplier_index:
        return None

    search_text = ocr_text[:500].lower()

    for supplier_id, name in supplier_index.items():
        if not name:
            continue
        if name.lower() in search_text:
            return supplier_id

    return None


def parse_with_profile(ocr_text: str, extraction_profile: dict, supplier_name: str = "") -> OCRParseResult:
    """Parse OCR text using a supplier-specific extraction profile.

    Uses exact field labels and column maps from the profile instead of
    generic regex. Falls back to generic parsing for any field not covered
    by the profile.

    Args:
        ocr_text: Raw OCR text from GLM-OCR (may contain HTML tables).
        extraction_profile: Dict with keys like invoice_number_label,
            date_label, column_map, has_subtotal_row, etc.
        supplier_name: Known supplier name to return directly.

    Returns:
        OCRParseResult with supplier-specific extraction applied.
    """
    result = parse_ocr_text(ocr_text)

    # Supplier name: return directly from memory (confidence 95)
    if supplier_name:
        result.supplier = ParsedField(value=supplier_name, confidence=95, source="memory")

    # Invoice number: search for exact label
    inv_label = extraction_profile.get("invoice_number_label")
    if inv_label:
        inv_value = _extract_labeled_field(ocr_text, inv_label)
        if inv_value:
            result.invoice_number = ParsedField(value=inv_value, confidence=90, source="profile")

    # Date: search for exact label
    date_label = extraction_profile.get("date_label")
    if date_label:
        date_value = _extract_labeled_field(ocr_text, date_label)
        if date_value:
            result.date = ParsedField(value=date_value, confidence=90, source="profile")

    # Items: re-parse using column map if provided
    column_map = extraction_profile.get("column_map")
    if column_map:
        profile_items = _parse_items_with_column_map(ocr_text, column_map)
        if profile_items:
            result.items = profile_items

    return result


def _extract_labeled_field(text: str, label: str) -> str | None:
    """Find a field value by its exact label in OCR text.

    Looks for "LABEL: value", "LABEL value" (on same line), or
    "LABEL\\nvalue" (value on next line after label).

    Returns the stripped value string, or None if not found.
    """
    # Escape label for regex
    escaped = re.escape(label)

    # Same-line patterns: "ORDER #: 1234567-001" or "ORDER # 1234567-001"
    same_line = re.search(
        rf"{escaped}\s*[:.]?\s*([A-Z0-9][\w\-/]+)",
        text,
        re.IGNORECASE,
    )
    if same_line:
        return same_line.group(1).strip()

    # Next-line pattern: label on one line, value on next
    next_line = re.search(
        rf"{escaped}\s*\n\s*([A-Z0-9][\w\-/]+)",
        text,
        re.IGNORECASE,
    )
    if next_line:
        return next_line.group(1).strip()

    return None


def _parse_items_with_column_map(text: str, column_map: dict[str, str]) -> list[ParsedItem]:
    """Parse line items from HTML table using supplier-specific column mapping.

    Maps column headers to standard field names using column_map.
    column_map example: {"CS": "quantity", "LESS": "unit", "AMOUNT": "total"}

    Returns list of ParsedItem, or empty list if no table found.
    """
    # Use the existing HTML table parser
    table_rows = _extract_html_table_rows(text)
    if not table_rows:
        return []

    # Find header row — the row whose cells match our column_map keys
    header_indices: dict[str, int] = {}  # field_name -> column_index
    header_row_idx = -1

    for row_idx, row in enumerate(table_rows):
        matched = 0
        temp_indices: dict[str, int] = {}
        for col_idx, cell in enumerate(row):
            cell_stripped = cell.strip()
            for col_header, field_name in column_map.items():
                if col_header.lower() in cell_stripped.lower():
                    temp_indices[field_name] = col_idx
                    matched += 1
        if matched >= 2:  # Found the header row
            header_indices = temp_indices
            header_row_idx = row_idx
            break

    if not header_indices or header_row_idx < 0:
        return []

    items = []
    for row in table_rows[header_row_idx + 1:]:
        if not row or all(not c.strip() for c in row):
            continue

        # Skip rows that look like totals
        first_cell = row[0].strip().lower() if row else ""
        if any(kw in first_cell for kw in ("total", "subtotal", "tax", "amount due")):
            break

        item = ParsedItem()

        # Name: look for "name" in column_map, or use the longest non-numeric cell
        name_idx = header_indices.get("name")
        if name_idx is not None and name_idx < len(row):
            item.name = row[name_idx].strip()
        else:
            # Fallback: use the widest text cell
            best_name = ""
            for cell in row:
                cell = cell.strip()
                if len(cell) > len(best_name) and not re.match(r'^[\d.,]+$', cell):
                    best_name = cell
            item.name = best_name

        if not item.name:
            continue

        # Numeric fields from column map
        qty_idx = header_indices.get("quantity")
        if qty_idx is not None and qty_idx < len(row):
            val = _parse_money(row[qty_idx])
            if val is not None:
                item.quantity = val

        unit_idx = header_indices.get("unit")
        if unit_idx is not None and unit_idx < len(row):
            item.unit = row[unit_idx].strip()

        price_idx = header_indices.get("unit_price")
        if price_idx is not None and price_idx < len(row):
            item.unit_price = _parse_money(row[price_idx])

        total_idx = header_indices.get("total")
        if total_idx is not None and total_idx < len(row):
            item.total = _parse_money(row[total_idx])

        item.confidence = 80 if item.quantity is not None and item.unit_price is not None else 60
        items.append(item)

    return items


def _extract_html_table_rows(text: str) -> list[list[str]]:
    """Extract all rows from the first HTML table in the text.

    Returns a list of rows, each row being a list of cell strings.
    Returns empty list if no table is found.
    """
    if "<table" not in text.lower():
        return []

    parser = _TableParser()
    try:
        parser.feed(text)
    except Exception:
        return []

    if not parser.tables:
        return []

    # Return rows from the first table only
    return parser.tables[0]
