from django.urls import path
from scanner.views import scan_invoice_view, confirm_scan_view, stats_view

urlpatterns = [
    path("scan/", scan_invoice_view, name="scan-invoice"),
    path("confirm/", confirm_scan_view, name="confirm-scan"),
    path("stats/", stats_view, name="stats"),
]
