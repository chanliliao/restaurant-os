import logging

from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework import status

from scanner.memory import (
    JsonSupplierMemory,
    JsonGeneralMemory,
    normalize_supplier_id,
    categorize_corrections,
    apply_corrections,
)
from scanner.serializers import ScanRequestSerializer, ConfirmRequestSerializer
from scanner.scanning.engine import scan_invoice

logger = logging.getLogger(__name__)


def _get_supplier_memory() -> JsonSupplierMemory:
    """Factory for supplier memory store (patchable in tests)."""
    return JsonSupplierMemory()


def _get_general_memory() -> JsonGeneralMemory:
    """Factory for general memory store (patchable in tests)."""
    return JsonGeneralMemory()


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def scan_invoice_view(request):
    serializer = ScanRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    mode = serializer.validated_data.get("mode", "normal")
    debug = request.query_params.get("debug", "").lower() in ("1", "true")
    image_file = serializer.validated_data["image"]

    try:
        image_bytes = image_file.read()
        result = scan_invoice(image_bytes, mode=mode, debug=debug)

        # If the engine returned an error, still return 200 with error in metadata
        # so the frontend can display partial results or error info
        return Response(result)

    except Exception as e:
        logger.error("Unexpected error in scan endpoint: %s", e, exc_info=True)
        return Response(
            {"error": "Internal server error during scan."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@parser_classes([JSONParser])
def confirm_scan_view(request):
    serializer = ConfirmRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    validated = serializer.validated_data
    scan_result = validated["scan_result"]
    corrections = validated["corrections"]
    corrections_count = len(corrections)
    confirmed_at = validated["confirmed_at"].isoformat()

    logger.info(
        "Scan confirmed with %d correction(s) at %s",
        corrections_count,
        confirmed_at,
    )

    # Apply corrections to get the canonical "truth" result
    corrected_scan = apply_corrections(scan_result, corrections)

    # Categorize errors for learning
    categorized = categorize_corrections(corrections)

    # Attach categorized corrections to the corrected scan for storage
    corrected_scan["corrections"] = categorized

    # Always update general memory
    general_memory = _get_general_memory()
    general_memory.update_from_scan(corrected_scan)

    # Update supplier memory if supplier name is present and valid
    supplier_name = corrected_scan.get("supplier")
    if supplier_name and isinstance(supplier_name, str) and supplier_name.strip():
        try:
            supplier_id = normalize_supplier_id(supplier_name)
            supplier_memory = _get_supplier_memory()
            supplier_memory.save_scan(supplier_id, corrected_scan)
        except ValueError:
            logger.warning("Could not normalize supplier name: %r", supplier_name)

    return Response({
        "status": "confirmed",
        "corrections_count": corrections_count,
        "confirmed_at": confirmed_at,
        "memory_updated": True,
    })
