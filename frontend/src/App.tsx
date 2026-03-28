import { useState, useCallback, useRef } from "react";
import DropZone from "./components/DropZone.tsx";
import ScanControls from "./components/ScanControls.tsx";
import InvoiceForm from "./components/InvoiceForm.tsx";
import ItemsTable from "./components/ItemsTable.tsx";
import { scanInvoice, confirmScan } from "./services/api.ts";
import type { ScanMode, ScanResponse, FieldCorrection } from "./types/scan.ts";
import "./styles/app.css";

export default function App() {
  const [mode, setMode] = useState<ScanMode>("normal");
  const [debug, setDebug] = useState(false);
  const [result, setResult] = useState<ScanResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);

  const headerCorrections = useRef<FieldCorrection[]>([]);
  const itemCorrections = useRef<FieldCorrection[]>([]);

  const handleFileSelected = useCallback(
    async (file: File) => {
      setLoading(true);
      setError(null);
      setResult(null);
      setConfirmed(false);
      setFileName(file.name);
      headerCorrections.current = [];
      itemCorrections.current = [];

      try {
        const response = await scanInvoice(file, mode, debug);
        setResult(response);
      } catch (err: unknown) {
        if (err instanceof Error) {
          setError(err.message);
        } else {
          setError("An unexpected error occurred while scanning.");
        }
      } finally {
        setLoading(false);
      }
    },
    [mode, debug]
  );

  const handleHeaderCorrections = useCallback((corrections: FieldCorrection[]) => {
    headerCorrections.current = corrections;
  }, []);

  const handleItemCorrections = useCallback((corrections: FieldCorrection[]) => {
    itemCorrections.current = corrections;
  }, []);

  const handleConfirm = useCallback(async () => {
    if (!result) return;

    setConfirming(true);
    setError(null);

    try {
      const allCorrections = [...headerCorrections.current, ...itemCorrections.current];
      await confirmScan({
        scan_result: result,
        corrections: allCorrections,
        confirmed_at: new Date().toISOString(),
      });
      setConfirmed(true);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("An unexpected error occurred while confirming.");
      }
    } finally {
      setConfirming(false);
    }
  }, [result]);

  return (
    <div className="app">
      <header className="app__header">
        <h1 className="app__title">SmartScanner</h1>
        <p className="app__subtitle">AI-powered restaurant invoice scanner</p>
      </header>

      <main className="app__main">
        <ScanControls
          mode={mode}
          onModeChange={setMode}
          debug={debug}
          onDebugChange={setDebug}
          disabled={loading}
        />

        <DropZone onFileSelected={handleFileSelected} disabled={loading} />

        {loading && (
          <div className="app__status">
            <p className="app__loading">Scanning {fileName}...</p>
          </div>
        )}

        {error && (
          <div className="app__status">
            <p className="app__error">Error: {error}</p>
          </div>
        )}

        {result && !confirmed && (
          <div className="app__result">
            <h2 className="app__result-title">
              Scan Result {fileName ? `(${fileName})` : ""}
            </h2>

            <div className="app__result-body">
              <div className="app__legend">
                <span className="legend-item field--low-confidence">Low confidence</span>
                <span className="legend-item field--inferred">Inferred</span>
                <span className="legend-item field--changed">Edited</span>
              </div>

              <InvoiceForm
                scanResult={result}
                onCorrectionsChange={handleHeaderCorrections}
              />

              <ItemsTable
                items={result.items}
                onCorrectionsChange={handleItemCorrections}
              />

              <div className="app__actions">
                <button
                  type="button"
                  className="app__confirm-btn"
                  onClick={handleConfirm}
                  disabled={confirming}
                >
                  {confirming ? "Confirming..." : "Confirm All"}
                </button>
              </div>
            </div>
          </div>
        )}

        {confirmed && (
          <div className="app__status app__status--success">
            <p className="app__success">Invoice confirmed successfully.</p>
          </div>
        )}
      </main>
    </div>
  );
}
