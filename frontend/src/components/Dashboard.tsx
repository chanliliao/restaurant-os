import { useState, useEffect } from "react";
import { getStats } from "../services/api.ts";
import type { StatsResponse } from "../types/scan.ts";

interface DashboardProps {
  visible: boolean;
}

export default function Dashboard({ visible }: DashboardProps) {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!visible) return;
    setLoading(true);
    setError(null);
    getStats()
      .then(setStats)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to load stats");
      })
      .finally(() => setLoading(false));
  }, [visible]);

  if (!visible) return null;

  if (loading) {
    return (
      <div className="dashboard">
        <p className="app__loading">Loading stats...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="dashboard">
        <p className="app__error">Error: {error}</p>
      </div>
    );
  }

  if (!stats || stats.accuracy.total_scans === 0) {
    return (
      <div className="dashboard">
        <p className="dashboard__empty">No scan data yet. Scan some invoices first.</p>
      </div>
    );
  }

  const { accuracy, api_usage } = stats;

  return (
    <div className="dashboard">
      <h2 className="dashboard__title">Dashboard</h2>

      <div className="dashboard__cards">
        <div className="dashboard__card">
          <span className="dashboard__card-label">Total Scans</span>
          <span className="dashboard__card-value">{accuracy.total_scans}</span>
        </div>
        <div className="dashboard__card">
          <span className="dashboard__card-label">Avg Accuracy</span>
          <span className="dashboard__card-value">
            {(accuracy.average_accuracy * 100).toFixed(1)}%
          </span>
        </div>
        <div className="dashboard__card">
          <span className="dashboard__card-label">Total Corrections</span>
          <span className="dashboard__card-value">{accuracy.total_corrections}</span>
        </div>
      </div>

      {Object.keys(accuracy.by_mode).length > 0 && (
        <div className="dashboard__section">
          <h3 className="dashboard__section-title">By Mode</h3>
          <table className="dashboard__table">
            <thead>
              <tr>
                <th>Mode</th>
                <th>Scans</th>
                <th>Avg Accuracy</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(accuracy.by_mode).map(([mode, data]) => (
                <tr key={mode}>
                  <td>{mode}</td>
                  <td>{data.count}</td>
                  <td>{(data.average_accuracy * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {api_usage.totals && Object.keys(api_usage.totals).length > 0 && (
        <div className="dashboard__section">
          <h3 className="dashboard__section-title">API Usage</h3>
          <div className="dashboard__cards">
            {Object.entries(api_usage.totals).map(([model, count]) => (
              <div key={model} className="dashboard__card">
                <span className="dashboard__card-label">{model}</span>
                <span className="dashboard__card-value">{count} calls</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
