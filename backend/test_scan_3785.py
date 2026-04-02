"""
Diagnostic scan with per-stage timing breakdown — IMG_3785.
Usage: python -X utf8 test_scan_3785.py
"""
import os, sys, io, base64, re, time
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartscanner.settings")
sys.path.insert(0, os.path.dirname(__file__))
import django; django.setup()

from PIL import Image
from scanner.scanning.engine import (
    _optimize_for_glm, _call_glm_ocr, _optimize_image_for_vision, scan_invoice
)
from scanner.scanning.ocr_parser import parse_ocr_text
from scanner.preprocessing import prepare_variants
from scanner.preprocessing.segmentation import segment_invoice

IMAGE_PATH = r"C:\Users\cliao\Desktop\Coding\Claude Projects\SmartScanner\z_test_files\companies_6HRPprEeSHQrgE8tZDt6_email-ingest_CAHJM-4xpBDiSExQ7DkSBbjvjcrK0oN1z4Fv8ie5hcJwoGfs0Bg@mail.gmail.com_IMG_3785_3a13a9d8.jpeg"
SEP = "=" * 70
timings = {}

def section(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")

def hms(s):
    return f"{s:.2f}s"

def header_glm_useful(text):
    empty_cells = len(re.findall(r"<td>\s*</td>", text))
    if empty_cells >= 5:
        return False
    plain = re.sub(r"<[^>]+>", " ", text).strip()
    plain = re.sub(r"\s+", " ", plain)
    if len(plain) < 30:
        return False
    _TABLE_HEADERS = {"stock", "quantity", "description", "amount", "price",
                      "units", "cases", "bottles", "item", "number", "upc",
                      "code", "srp", "dsc", "less", "cte", "sub", "page"}
    real_words = [w for w in plain.lower().split()
                  if len(w) >= 4 and w not in _TABLE_HEADERS]
    return len(real_words) >= 3

def main():
    scan_start = time.time()
    print(SEP)
    print(f"  SMARTSCANNER -- DIAGNOSTIC SCAN: IMG_3785")
    print(SEP)

    with open(IMAGE_PATH, "rb") as f:
        image_bytes = f.read()
    print(f"\nImage: {len(image_bytes)//1024} KB")

    # ── STAGE 1: PREPROCESSING ────────────────────────────────────────────────
    section("STAGE 1 -- PREPROCESSING")
    t = time.time()
    image = Image.open(io.BytesIO(image_bytes)); image.load()
    variants = prepare_variants(image)
    original     = variants["original"]
    preprocessed = variants["preprocessed"]
    glm_bytes, glm_media_type = _optimize_for_glm(image_bytes)
    orig_b64, orig_media = _optimize_image_for_vision(original)
    pre_b64,  pre_media  = _optimize_image_for_vision(preprocessed)
    seg = segment_invoice(original)
    zones = [k for k, v in seg.items() if v is not None
             and k not in ("regions_detected","bounding_boxes","method")]
    timings["1_preprocessing"] = time.time() - t

    print(f"  Original      : {original.size[0]}x{original.size[1]} px")
    print(f"  GLM-OCR image : {len(glm_bytes)//1024} KB  ({glm_media_type})")
    print(f"  Vision images : {len(base64.b64decode(orig_b64))//1024} KB + {len(base64.b64decode(pre_b64))//1024} KB JPEG")
    print(f"  Segments      : {zones}  (method: {seg.get('method','?')})")
    print(f"  Time: {hms(timings['1_preprocessing'])}")

    # ── STAGE 2: GLM-OCR FULL PAGE ────────────────────────────────────────────
    section("STAGE 2 -- GLM-OCR (full page)")
    t = time.time()
    glm_b64  = base64.b64encode(glm_bytes).decode()
    glm_text = _call_glm_ocr(glm_b64, media_type=glm_media_type)
    timings["2_glm_ocr_full"] = time.time() - t
    print(f"  {len(glm_text)} characters  |  Time: {hms(timings['2_glm_ocr_full'])}\n")
    print(glm_text)

    # ── STAGE 3: GLM-OCR HEADER CROP ─────────────────────────────────────────
    section("STAGE 3 -- GLM-OCR (header crop + smart fallback)")
    header_glm_text = ""
    crop_source = "none"
    t = time.time()

    if seg.get("header") is not None:
        h_b64, h_media = _optimize_image_for_vision(seg["header"], max_edge=1600)
        header_glm_text = _call_glm_ocr(h_b64, media_type=h_media)
        if header_glm_useful(header_glm_text):
            crop_source = "segmented header crop"
        else:
            full_page_has_supplier = bool(parse_ocr_text(glm_text).supplier.value)
            if not full_page_has_supplier:
                print(f"  Header crop useless + supplier missing — trying top-30% fallback")
                w, h = original.size
                top30 = original.crop((0, 0, w, int(h * 0.30)))
                fb_b64, fb_media = _optimize_image_for_vision(top30, max_edge=1600)
                fallback_text = _call_glm_ocr(fb_b64, media_type=fb_media)
                if header_glm_useful(fallback_text):
                    header_glm_text = fallback_text
                    crop_source = "top-30% fallback"
                else:
                    crop_source = "both failed"
            else:
                print(f"  Header crop useless but full-page has supplier — skipping fallback")
                crop_source = "skipped (full-page sufficient)"
    else:
        print("  No header segment detected")

    timings["3_glm_ocr_header"] = time.time() - t
    print(f"  Source: {crop_source}  |  {len(header_glm_text)} chars  |  Time: {hms(timings['3_glm_ocr_header'])}\n")
    if header_glm_useful(header_glm_text):
        print(header_glm_text)
    else:
        print("  (no useful header content)")

    # ── STAGE 4: OCR PARSER ───────────────────────────────────────────────────
    section("STAGE 4 -- OCR PARSER (no LLM, no Tesseract)")
    t = time.time()
    combined_text = glm_text
    if header_glm_text.strip():
        combined_text += "\n\n--- HEADER GLM-OCR ---\n" + header_glm_text
    parsed = parse_ocr_text(combined_text)
    timings["4_ocr_parser"] = time.time() - t

    print(f"\n  Time: {hms(timings['4_ocr_parser'])}")
    print(f"\n  {'Field':<20} {'Value':<35} {'Conf':<8} Source")
    print(f"  {'-'*70}")
    for fname in ("supplier", "invoice_number", "date", "subtotal", "tax", "total"):
        pf = getattr(parsed, fname)
        val  = str(pf.value)[:34] if pf.value is not None else "NOT FOUND"
        conf = f"{pf.confidence}%" if pf.value is not None else "--"
        flag = "  OK" if pf.confidence >= 60 else ("  ?" if pf.confidence > 0 else "  X")
        print(f"  {fname:<20} {val:<35} {conf:<8} {pf.source}{flag}")

    items = parsed.items
    print(f"\n  LINE ITEMS ({len(items)} found):")
    if items:
        print(f"  {'#':<4} {'Name':<35} {'Qty':<8} {'Unit':<8} {'UnitPrice':<12} {'Total':<10} Conf")
        print(f"  {'-'*85}")
        for i, item in enumerate(items, 1):
            qty  = str(item.quantity) if item.quantity is not None else "--"
            unit = str(item.unit)[:7] if item.unit else "--"
            up   = str(item.unit_price) if item.unit_price is not None else "--"
            tot  = str(item.total) if item.total is not None else "--"
            print(f"  {i:<4} {str(item.name)[:34]:<35} {qty:<8} {unit:<8} {up:<12} {tot:<10} {item.confidence}%")
    else:
        print("  (none)")

    # ── STAGE 5: LLM NEEDED SUMMARY ──────────────────────────────────────────
    section("STAGE 5 -- WHAT NEEDED LLM HELP")
    needs_llm = parsed.fields_needing_llm()
    good = [f for f in ("supplier","invoice_number","date","subtotal","tax","total")
            if getattr(parsed, f).value is not None and getattr(parsed, f).confidence >= 60]
    print("\n  OCR only (no LLM needed):")
    if good:
        for f in good:
            pf = getattr(parsed, f)
            print(f"    OK  {f:<20} = {pf.value}  (conf {pf.confidence}%)")
    else:
        print("    (none)")
    print("\n  Needed LLM:")
    for f in needs_llm:
        if f == "items":
            inc = sum(1 for i in items if i.quantity is None or i.unit_price is None or i.total is None)
            print(f"    X   items  -- {len(items)} found, {inc} incomplete")
        else:
            pf = getattr(parsed, f)
            reason = "not found" if pf.value is None else f"low conf ({pf.confidence}%)"
            print(f"    X   {f:<20} -- {reason}")

    # ── STAGE 6: FULL ENGINE ──────────────────────────────────────────────────
    section("STAGE 6 -- FULL ENGINE SCAN (mode=glm)")
    print("  Calling scan_invoice(mode='glm')...\n")
    t = time.time()
    result = scan_invoice(image_bytes, mode="glm")
    timings["6_llm_engine"] = time.time() - t
    print(f"  Time: {hms(timings['6_llm_engine'])}")

    print("\n  FINAL RESULT:")
    for key in ("supplier", "invoice_number", "date", "subtotal", "tax", "total"):
        val = result.get(key)
        if val is not None:
            print(f"  {key:<22} {val}")

    final_items = result.get("items", [])
    print(f"\n  LINE ITEMS ({len(final_items)}):")
    if final_items:
        print(f"  {'#':<4} {'Name':<35} {'Qty':<8} {'Unit':<8} {'Unit Price':<12} {'Total'}")
        print(f"  {'-'*80}")
        for i, item in enumerate(final_items, 1):
            print(f"  {i:<4} {str(item.get('name',''))[:34]:<35} {str(item.get('quantity','--')):<8} "
                  f"{str(item.get('unit','--'))[:7]:<8} {str(item.get('unit_price','--')):<12} {item.get('total','--')}")
    else:
        print("  (no items)")

    conf = result.get("confidence", {})
    if conf:
        print(f"\n  Confidence: " + "  ".join(f"{k}={v}" for k,v in conf.items()))
    meta = result.get("scan_metadata", {})
    print(f"  API calls : {meta.get('api_calls','--')}")

    # ── TIMING SUMMARY ────────────────────────────────────────────────────────
    total_elapsed = time.time() - scan_start
    section("TIMING SUMMARY")
    stage_labels = {
        "1_preprocessing":  "Preprocessing (PIL, optimize, segment)",
        "2_glm_ocr_full":   "GLM-OCR full page",
        "3_glm_ocr_header": "GLM-OCR header crop (+ smart fallback)",
        "4_ocr_parser":     "OCR parser (regex, no Tesseract)",
        "6_llm_engine":     "Full engine (LLM scan)",
    }
    print(f"\n  {'Stage':<42} {'Time':>8}  {'% of total':>10}")
    print(f"  {'-'*65}")
    for key, label in stage_labels.items():
        t_val = timings.get(key, 0)
        pct = (t_val / total_elapsed * 100) if total_elapsed else 0
        print(f"  {label:<42} {hms(t_val):>8}  {pct:>9.1f}%")
    print(f"  {'-'*65}")
    print(f"  {'TOTAL (wall clock)':<42} {hms(total_elapsed):>8}  {'100.0%':>10}")
    print(f"\n  scan_invoice() time (production estimate): {hms(timings.get('6_llm_engine',0))}")
    print(f"  Diagnostic overhead (stages 1-4):          {hms(total_elapsed - timings.get('6_llm_engine',0))}")
    print(f"\n{SEP}\n  DONE\n{SEP}")

if __name__ == "__main__":
    main()
