import axios from "axios";
import type { ScanMode, ScanResponse, ConfirmRequest, ConfirmResponse, StatsResponse, QuotaResponse } from "../types/scan.ts";

const client = axios.create({
  baseURL: "/api",
  headers: {
    Accept: "application/json",
  },
});

/**
 * Send an invoice image to the backend for scanning.
 * Uses multipart/form-data to upload the image file along with scan parameters.
 */
export async function scanInvoice(
  file: File,
  mode: ScanMode = "normal",
  debug: boolean = false
): Promise<ScanResponse> {
  const formData = new FormData();
  formData.append("image", file);
  formData.append("mode", mode);

  const params = debug ? "?debug=1" : "";
  const response = await client.post<ScanResponse>(`/scan/${params}`, formData, {
    headers: {
      "Content-Type": "multipart/form-data",
    },
  });

  return response.data;
}

/**
 * Confirm a scan result, optionally with user corrections.
 */
export async function confirmScan(
  data: ConfirmRequest
): Promise<ConfirmResponse> {
  const response = await client.post<ConfirmResponse>("/confirm/", data);
  return response.data;
}

/**
 * Fetch aggregated accuracy and API usage stats.
 */
export async function getStats(): Promise<StatsResponse> {
  const response = await client.get<StatsResponse>("/stats/");
  return response.data;
}

/**
 * Fetch Gemini free tier quota status (light mode only).
 */
export async function getQuota(): Promise<QuotaResponse> {
  const response = await client.get<QuotaResponse>("/quota/");
  return response.data;
}
