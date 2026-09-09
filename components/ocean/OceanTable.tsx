"use client";

import { useMemo, useState } from "react";

import { formatP, formatSlope } from "@/lib/ocean";

export interface OceanRow {
  areaNo: string;
  areaName: string;
  region: string;
  slope: number;
  p: number;
  nYears: number;
  firstYear: number;
  lastYear: number;
  lastMean: number;
  firstMean: number;
  normal: number | null;
  spark: string;
  long: boolean;
}

type SortKey = "slope" | "name" | "region" | "normal";

const SPARK_W = 132;
const SPARK_H = 26;

export function OceanTable({ rows, regions }: { rows: OceanRow[]; regions: string[] }) {
  const [sort, setSort] = useState<SortKey>("slope");
  const [region, setRegion] = useState<string>("");
  const [longOnly, setLongOnly] = useState(true);

  const shown = useMemo(() => {
    let out = rows.filter((r) => (region ? r.region === region : true));
    if (longOnly) out = out.filter((r) => r.long);
    const cmp: Record<SortKey, (a: OceanRow, b: OceanRow) => number> = {
      slope: (a, b) => b.slope - a.slope,
      name: (a, b) => a.areaNo.localeCompare(b.areaNo),
      region: (a, b) => a.region.localeCompare(b.region) || b.slope - a.slope,
      normal: (a, b) => (a.normal ?? 99) - (b.normal ?? 99),
    };
    return [...out].sort(cmp[sort]);
  }, [rows, sort, region, longOnly]);

  return (
    <>
      <div className="controls">
        <label>
          並び
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
            <option value="slope">上がり方が大きい順</option>
            <option value="normal">平年水温が低い順</option>
            <option value="region">地域別</option>
            <option value="name">海域番号順</option>
          </select>
        </label>
        <label>
          地域
          <select value={region} onChange={(e) => setRegion(e.target.value)}>
            <option value="">すべて</option>
            {regions.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={longOnly}
            onChange={(e) => setLongOnly(e.target.checked)}
          />
          1982 年からの海域だけ
        </label>
        <span className="count" data-testid="ocean-count">
          {shown.length} / {rows.length} 海域
        </span>
      </div>

      <div className="table-scroll">
        <table className="ocean">
          <thead>
            <tr>
              <th>海域</th>
              <th>地域</th>
              <th className="num">平年水温</th>
              <th>年平均水温の推移</th>
              <th className="num">上がり方</th>
              <th className="num">p</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.areaNo}>
                <td>
                  <span className="areaname">{r.areaName}</span>
                  <span className="areano">{r.areaNo}</span>
                </td>
                <td className="region">{r.region}</td>
                <td className="num">{r.normal === null ? "—" : `${r.normal.toFixed(1)}℃`}</td>
                <td className="sparkcell">
                  <svg
                    viewBox={`0 0 ${SPARK_W} ${SPARK_H}`}
                    width={SPARK_W}
                    height={SPARK_H}
                    role="img"
                    aria-label={`${r.firstYear}年 ${r.firstMean.toFixed(1)}℃ から ${r.lastYear}年 ${r.lastMean.toFixed(1)}℃`}
                  >
                    <path d={r.spark} fill="none" stroke="currentColor" strokeWidth="1.2" />
                  </svg>
                  <span className="ends">
                    {r.firstYear}–{r.lastYear}
                  </span>
                </td>
                <td className={`num slope ${r.slope > 0 ? "up" : "down"}`}>
                  {formatSlope(r.slope)}
                </td>
                <td className="num p">{formatP(r.p)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown.length === 0 ? <p className="hint">条件に合う海域が無い</p> : null}
    </>
  );
}
