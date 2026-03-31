import { useState, useEffect } from "react";
import { getQuota } from "../services/api.ts";
import type { QuotaResponse } from "../types/scan.ts";

interface QuotaBarProps {
  mode: string;
  refreshKey: number;
}

export default function QuotaBar({ mode, refreshKey }: QuotaBarProps) {
  const [quota, setQuota] = useState<QuotaResponse | null>(null);

  useEffect(() => {
    if (mode !== "light") return;
    getQuota().then(setQuota).catch(() => {});
  }, [mode, refreshKey]);

  if (mode !== "light" || !quota) return null;

  const pct = (quota.used_today / quota.daily_limit) * 100;
  const color =
    pct >= 95 ? "#dc2626" : pct >= 80 ? "#d97706" : "#16a34a";

  return (
    <div className="quota-bar">
      <div className="quota-bar__info">
        <span className="quota-bar__label">Gemini Free Tier</span>
        <span className="quota-bar__count">
          {quota.used_today} / {quota.daily_limit} calls today
        </span>
        <span className="quota-bar__remaining" style={{ color }}>
          {quota.remaining} remaining
        </span>
      </div>
      <div className="quota-bar__track">
        <div
          className="quota-bar__fill"
          style={{ width: `${Math.min(pct, 100)}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}
