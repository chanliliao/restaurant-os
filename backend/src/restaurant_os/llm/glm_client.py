"""
Async GLM-4-Flash + GLM-OCR wrapper with integrated OCR field parsing.

"""

from __future__ import annotations
import asyncio
import base64
import io
import json
import logging
import re
from dataclasses import dataclass, field as dc_field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, AsyncGenerator
import httpx
import yaml
from PIL import Image
from restaurant_os.core.config import settings

logger = logging.getLogger(__name__)

_GLM_OCR_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/layout_parsing"
_GLM_CHAT_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
_PROMPTS_DIR = Path(__file__).parent / "prompts"


# ---------------------------------------------------------------------------
# OCR parse result data structures (ported from scanner/scanning/ocr_parser.py)
# ---------------------------------------------------------------------------


@dataclass
class ParsedField:
    """A single extracted invoice field with its value and extraction confidence."""

    value: str | float | None
    confidence: int  # 0–100
    source: str = "ocr"  # "ocr" or "missing"


@dataclass
class ParsedItem:
    """A partially-parsed line item from raw OCR text."""

    name: str = ""
    quantity: float | None = None
    unit: str = ""
    unit_price: float | None = None
    total: float | None = None
    confidence: int = 0


@dataclass
class OCRParseResult:
    """Structured result from parsing GLM-OCR output text."""

    supplier: ParsedField = dc_field(
        default_factory=lambda: ParsedField(None, 0, "missing")
    )
    invoice_number: ParsedField = dc_field(
        default_factory=lambda: ParsedField(None, 0, "missing")
    )
    date: ParsedField = dc_field(
        default_factory=lambda: ParsedField(None, 0, "missing")
    )
    subtotal: ParsedField = dc_field(
        default_factory=lambda: ParsedField(None, 0, "missing")
    )
    tax: ParsedField = dc_field(
        default_factory=lambda: ParsedField(None, 0, "missing")
    )
    total: ParsedField = dc_field(
        default_factory=lambda: ParsedField(None, 0, "missing")
    )
    items: list[ParsedItem] = dc_field(default_factory=list)
    raw_text: str = ""

    def to_dict(self) -> dict:
        """Convert to a summary dict for embedding in an LLM extraction prompt."""
        result: dict = {}
        for fname in ("supplier", "invoice_number", "date", "subtotal", "tax", "total"):
            pf: ParsedField = getattr(self, fname)
            if pf.value is not None and pf.confidence > 0:
                result[fname] = {"value": pf.value, "confidence": pf.confidence}
        if self.items:
            result["items"] = []
            for item in self.items:
                d: dict = {"name": item.name}
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
        needs: list[str] = []
        for fname in ("supplier", "invoice_number", "date", "subtotal", "tax", "total"):
            pf: ParsedField = getattr(self, fname)
            if pf.value is None or pf.confidence < 60:
                needs.append(fname)
        if not self.items or any(
            i.quantity is None or i.total is None for i in self.items
        ):
            needs.append("items")
        return needs


# ---------------------------------------------------------------------------
# OCR text parsing helpers # ---------------------------------------------------------------------------

_INVOICE_NUM_PATTERNS = [
    re.compile(
        r"invoice\s*(?:#|no\.?|number)\s*[:.]?\s*([A-Z0-9][\w\-/]+)", re.IGNORECASE
    ),
    re.compile(
        r"INVOICE\s*NO\.?\s*(?:<br\s*/?>|\n|[:.]\s*)?\s*(\d[\d\-/]+)", re.IGNORECASE
    ),
    re.compile(r"\b(INV[\-]?\d{3,})\b", re.IGNORECASE),
    re.compile(r"INVOICE\s+.*?([A-Z]\d{5,})", re.IGNORECASE),
    re.compile(r"#\s*([A-Z0-9][\w\-]{4,})", re.IGNORECASE),
]

_DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\b"),
    re.compile(r"\b(\d{4}[/\-]\d{1,2}[/\-]\d{1,2})\b"),
    re.compile(
        r"date\s*[:.]?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", re.IGNORECASE
    ),
    re.compile(r"\b(\w{3,9}\s+\d{1,2},?\s+\d{4})\b"),
]

