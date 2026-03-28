import logging

from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework import status

from scanner.serializers import ScanRequestSerializer, ConfirmRequestSerializer
from scanner.scanning.engine import scan_invoice

logger = logging.getLogger(__name__)


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
    corrections_count = len(validated["corrections"])
    confirmed_at = validated["confirmed_at"].isoformat()

    logger.info(
        "Scan confirmed with %d correction(s) at %s",
        corrections_count,
        confirmed_at,
    )

    return Response({
        "status": "confirmed",
        "corrections_count": corrections_count,
        "confirmed_at": confirmed_at,
    })
