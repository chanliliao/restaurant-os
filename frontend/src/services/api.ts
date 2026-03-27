import axios from "axios";
import type { ScanMode, ScanResponse } from "../types/scan.ts";

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
  _debug: boolean = false
): Promise<ScanResponse> {
  const formData = new FormData();
  formData.append("image", file);
  formData.append("mode", mode);

  const response = await client.post<ScanResponse>("/scan/", formData, {
    headers: {
      "Content-Type": "multipart/form-data",
    },
  });

  return response.data;
}
