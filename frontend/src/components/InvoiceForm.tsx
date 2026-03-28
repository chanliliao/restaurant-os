import { useState, useCallback } from "react";
import type { ScanResponse, FieldCorrection } from "../types/scan.ts";

type HeaderField = "supplier" | "date" | "invoice_number" | "subtotal" | "tax" | "total";

const HEADER_FIELDS: { key: HeaderField; label: string; type: string }[] = [
  { key: "supplier", label: "Supplier", type: "text" },
  { key: "date", label: "Date", type: "text" },
  { key: "invoice_number", label: "Invoice #", type: "text" },
  { key: "subtotal", label: "Subtotal", type: "number" },
  { key: "tax", label: "Tax", type: "number" },
  { key: "total", label: "Total", type: "number" },
];

interface Props {
  scanResult: ScanResponse;
  onCorrectionsChange: (corrections: FieldCorrection[]) => void;
}

export default function InvoiceForm({ scanResult, onCorrectionsChange }: Props) {
  const [values, setValues] = useState<Record<HeaderField, string>>(() => {
    const init: Record<string, string> = {};
    for (const f of HEADER_FIELDS) {
      init[f.key] = String(scanResult[f.key]);
    }
    return init as Record<HeaderField, string>;
  });

  const [changed, setChanged] = useState<Set<HeaderField>>(new Set());

  const handleChange = useCallback(
    (field: HeaderField, newValue: string) => {
      setValues((prev) => ({ ...prev, [field]: newValue }));

      const originalValue = String(scanResult[field]);
      const isChanged = newValue !== originalValue;

      setChanged((prev) => {
        const next = new Set(prev);
        if (isChanged) {
          next.add(field);
        } else {
          next.delete(field);
        }
        return next;
      });

      // Build corrections list
      const updatedValues = { ...values, [field]: newValue };
      const corrections: FieldCorrection[] = [];
      for (const f of HEADER_FIELDS) {
        const orig = String(scanResult[f.key]);
        const curr = f.key === field ? newValue : updatedValues[f.key];
        if (curr !== orig) {
          corrections.push({
            field: f.key,
            original_value: f.type === "number" ? Number(orig) : orig,
            corrected_value: f.type === "number" ? Number(curr) : curr,
          });
        }
      }
      onCorrectionsChange(corrections);
    },
    [scanResult, values, onCorrectionsChange]
  );

  const getFieldClass = (field: HeaderField): string => {
    if (changed.has(field)) return "field--changed";
    const confidence = scanResult.confidence[field] ?? 100;
    if (confidence < 60) return "field--low-confidence";
    const source = scanResult.inference_sources[field] ?? "scanned";
    if (source !== "scanned") return "field--inferred";
    return "";
  };

  return (
    <div className="invoice-form">
      <h3 className="invoice-form__title">Invoice Details</h3>
      <div className="invoice-form__grid">
        {HEADER_FIELDS.map((f) => {
          const confidence = scanResult.confidence[f.key] ?? 100;
          const source = scanResult.inference_sources[f.key] ?? "scanned";
          return (
            <div key={f.key} className="invoice-form__field">
              <label className="invoice-form__label" htmlFor={`field-${f.key}`}>
                {f.label}
                <span className={`confidence-badge ${confidence < 60 ? "confidence-badge--low" : ""}`}>
                  {confidence}%
                </span>
                {source !== "scanned" && (
                  <span className="source-badge">{source}</span>
                )}
              </label>
              <input
                id={`field-${f.key}`}
                className={`invoice-form__input ${getFieldClass(f.key)}`}
                type={f.type}
                value={values[f.key]}
                onChange={(e) => handleChange(f.key, e.target.value)}
                step={f.type === "number" ? "0.01" : undefined}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
