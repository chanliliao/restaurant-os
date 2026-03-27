from django.urls import path
from scanner.views import scan_invoice_view

urlpatterns = [
    path("scan/", scan_invoice_view, name="scan-invoice"),
]
