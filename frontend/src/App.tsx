import { useState, useCallback, useRef } from "react";
import DropZone from "./components/DropZone.tsx";
import ScanControls from "./components/ScanControls.tsx";
import ResultTabs from "./components/ResultTabs.tsx";
import Dashboard from "./components/Dashboard.tsx";
import { scanInvoice, confirmScan } from "./services/api.ts";
import type { ScanMode, ScanTab, FieldCorrection } from "./types/scan.ts";
import "./styles/app.css";

let nextTabId = 0;

export default function App() {
  const [mode, setMode] = useState<ScanMode>("normal");
  const [debug, setDebug] = useState(false);
  const [tabs, setTabs] = useState<ScanTab[]>([]);
  const [activeTab, setActiveTab] = useState(0);
  const [scanning, setScanning] = useState(false);
  const [showDashboard, setShowDashboard] = useState(false);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  // Per-tab corrections stored by tab id
  const headerCorrections = useRef<Record<string, FieldCorrection[]>>({});
  const itemCorrections = useRef<Record<string, FieldCorrection[]>>({});

  const processFiles = useCallback(
    async (files: File[]) => {
      // Create tab entries for all files
      const newTabs: ScanTab[] = files.map((f) => ({
        id: `tab-${++nextTabId}`,
        filename: f.name,
        status: "scanning" as const,
        confirmed: false,
      }));

      setTabs((prev) => {
        const updated = [...prev, ...newTabs];
        // Activate the first new tab
        setActiveTab(updated.length - newTabs.length);
        return updated;
      });
      setScanning(true);

      // Process sequentially
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const tabId = newTabs[i].id;

        try {
          const result = await scanInvoice(file, mode, debug);
          setTabs((prev) =>
            prev.map((t) =>
              t.id === tabId ? { ...t, status: "done" as const, result } : t
            )
          );
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : "Scan failed";
          setTabs((prev) =>
            prev.map((t) =>
              t.id === tabId ? { ...t, status: "error" as const, error: msg } : t
            )
          );
        }
      }

      setScanning(false);
    },
    [mode, debug]
  );

  const handleHeaderCorrections = useCallback(
    (tabId: string, corrections: FieldCorrection[]) => {
      headerCorrections.current[tabId] = corrections;
    },
    []
  );

  const handleItemCorrections = useCallback(
    (tabId: string, corrections: FieldCorrection[]) => {
      itemCorrections.current[tabId] = corrections;
    },
    []
  );

  const handleConfirm = useCallback(
    async (tabId: string) => {
      const tab = tabs.find((t) => t.id === tabId);
      if (!tab?.result) return;

      setConfirmingId(tabId);
      try {
        const allCorrections = [
          ...(headerCorrections.current[tabId] ?? []),
          ...(itemCorrections.current[tabId] ?? []),
        ];
        await confirmScan({
          scan_result: tab.result,
          corrections: allCorrections,
          confirmed_at: new Date().toISOString(),
        });
        setTabs((prev) =>
          prev.map((t) => (t.id === tabId ? { ...t, confirmed: true } : t))
        );
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Confirm failed";
        setTabs((prev) =>
          prev.map((t) =>
            t.id === tabId ? { ...t, error: msg } : t
          )
        );
      } finally {
        setConfirmingId(null);
      }
    },
    [tabs]
  );

  return (
    <div className="app">
      <header className="app__header">
        <h1 className="app__title">SmartScanner</h1>
        <p className="app__subtitle">AI-powered restaurant invoice scanner</p>
        <button
          type="button"
          className="app__dashboard-toggle"
          onClick={() => setShowDashboard((v) => !v)}
        >
          {showDashboard ? "Close Dashboard" : "Dashboard"}
        </button>
      </header>

      <main className="app__main">
        <Dashboard visible={showDashboard} />

        {!showDashboard && (
          <>
            <ScanControls
              mode={mode}
              onModeChange={setMode}
              debug={debug}
              onDebugChange={setDebug}
              disabled={scanning}
            />

            <DropZone onFilesSelected={processFiles} disabled={scanning} />

            <ResultTabs
              tabs={tabs}
              activeTab={activeTab}
              onTabChange={setActiveTab}
              onHeaderCorrectionsChange={handleHeaderCorrections}
              onItemCorrectionsChange={handleItemCorrections}
              onConfirm={handleConfirm}
              confirmingId={confirmingId}
            />
          </>
        )}
      </main>
    </div>
  );
}
