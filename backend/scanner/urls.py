from django.urls import path
from scanner.views import scan_invoice

urlpatterns = [
    path("scan/", scan_invoice, name="scan-invoice"),
]
