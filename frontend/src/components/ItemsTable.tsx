import { useState, useCallback } from "react";
import type { LineItem, FieldCorrection } from "../types/scan.ts";

type ItemField = "name" | "quantity" | "unit" | "unit_price" | "total";

const COLUMNS: { key: ItemField; label: string; type: string }[] = [
  { key: "name", label: "Name", type: "text" },
  { key: "quantity", label: "Qty", type: "number" },
  { key: "unit", label: "Unit", type: "text" },
  { key: "unit_price", label: "Unit Price", type: "number" },
  { key: "total", label: "Total", type: "number" },
];

interface Props {
  items: LineItem[];
  onCorrectionsChange: (corrections: FieldCorrection[]) => void;
}

function makeEmptyItem(): LineItem {
  return { name: "", quantity: 0, unit: "", unit_price: 0, total: 0, confidence: 100 };
}

export default function ItemsTable({ items: initialItems, onCorrectionsChange }: Props) {
  const [items, setItems] = useState<LineItem[]>(() => [...initialItems]);
  const [originalItems] = useState<LineItem[]>(() => [...initialItems]);
  const [changedCells, setChangedCells] = useState<Set<string>>(new Set());

  const buildCorrections = useCallback(
    (currentItems: LineItem[], currentChanged: Set<string>) => {
      const corrections: FieldCorrection[] = [];
      for (const cellKey of currentChanged) {
        const [rowStr, field] = cellKey.split(":");
        const row = Number(rowStr);
        if (row < originalItems.length) {
          const origItem = originalItems[row];
          const currItem = currentItems[row];
          if (origItem && currItem) {
            corrections.push({
              field: `items[${row}].${field}`,
              original_value: origItem[field as ItemField],
              corrected_value: currItem[field as ItemField],
            });
          }
        }
      }
      // Track added rows
      for (let i = originalItems.length; i < currentItems.length; i++) {
        corrections.push({
          field: `items[${i}]`,
          original_value: "",
          corrected_value: `added_row`,
        });
      }
      return corrections;
    },
    [originalItems]
  );

  const handleCellChange = useCallback(
    (rowIndex: number, field: ItemField, value: string) => {
      setItems((prev) => {
        const next = [...prev];
        const item = { ...next[rowIndex] };
        if (field === "quantity" || field === "unit_price" || field === "total") {
          (item as Record<string, unknown>)[field] = Number(value) || 0;
        } else {
          (item as Record<string, unknown>)[field] = value;
        }
        next[rowIndex] = item;

        // Determine changed state
        const cellKey = `${rowIndex}:${field}`;
        setChangedCells((prevChanged) => {
          const nextChanged = new Set(prevChanged);
          if (rowIndex < originalItems.length) {
            const origValue = String(originalItems[rowIndex][field]);
            if (value !== origValue) {
              nextChanged.add(cellKey);
            } else {
              nextChanged.delete(cellKey);
            }
          }
          onCorrectionsChange(buildCorrections(next, nextChanged));
          return nextChanged;
        });

        return next;
      });
    },
    [originalItems, onCorrectionsChange, buildCorrections]
  );

  const addRow = useCallback(() => {
    setItems((prev) => {
      const next = [...prev, makeEmptyItem()];
      onCorrectionsChange(buildCorrections(next, changedCells));
      return next;
    });
  }, [onCorrectionsChange, buildCorrections, changedCells]);

  const removeRow = useCallback(
    (index: number) => {
      setItems((prev) => {
        const next = prev.filter((_, i) => i !== index);
        // Clean up changed cells for removed row and re-index
        const nextChanged = new Set<string>();
        for (const key of changedCells) {
          const [rowStr, field] = key.split(":");
          const row = Number(rowStr);
          if (row < index) {
            nextChanged.add(key);
          } else if (row > index) {
            nextChanged.add(`${row - 1}:${field}`);
          }
        }
        setChangedCells(nextChanged);
        onCorrectionsChange(buildCorrections(next, nextChanged));
        return next;
      });
    },
    [changedCells, onCorrectionsChange, buildCorrections]
  );

  const getCellClass = (rowIndex: number, field: ItemField): string => {
    const cellKey = `${rowIndex}:${field}`;
    if (changedCells.has(cellKey)) return "field--changed";
    if (rowIndex >= originalItems.length) return "field--changed";
    const confidence = originalItems[rowIndex].confidence;
    if (confidence < 60) return "field--low-confidence";
    return "";
  };

  return (
    <div className="items-table">
      <div className="items-table__header">
        <h3 className="items-table__title">Line Items</h3>
        <button type="button" className="items-table__add-btn" onClick={addRow}>
          + Add Row
        </button>
      </div>
      <div className="items-table__wrapper">
        <table className="items-table__table">
          <thead>
            <tr>
              {COLUMNS.map((col) => (
                <th key={col.key}>{col.label}</th>
              ))}
              <th>Conf.</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, rowIndex) => (
              <tr key={rowIndex}>
                {COLUMNS.map((col) => (
                  <td key={col.key} className={getCellClass(rowIndex, col.key)}>
                    <input
                      className="items-table__cell-input"
                      type={col.type}
                      value={item[col.key]}
                      onChange={(e) => handleCellChange(rowIndex, col.key, e.target.value)}
                      step={col.type === "number" ? "0.01" : undefined}
                    />
                  </td>
                ))}
                <td>
                  <span className={`confidence-badge ${item.confidence < 60 ? "confidence-badge--low" : ""}`}>
                    {item.confidence}%
                  </span>
                </td>
                <td>
                  <button
                    type="button"
                    className="items-table__remove-btn"
                    onClick={() => removeRow(rowIndex)}
                    title="Remove row"
                  >
                    x
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
