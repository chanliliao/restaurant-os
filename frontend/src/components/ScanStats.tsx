import type { ScanResponse } from "../types/scan.ts";

interface ScanStatsProps {
  metadata: ScanResponse["scan_metadata"];
}

export default function ScanStats({ metadata }: ScanStatsProps) {
  return (
    <div className="scan-stats">
      <span className="scan-stats__badge scan-stats__badge--mode">
        {metadata.mode}
      </span>
      <span className="scan-stats__badge">
        {metadata.scans_performed} scan{metadata.scans_performed !== 1 ? "s" : ""}
      </span>
      <span className="scan-stats__badge">
        {Object.values(metadata.api_calls).reduce((a, b) => a + b, 0)} API call
        {Object.values(metadata.api_calls).reduce((a, b) => a + b, 0) !== 1 ? "s" : ""}
      </span>
      {metadata.models_used.map((m) => (
        <span key={m} className="scan-stats__badge scan-stats__badge--model">
          {m}
        </span>
      ))}
      {metadata.tiebreaker_triggered && (
        <span className="scan-stats__badge scan-stats__badge--flag">tiebreaker</span>
      )}
      {metadata.math_validation_triggered && (
        <span className="scan-stats__badge scan-stats__badge--flag">math check</span>
      )}
    </div>
  );
}
