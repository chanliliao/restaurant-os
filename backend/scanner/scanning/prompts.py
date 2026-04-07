"""
Prompt templates for invoice scanning with GLM models.

Builds structured prompts that instruct the model to extract invoice data
from images and return JSON with confidence scores and inference sources.
"""

# System instruction for GLM — separated from user prompt for better
# instruction following per model best practices.
ACCOUNTANT_SYSTEM_INSTRUCTION = (
    "You are an experienced accountant and invoice analysis assistant for a restaurant. "
    "Accuracy is critical — a wrong number means the restaurant pays the wrong amount. "
    "You would rather leave a field blank than record a wrong value. "
    "You are careful, methodical, and honest about what you can and cannot read."
)


def build_smart_pass_prompt(
    ocr_parsed: dict,
    ocr_text: str = "",
    has_header_crop: bool = False,
    has_binary_image: bool = False,
    ocr_quality: str = "good",
    ocr_source: str = "tesseract",
    supplier_context: str | None = None,
    format_description_request: str | None = None,
) -> str:
    """
    Build the extraction prompt for the OCR-first pipeline (pass 1).

    Uses an accountant framing — conservative with numbers, honest about
    uncertainty. Each field gets a "readable" flag so the system knows
    what needs re-verification in pass 2.

    Args:
        ocr_parsed: Dict from OCRParseResult.to_dict() with fields
            the OCR parser already extracted (with confidence scores).
        ocr_text: Full raw OCR text for reference.
        has_header_crop: If True, a 3rd image is included showing a
            zoomed-in crop of the header region.
        ocr_quality: "good", "poor", or "failed" — indicates OCR reliability.
        ocr_source: "glm" or "tesseract" — indicates OCR engine quality.
        supplier_context: Optional pre-formatted supplier context section
            (e.g. from build_supplier_context_section()) to append to the prompt.
        format_description_request: Optional pre-formatted format description
            request section (e.g. from build_format_description_request()) to
            append to the prompt.

    Returns:
        Prompt string for the extraction pass.
    """
    import json

    ocr_data_section = ""
    if ocr_parsed:
        ocr_data_section = (
            "\n\n## OCR-Extracted Data (Pre-Parsed)\n"
            "The following fields were extracted from the invoice via OCR. "
            "Each field has a confidence score. Validate these against the images, "
            "correct any errors, and fill in missing fields.\n\n"
            + f"```json\n{json.dumps(ocr_parsed, indent=2)}\n```"
        )

    raw_text_section = ""
    if ocr_text.strip():
        raw_text_section = (
            "\n\n## Raw OCR Text\n"
            "Below is the full raw text extracted by OCR. Use it as an additional "
            "cross-reference — it may contain errors.\n\n"
            + f"```\n{ocr_text.strip().replace('```', '---')}\n```"
        )

    ocr_quality_warning = ""
    if ocr_quality in ("poor", "failed"):
        ocr_quality_warning = (
            "\n\n## ⚠ OCR Quality Warning\n"
            "OCR was unable to extract meaningful data from this invoice. "
            "The image may be blurry, have a striped background, or contain "
            "a watermark. Be EXTRA conservative — use null for any value you "
            "cannot clearly read.\n"
        )

    glm_note = ""
    if ocr_source == "glm":
        glm_note = (
            "\n\n## OCR Source: Document Layout Parser (High Confidence)\n"
            "The OCR data and raw text above come from a professional document "
            "layout parsing engine — NOT basic OCR. HTML tables in the raw text "
            "preserve exact column structure (QTY, DESCRIPTION, UNIT PRICE, AMOUNT). "
            "Trust the structured data highly. Focus on validating numbers against "
            "the image rather than re-extracting from scratch.\n"
        )

    prompt = f"""## Task
Extract structured data from the provided invoice image(s).
For each field, you MUST indicate whether you could clearly read it:
- **"readable": true** — you can see and read this value clearly in the image
- **"readable": false** — the value is blurry, obscured, ambiguous, or you had to guess

This is critical: fields marked "readable": false will be sent back for a second
verification pass. Be honest — marking a guess as readable defeats the purpose.

You receive multiple image variants:
1. The original image (orientation-corrected only)
2. A preprocessed image (contrast-enhanced, denoised, grayscale)
{"3. A ZOOMED-IN CROP of the header/invoice-number area — use this to read the invoice number, date, and supplier name character by character." if has_header_crop else ""}
{"4. A high-contrast BINARY image (text isolated from background) — especially useful for reading numbers on striped or watermarked forms. Compare this with the other images when numbers are hard to read." if has_binary_image else ""}
{ocr_data_section}
{raw_text_section}
{ocr_quality_warning}{glm_note}

## How to Extract

### Step 1: Read the header
- Find the supplier name, invoice number, and date.
- Read the invoice number character by character. Invoice numbers often start
  with a letter (B, A, C, S, R, etc.). Common misreads: B↔8, l↔1, O↔0, S↔5.
- If you cross-reference with OCR text and both agree, you can be more confident.

### Step 2: Read the line items
- Go row by row through the items table.
- For each row, read: item name, quantity, unit, unit price, and line total.
- IMPORTANT: Not every row has all columns filled. If a cell is empty or you
  cannot read it, use null — do NOT invent a number.
- Some invoices only show the line total without a unit price — that is normal.
- "unit" means unit of measure ONLY (e.g. CS, EA, BTL, GAL, LB, OZ, CAN).
  Do NOT put item codes, UPC codes, slot numbers, or operator codes in "unit".
- When an invoice has both EACH PRICE and UNIT PRICE columns, use UNIT PRICE
  (the per-case/per-unit extended price that multiplies with qty to equal AMOUNT).
  Use the AMOUNT column directly for "total" — do NOT recompute qty × each_price.

### Step 3: Read the totals
- Find subtotal, tax, and grand total at the bottom.
- Cross-check: do the line totals add up to the subtotal?
- Cross-check: does subtotal + tax = total?

### Step 4: Self-check
- Review your extracted data. Does it make sense as an invoice?
- If a number seems implausible (e.g., quantity of 1000 for a single item),
  double-check it.
- If you are uncertain about ANY value, set "readable": false for that field.

## Beverage Invoice Context
- Beverage cases use the format "X/Y/Zml" = X packs of Y units per case.
  Example: "4/6/355ml" = 4 six-packs = 24 bottles per case.
- BOTTLE DEPOSIT quantity = total individual bottles across all cases.
  Example: 3 cases of "4/6/355ml" = 3 × 24 = 72 bottles at $0.05 each.

## Rules
- Use null for any numeric value you cannot clearly read. NEVER guess.
- Use empty string for text fields you cannot determine.
- Dates in YYYY-MM-DD format.
- Currency values as plain numbers (no $ symbols).
- Respond ONLY with valid JSON — no markdown fences, no explanation.

## Required JSON Output Schema
{{{{
    "supplier": "string",
    "date": "string — YYYY-MM-DD format",
    "invoice_number": "string",
    "items": [
        {{{{
            "name": "string",
            "quantity": 0,
            "unit": "string",
            "unit_price": 0.00,
            "total": 0.00,
            "confidence": 0,
            "readable": true
        }}}}
    ],
    "subtotal": 0.00,
    "tax": 0.00,
    "total": 0.00,
    "confidence": {{{{
        "supplier": 0,
        "date": 0,
        "invoice_number": 0,
        "subtotal": 0,
        "tax": 0,
        "total": 0
    }}}},
    "readable": {{{{
        "supplier": true,
        "date": true,
        "invoice_number": true,
        "subtotal": true,
        "tax": true,
        "total": true
    }}}},
    "inference_sources": {{{{
        "supplier": "scanned|inferred|missing",
        "date": "scanned|inferred|missing",
        "invoice_number": "scanned|inferred|missing",
        "subtotal": "scanned|inferred|missing",
        "tax": "scanned|inferred|missing",
        "total": "scanned|inferred|missing"
    }}}}
}}}}"""

    # Inject supplier context or format description request if provided
    if supplier_context:
        prompt += f"\n\n{supplier_context}"
    if format_description_request:
        prompt += f"\n\n{format_description_request}"

    return prompt


