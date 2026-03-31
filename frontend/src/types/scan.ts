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
    api_calls: Record<string, number>;
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

/** Tracks a single field correction made by the user */
export interface FieldCorrection {
  field: string;
  original_value: string | number;
  corrected_value: string | number;
}

/** Payload sent to POST /api/confirm/ */
export interface ConfirmRequest {
  scan_result: ScanResponse;
  corrections: FieldCorrection[];
  confirmed_at: string;
}

/** Response from POST /api/confirm/ */
export interface ConfirmResponse {
  status: string;
  corrections_count: number;
  confirmed_at: string;
}

/** A single tab in the multi-scan result view */
export interface ScanTab {
  id: string;
  filename: string;
  status: "scanning" | "done" | "error";
  result?: ScanResponse;
  error?: string;
  confirmed: boolean;
}

/** Gemini quota status from GET /api/quota/ */
export interface QuotaResponse {
  used_today: number;
  daily_limit: number;
  remaining: number;
  per_minute_limit: number;
}

/** Aggregated stats response from GET /api/stats/ */
export interface StatsResponse {
  accuracy: {
    total_scans: number;
    average_accuracy: number;
    total_corrections: number;
    by_mode: Record<string, { count: number; average_accuracy: number; total_corrections: number }>;
    by_supplier: Record<string, { count: number; average_accuracy: number; total_corrections: number }>;
  };
  api_usage: {
    total_scans: number;
    totals: Record<string, number>;
    by_mode: Record<string, { count: number; totals: Record<string, number> }>;
  };
}
