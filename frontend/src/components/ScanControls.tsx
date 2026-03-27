import type { ScanMode } from "../types/scan.ts";
import type { ChangeEvent } from "react";

interface ScanControlsProps {
  mode: ScanMode;
  onModeChange: (mode: ScanMode) => void;
  debug: boolean;
  onDebugChange: (debug: boolean) => void;
  disabled?: boolean;
}

const MODE_LABELS: Record<ScanMode, string> = {
  light: "Light -- fast, lower accuracy",
  normal: "Normal -- balanced",
  heavy: "Heavy -- thorough, highest accuracy",
};

export default function ScanControls({
  mode,
  onModeChange,
  debug,
  onDebugChange,
  disabled = false,
}: ScanControlsProps) {
  const handleModeChange = (e: ChangeEvent<HTMLSelectElement>) => {
    onModeChange(e.target.value as ScanMode);
  };

  const handleDebugChange = (e: ChangeEvent<HTMLInputElement>) => {
    onDebugChange(e.target.checked);
  };

  return (
    <div className="scan-controls">
      <div className="scan-controls__field">
        <label htmlFor="scan-mode" className="scan-controls__label">
          Scan Mode
        </label>
        <select
          id="scan-mode"
          className="scan-controls__select"
          value={mode}
          onChange={handleModeChange}
          disabled={disabled}
        >
          {(Object.keys(MODE_LABELS) as ScanMode[]).map((m) => (
            <option key={m} value={m}>
              {MODE_LABELS[m]}
            </option>
          ))}
        </select>
      </div>

      <div className="scan-controls__field">
        <label className="scan-controls__checkbox-label">
          <input
            type="checkbox"
            checked={debug}
            onChange={handleDebugChange}
            disabled={disabled}
          />
          Debug Mode
        </label>
      </div>
    </div>
  );
}
