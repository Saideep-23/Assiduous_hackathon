import React, { useState } from "react";

export function SensitisationTable({
  waccAxis,
  tgAxis,
  grid,
}: {
  waccAxis: number[];
  tgAxis: number[];
  grid: number[][];
}) {
  const [hi, setHi] = useState<[number, number] | null>(null);

  return (
    <div className="sens-grid-wrap">
      <table className="sens-table">
        <thead>
          <tr>
            <th>WACC \ <em>g</em></th>
            {tgAxis.map((g, j) => (
              <th key={j}>{(g * 100).toFixed(1)}%</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {grid.map((row, i) => (
            <tr key={i}>
              <th>{(waccAxis[i] * 100).toFixed(2)}%</th>
              {row.map((cell, j) => {
                const isRow = hi !== null && hi[0] === i;
                const isCol = hi !== null && hi[1] === j;
                const isCell = hi !== null && hi[0] === i && hi[1] === j;
                return (
                  <td
                    key={j}
                    onMouseEnter={() => setHi([i, j])}
                    onMouseLeave={() => setHi(null)}
                    title={`WACC ${(waccAxis[i] * 100).toFixed(2)}% · g ${(tgAxis[j] * 100).toFixed(1)}% → $${cell}`}
                    className={[isRow && !isCell ? "row-hi" : "", isCol && !isCell ? "col-hi" : "", isCell ? "cell-hi" : ""]
                      .filter(Boolean)
                      .join(" ")}
                  >
                    {cell}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
