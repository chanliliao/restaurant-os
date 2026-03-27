import { useState, useCallback } from "react";
import DropZone from "./components/DropZone.tsx";
import ScanControls from "./components/ScanControls.tsx";
import { scanInvoice } from "./services/api.ts";
import type { ScanMode, ScanResponse } from "./types/scan.ts";
import "./styles/app.css";

export default function App() {
  const [mode, setMode] = useState<ScanMode>("normal");
  const [debug, setDebug] = useState(false);
  const [result, setResult] = useState<ScanResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);

  const handleFileSelected = useCallback(
    async (file: File) => {
      setLoading(true);
      setError(null);
      setResult(null);
      setFileName(file.name);

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

        {result && (
          <div className="app__result">
            <h2 className="app__result-title">
              Scan Result {fileName ? `(${fileName})` : ""}
            </h2>
            <pre className="app__result-json">
              {JSON.stringify(result, null, 2)}
            </pre>
          </div>
        )}
      </main>
    </div>
  );
}
