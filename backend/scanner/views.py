from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework import status
from scanner.serializers import ScanRequestSerializer

@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def scan_invoice(request):
    serializer = ScanRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    mode = serializer.validated_data.get("mode", "normal")
    placeholder_result = {
        "supplier": "Placeholder Supplier",
        "date": "2026-01-01",
        "invoice_number": "INV-0000",
        "items": [{"name": "Sample Item", "qty": 1, "unit": "ea", "price": 0.00}],
        "subtotal": 0.00,
        "tax": 0.00,
        "total": 0.00,
        "confidence": {"supplier": 0, "date": 0, "invoice_number": 0, "items.0.name": 0, "items.0.qty": 0, "items.0.price": 0, "subtotal": 0, "tax": 0, "total": 0},
        "inference_sources": {},
        "scan_metadata": {"mode": mode, "scan_passes": 0, "tiebreaker_triggered": False, "math_validation_triggered": False, "api_calls": {"sonnet": 0, "opus": 0}},
    }
    return Response(placeholder_result)