def build_verification_prompt(
    pass1_result: dict,
    uncertain_fields: list[str],
    uncertain_items: list[int],
) -> str:
    """
    Build a verification prompt for pass 2.

    Takes the pass 1 result and a list of fields/items that were marked
    as not clearly readable. Asks the LLM to focus specifically on those
    values.

    Args:
        pass1_result: The full extraction result from pass 1.
        uncertain_fields: List of top-level field names marked readable=false.
        uncertain_items: List of item indices with readable=false.

    Returns:
        Prompt string for the verification pass.
    """
    import json

    # Clean pass1 for display
    display = {k: v for k, v in pass1_result.items()
                if k not in ("scan_metadata", "readable")}

    # Build focused instructions
    field_list = ""
    if uncertain_fields:
        field_list = "**Uncertain top-level fields:** " + ", ".join(uncertain_fields)

    item_list = ""
    if uncertain_items:
        item_descs = []
        items = pass1_result.get("items", [])
        for idx in uncertain_items:
            if idx < len(items):
                name = items[idx].get("name", f"item {idx}")
                item_descs.append(f"item {idx + 1} ({name})")
        item_list = "**Uncertain line items:** " + ", ".join(item_descs)

    prompt = f"""## Second Verification Pass

## Context
A first pass already extracted data from this invoice, but some values could not
be read clearly. Your job is to look at the images AGAIN, focusing specifically
on the uncertain values, and either confirm or correct them.

## First Pass Result
```json
{json.dumps(display, indent=2)}
```

## What Needs Verification
{field_list}
{item_list}

## Instructions
1. Look at the invoice images carefully, focusing on the uncertain fields listed above.
2. For each uncertain field, try to read the value directly from the image.
3. If you can now read it clearly, provide the correct value with higher confidence.
4. If you STILL cannot read it clearly, keep it as null and set confidence to 0.
   This is perfectly acceptable — some values are genuinely unreadable.
5. Do NOT change values that were already marked as clearly readable in the first pass
   unless you spot an obvious error.
6. Cross-check your corrections: do line totals still make mathematical sense?

## Rules
- Use null for values you still cannot read. Do NOT guess.
- Respond ONLY with the complete corrected JSON — same schema as the first pass.
- No markdown fences, no explanation.

## Required JSON Output Schema
{{
    "supplier": "string",
    "date": "string — YYYY-MM-DD format",
    "invoice_number": "string",
    "items": [
        {{
            "name": "string",
            "quantity": 0,
            "unit": "string",
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
