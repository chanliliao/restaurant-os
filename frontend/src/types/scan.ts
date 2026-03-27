/** Scan mode: controls cost vs accuracy tradeoff */
export type ScanMode = "light" | "normal" | "heavy";

/** Individual line item on an invoice */
export interface LineItem {
  name: string;
  quantity: number;
  unit: string;
  unit_price: number;
  total: number;
  confidence: number;
}

/** Full scan response from the backend API */
export interface ScanResponse {
  supplier: string;
  date: string;
  invoice_number: string;
  items: LineItem[];
  subtotal: number;
  tax: number;
  total: number;
  confidence: Record<string, number>;
  inference_sources: Record<string, string>;
  scan_metadata: {
    mode: ScanMode;
    scans_performed: number;
    tiebreaker_triggered: boolean;
    math_validation_triggered: boolean;
    api_calls: number;
    models_used: string[];
    preprocessing: Record<string, unknown>;
  };
}

/** Parameters sent with a scan request */
export interface ScanRequest {
  image: File;
  mode: ScanMode;
  debug: boolean;
}
