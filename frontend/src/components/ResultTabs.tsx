import type { ScanTab, FieldCorrection } from "../types/scan.ts";
import ScanStats from "./ScanStats.tsx";
import InvoiceForm from "./InvoiceForm.tsx";
import ItemsTable from "./ItemsTable.tsx";

interface ResultTabsProps {
  tabs: ScanTab[];
  activeTab: number;
  onTabChange: (idx: number) => void;
  onHeaderCorrectionsChange: (tabId: string, corrections: FieldCorrection[]) => void;
  onItemCorrectionsChange: (tabId: string, corrections: FieldCorrection[]) => void;
  onConfirm: (tabId: string) => void;
  confirmingId: string | null;
}

export default function ResultTabs({
  tabs,
  activeTab,
  onTabChange,
  onHeaderCorrectionsChange,
  onItemCorrectionsChange,
  onConfirm,
  confirmingId,
}: ResultTabsProps) {
  if (tabs.length === 0) return null;

  const current = tabs[activeTab];

  return (
    <div className="result-tabs">
      <div className="result-tabs__bar">
        {tabs.map((tab, idx) => {
          const cls = [
            "result-tabs__tab",
            idx === activeTab ? "result-tabs__tab--active" : "",
            `result-tabs__tab--${tab.status}`,
            tab.confirmed ? "result-tabs__tab--confirmed" : "",
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <button
              key={tab.id}
              type="button"
              className={cls}
              onClick={() => onTabChange(idx)}
            >
              <span className="result-tabs__tab-name">{tab.filename}</span>
              <span className="result-tabs__tab-status">
                {tab.confirmed ? " \u2713" : tab.status === "scanning" ? " ..." : tab.status === "error" ? " !" : ""}
              </span>
            </button>
          );
        })}
      </div>

      <div className="result-tabs__content">
        {current.status === "scanning" && (
          <div className="app__status">
            <p className="app__loading">Scanning {current.filename}...</p>
          </div>
        )}

        {current.status === "error" && (
          <div className="app__status">
            <p className="app__error">Error: {current.error}</p>
          </div>
        )}

        {current.status === "done" && current.result && (
          <div className="app__result-body">
            <ScanStats metadata={current.result.scan_metadata} />

            <div className="app__legend">
              <span className="legend-item field--low-confidence">Low confidence</span>
              <span className="legend-item field--inferred">Inferred</span>
              <span className="legend-item field--changed">Edited</span>
            </div>

            <InvoiceForm
              scanResult={current.result}
              onCorrectionsChange={(c) => onHeaderCorrectionsChange(current.id, c)}
            />

            <ItemsTable
              items={current.result.items}
              onCorrectionsChange={(c) => onItemCorrectionsChange(current.id, c)}
            />

            {!current.confirmed && (
              <div className="app__actions">
                <button
                  type="button"
                  className="app__confirm-btn"
                  onClick={() => onConfirm(current.id)}
                  disabled={confirmingId === current.id}
                >
                  {confirmingId === current.id ? "Confirming..." : "Confirm"}
                </button>
              </div>
            )}

            {current.confirmed && (
              <div className="app__status app__status--success">
                <p className="app__success">Invoice confirmed.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