_TOTAL_PATTERNS = [
    re.compile(
        r"(?:grand\s+)?total\s*[:.]?\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE
    ),
]
_SUBTOTAL_PATTERNS = [
    re.compile(r"sub\s*total\s*[:.]?\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE),
]
_TAX_PATTERNS = [
    re.compile(
        r"(?:sales\s+)?tax\s*[:.]?\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE
    ),
]

_SUPPLIER_SKIP_RE = re.compile(
    r"\b(ship\s+to|bill\s+to|sold\s+to|customer|remit\s+to|license|plenary|"
    r"tax\s+reg|tax\s+registration|reg\s*#|registration\s*#)\b",
    re.IGNORECASE,
)

_INVOICE_NUM_SKIP = re.compile(
    r"^(PAGE|DATE|NO|NUMBER|REF|PO|COPY|CUSTOMER|ORDER|TERMS?|AMOUNT|TOTAL|QTY|UNIT|PRICE|DESC|ITEM)$",
    re.IGNORECASE,
)

_COMPANY_SUFFIXES = re.compile(
    r"\b(Inc\.?|LLC|Corp\.?|Co\.?|Ltd\.?|Company|Imports?|Import,?\s+Inc|"
    r"Distribution|Distributors?|Supply|Supplies|Foods?|Wholesale|International)\b",
    re.IGNORECASE,
)


def _parse_money(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (ValueError, TypeError):
        return None


def _extract_supplier(lines: list[str]) -> ParsedField:
    best: ParsedField | None = None
    for idx, line in enumerate(lines[:15]):
        stripped = line.strip()
        if not stripped or len(stripped) < 3:
            continue
        if _SUPPLIER_SKIP_RE.search(stripped):
            continue
        conf_boost = 0
        if stripped.startswith("## "):
            stripped = stripped[3:].strip()
            conf_boost = 10
        if not _COMPANY_SUFFIXES.search(stripped):
            continue
        name = stripped
        name = re.sub(r"^[^A-Za-z]+", "", name)
        name = re.sub(r"[^A-Za-z.)]+$", "", name)
        if len(name) < 3:
            continue
        if re.search(r"(#|\bREG\b|\d{4,})", name, re.IGNORECASE):
            continue
        conf = 85 if idx < 5 else 75
        conf += conf_boost
        candidate = ParsedField(value=name, confidence=conf, source="ocr")
        if best is None or conf > best.confidence:
            best = candidate
            if idx < 5:
                break
    return best if best is not None else ParsedField(None, 0, "missing")


def _extract_invoice_number(text: str) -> ParsedField:
    for pattern in _INVOICE_NUM_PATTERNS:
        m = pattern.search(text)
        if m:
            value = m.group(1).strip()
            if not any(c.isdigit() for c in value):
                continue
            if _INVOICE_NUM_SKIP.match(value):
                continue
            conf = 80 if re.match(r"^[A-Z]\d+$", value) else 65
            return ParsedField(value=value, confidence=conf, source="ocr")
    return ParsedField(None, 0, "missing")


def _extract_date(text: str) -> ParsedField:
    for pattern in _DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            value = m.group(1).strip()
            if any(c.isdigit() for c in value):
                return ParsedField(value=value, confidence=70, source="ocr")
    return ParsedField(None, 0, "missing")


def _extract_totals(
    text: str,
) -> tuple[ParsedField, ParsedField, ParsedField]:
    subtotal = ParsedField(None, 0, "missing")
    tax = ParsedField(None, 0, "missing")
    total = ParsedField(None, 0, "missing")
    for pattern in _SUBTOTAL_PATTERNS:
        m = pattern.search(text)
        if m:
            val = _parse_money(m.group(1))
            if val is not None:
                subtotal = ParsedField(val, 70, "ocr")
                break
    for pattern in _TAX_PATTERNS:
        m = pattern.search(text)
        if m:
            val = _parse_money(m.group(1))
            if val is not None:
                tax = ParsedField(val, 70, "ocr")
                break
    for pattern in _TOTAL_PATTERNS:
        m = pattern.search(text)
        if m:
            val = _parse_money(m.group(1))
            if val is not None:
                total = ParsedField(val, 70, "ocr")
                break
    return subtotal, tax, total


def _extract_items(lines: list[str]) -> list[ParsedItem]:
    items: list[ParsedItem] = []
    item_line_pattern = re.compile(
        r"^(\d+)?\s*(.{5,}?)\s+(\d+\.?\d*)\s+(\d+\.?\d*)$"
    )
    product_keywords = re.compile(
        r"\b(case|bottle|can|pack|box|bag|lb|kg|oz|gallon|each|ea)\b",
        re.IGNORECASE,
    )
    for line in lines:
        stripped = line.strip()
        if not stripped or len(stripped) < 5:
            continue
        m = item_line_pattern.match(stripped)
        if m:
            items.append(
                ParsedItem(
                    name=m.group(2).strip(),
                    quantity=float(m.group(1)) if m.group(1) else None,
                    confidence=50,
                )
            )
            continue
        if product_keywords.search(stripped):
            name = re.sub(r"^\d+\s+", "", stripped)
            name = re.sub(r"\s+[\d$.]+\s*$", "", name)
            if len(name) >= 3:
                items.append(ParsedItem(name=name.strip(), confidence=40))
    return items


class _TableParser(HTMLParser):
    """Extract rows from HTML <table> elements in GLM-OCR output."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: str = ""
        self._in_cell: bool = False
        self._current_colspan: int = 1

    def handle_starttag(self, tag: str, attrs: list) -> None:
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

    def handle_endtag(self, tag: str) -> None:
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
            for _ in range(self._current_colspan - 1):
                self._current_row.append("")
            self._in_cell = False
            self._current_colspan = 1

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell += data

    def handle_entityref(self, name: str) -> None:
        if self._in_cell:
            entities = {
                "amp": "&",
                "lt": "<",
                "gt": ">",
                "nbsp": " ",
                "quot": '"',
            }
            self._current_cell += entities.get(name, "")

    def handle_charref(self, name: str) -> None:
        if self._in_cell:
            try:
                char = chr(int(name[1:], 16) if name.startswith("x") else int(name))
                self._current_cell += char
            except (ValueError, OverflowError):
                pass


def _extract_header_from_html_tables(text: str) -> dict[str, ParsedField]:
    """Pull invoice_number and date from HTML <table> structures in GLM-OCR output."""
    result: dict[str, ParsedField] = {}
    if "<table" not in text.lower():
        return result
    parser = _TableParser()
    try:
        parser.feed(text)
    except Exception:
        return result

    inv_headers = re.compile(
        r"invoice\s*(no|number|#|num)", re.IGNORECASE
    )
    date_headers = re.compile(r"(invoice\s+)?date", re.IGNORECASE)

    for table in parser.tables:
        for row in table:
            for col_idx, cell in enumerate(row):
                if not cell:
                    continue
                if inv_headers.search(cell) and col_idx + 1 < len(row):
                    val = row[col_idx + 1].strip()
                    if val and any(c.isdigit() for c in val):
                        result["invoice_number"] = ParsedField(val, 85, "ocr")
                elif date_headers.search(cell) and col_idx + 1 < len(row):
                    val = row[col_idx + 1].strip()
                    if val and any(c.isdigit() for c in val):
                        result["date"] = ParsedField(val, 85, "ocr")
    return result


def parse_ocr_text(text: str) -> OCRParseResult:
    """
    Parse raw GLM-OCR text into structured invoice fields.
    output and HTML table structures emitted by GLM-OCR's layout parser.
    """
    lines = text.splitlines()

    supplier = _extract_supplier(lines)
    invoice_number = _extract_invoice_number(text)
    date = _extract_date(text)
    subtotal, tax, total = _extract_totals(text)
    items = _extract_items(lines)

    # Override with higher-confidence HTML table extractions when available
    html_fields = _extract_header_from_html_tables(text)
    if "invoice_number" in html_fields:
        invoice_number = html_fields["invoice_number"]
    if "date" in html_fields:
        date = html_fields["date"]

    return OCRParseResult(
        supplier=supplier,
        invoice_number=invoice_number,
        date=date,
        subtotal=subtotal,
        tax=tax,
        total=total,
        items=items,
        raw_text=text,
    )


# ---------------------------------------------------------------------------
# Image optimization helpers (ported from scanner/scanning/engine.py)
# ---------------------------------------------------------------------------


def _optimize_image(image_bytes: bytes) -> tuple[bytes, str]:
    """
    Resize and re-encode image bytes for GLM-OCR upload.

    - < 500 KB JPEG/PNG: returned as-is
    - 500 KB–1 MB: re-encoded as JPEG q85
    - > 1 MB: longest edge capped at 2000 px, JPEG q82
    """
    size = len(image_bytes)
    if size < 500_000:
        if image_bytes[:3] == b"\xff\xd8\xff":
            return image_bytes, "image/jpeg"
        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            return image_bytes, "image/png"
        return image_bytes, "image/jpeg"

    img = Image.open(io.BytesIO(image_bytes))
    img.load()

    if size > 1_000_000:
        w, h = img.size
        max_edge = max(w, h)
        if max_edge > 2000:
            scale = 2000 / max_edge
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    quality = 82 if size > 1_000_000 else 85
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    optimized = buf.getvalue()
    logger.debug(
        "_optimize_image: %d KB → %d KB (JPEG q%d)",
        size // 1024,
        len(optimized) // 1024,
        quality,
    )
    return optimized, "image/jpeg"


# ---------------------------------------------------------------------------
# GLMClient
# ---------------------------------------------------------------------------


class GLMClient:
    """
    Async client for GLM-OCR (layout parsing) and GLM-4-Flash (chat + tool calling).

    Usage:
        client = GLMClient(api_key=..., model=..., ocr_model=...)

        # OCR
        text = await client.aocr(image_bytes)
        parsed = client.parse_ocr_text(text)

        # Chat (non-streaming)
        response = await client.achat(messages=[...], tools=[...])
        content = response["content"]
        tool_calls = response["tool_calls"]  # list[dict] or None

        # Chat (streaming)
        async for chunk in await client.achat(messages=[...], stream=True):
            print(chunk["content"], end="", flush=True)
    """

    def __init__(
        self,
        api_key: str,
        model: str = "glm-4-flash",
        ocr_model: str = "glm-ocr",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._ocr_model = ocr_model
        self._prompts: dict[str, dict] = {}
        self._load_prompts()

    # ------------------------------------------------------------------
    # Prompt loading
    # ------------------------------------------------------------------

    def _load_prompts(self) -> None:
        """Load all YAML prompt files from the prompts/ subdirectory."""
        if not _PROMPTS_DIR.exists():
            logger.warning("GLMClient: prompts directory not found at %s", _PROMPTS_DIR)
            return
        for yaml_file in sorted(_PROMPTS_DIR.glob("*.yaml")):
            with yaml_file.open(encoding="utf-8") as fh:
                self._prompts[yaml_file.stem] = yaml.safe_load(fh) or {}
            logger.debug("GLMClient: loaded prompt '%s'", yaml_file.stem)

    def get_prompt_content(self, name: str) -> str:
        """Return the content string for a named YAML prompt file."""
        return self._prompts.get(name, {}).get("content", "")

    def get_prompt_version(self, name: str) -> str:
        """Return the version string for a named YAML prompt file."""
        return self._prompts.get(name, {}).get("version", "unknown")

    # ------------------------------------------------------------------
    # OCR
    # ------------------------------------------------------------------

    async def aocr(self, image_bytes: bytes) -> str:
        """
        Submit an image to the GLM-OCR layout parser and return extracted text.

        Ports the _call_glm_ocr() function from engine.py, rewritten as async.
        Applies size/format optimization before upload.

        Returns:
            Concatenated text and table content from all recognised blocks.
        """
        optimized, media_type = _optimize_image(image_bytes)
        b64 = base64.b64encode(optimized).decode()
        data_uri = f"data:{media_type};base64,{b64}"

        logger.info(
            "GLMClient.aocr: uploading %d KB as %s",
            len(optimized) // 1024,
            media_type,
        )

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                _GLM_OCR_ENDPOINT,
                headers={"Authorization": self._api_key},
                json={"model": self._ocr_model, "file": data_uri},
            )
            response.raise_for_status()

        data = response.json()
        text_parts: list[str] = []
        for page_blocks in data.get("layout_details", []):
            for block in page_blocks:
                if isinstance(block, dict) and block.get("label") in ("text", "table"):
                    content = block.get("content", "")
                    if content:
                        text_parts.append(str(content))

        if not text_parts:
            logger.warning("GLMClient.aocr: unexpected response structure — using raw JSON")
            text_parts = [json.dumps(data, ensure_ascii=False)]

        extracted = "\n".join(text_parts)
        logger.info("GLMClient.aocr: extracted %d characters", len(extracted))
        return extracted

    # ------------------------------------------------------------------
    # Chat completions (non-streaming and streaming)
    # ------------------------------------------------------------------

    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        temperature: float = 0.0,
        response_format: dict | None = None,
    ) -> dict[str, Any] | AsyncGenerator[dict[str, Any], None]:
        """
        Call GLM-4-Flash chat completions with optional tool calling and streaming.

        Args:
            messages: Conversation history in OpenAI message format.
            tools: List of tool definitions (JSON schema). When provided, the
                model may return ``tool_calls`` instead of ``content``.
            stream: If True, returns an async generator yielding content chunks.
            temperature: Sampling temperature (0 = deterministic).
            response_format: Optional response format hint (e.g. {"type": "json_object"}).

        Returns:
            Non-streaming: dict with keys ``content``, ``tool_calls``, ``usage``.
            Streaming: AsyncGenerator yielding ``{"content": str}`` chunks.

        Tool calling example:
            response = await client.achat(
                messages=[{"role": "user", "content": "Find salmon suppliers in Seattle"}],
                tools=[search_supplier_schema],
            )
            if response["tool_calls"]:
                call = response["tool_calls"][0]
                args = json.loads(call["function"]["arguments"])
        """
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
        if response_format:
            payload["response_format"] = response_format
        if stream:
            payload["stream"] = True
            return self._astream(payload)

        return await self._achat_once(payload)

    async def _achat_once(
        self, payload: dict[str, Any], max_retries: int = 3
    ) -> dict[str, Any]:
        """Single (non-streaming) chat completion with exponential retry on 429."""
        last_response: httpx.Response | None = None
        for attempt in range(max_retries):
            async with httpx.AsyncClient(timeout=120) as client:
                last_response = await client.post(
                    _GLM_CHAT_ENDPOINT,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self._api_key}",
                    },
                    json=payload,
                )
            if last_response.status_code == 429 and attempt < max_retries - 1:
                wait = 5 * (2**attempt)  # 5 s, 10 s, 20 s
                logger.warning(
                    "GLMClient.achat: 429 rate limit — retrying in %ds (attempt %d/%d)",
                    wait,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(wait)
                continue
            last_response.raise_for_status()
            data = last_response.json()
            message = data["choices"][0]["message"]
            return {
                "content": message.get("content"),
                "tool_calls": message.get("tool_calls"),
                "usage": data.get("usage", {}),
            }

        # Final attempt already raised; unreachable but satisfies type checkers
        raise RuntimeError("GLMClient.achat: max retries exceeded")

    async def _astream(
        self, payload: dict[str, Any]
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Streaming chat completion.

        Yields ``{"content": str}`` dicts as tokens arrive via SSE.
        The caller can accumulate ``chunk["content"]`` values to reconstruct
        the full response — the same pattern used by api/v1/routes.py for SSE.
        """
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                _GLM_CHAT_ENDPOINT,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw.strip() == "[DONE]":
                        return
                    try:
                        chunk = json.loads(raw)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content") or ""
                        if content:
                            yield {"content": content}
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    # ------------------------------------------------------------------
    # Response parsing utilities
    # ------------------------------------------------------------------

    @staticmethod
    def parse_json_response(text: str) -> dict[str, Any]:
        """
        Parse JSON from an LLM text response.

        Handles markdown code fences, trailing commas, inline comments, and
        stray control characters that GLM sometimes embeds inside string values.
        """
        cleaned = text.strip()
        if cleaned.startswith("```"):
            first_nl = cleaned.find("\n")
            if first_nl != -1:
                cleaned = cleaned[first_nl + 1 :]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3].strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        fixed = re.sub(r",\s*([}\]])", r"\1", cleaned)
        fixed = re.sub(r"//[^\n]*", "", fixed)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        fixed = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", fixed)
        return json.loads(fixed)

    @staticmethod
    def parse_ocr_text(text: str) -> OCRParseResult:
        """
        Parse raw GLM-OCR text into structured invoice fields.

        Delegates to the module-level ``parse_ocr_text()`` function which
        contains all regex patterns and HTML table parsing logic ported from
        scanner/scanning/ocr_parser.py.
        """
        return parse_ocr_text(text)


# ---------------------------------------------------------------------------
# Module-level singleton — import this wherever the GLM client is needed:
#   from restaurant_os.llm.glm_client import glm_client
# ---------------------------------------------------------------------------

glm_client = GLMClient(
    api_key=settings.glm_ocr_api_key,
    model=settings.glm_model,
    ocr_model=settings.glm_ocr_model,
)
