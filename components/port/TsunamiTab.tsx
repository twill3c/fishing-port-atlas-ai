"use client";

import { useEffect, useState } from "react";

/** export_web.py の _tsunami_section と対応 */
export interface TsunamiSection {
  status: string;
  policy: "redistribute" | "link_only" | "not_provided" | "no_data" | null;
  radii: { radius_m: number; max_rank: string | null; vintage: number | null }[] | null;
  note: string;
}

interface TsunamiMeta {
  disclaimer: string;
  attribution: string;
  source_page: string;
  rank_order: string[];
}

const POLICY_LABEL: Record<string, string> = {
  redistribute: "国土数値情報から加工して表示",
  link_only: "再配布に事前の連絡が要るため載せていない",
  not_provided: "国土数値情報として提供されていない",
  no_data: "津波浸水想定の配布が無い",
};

/**
 * 港の詳細の「防災」タブ(SPEC §7.4 / G-19〜G-22)。
 *
 * - 代表点が区域の内か外かは出さない。半径 100 / 200 / 500 m の最大浸水深区分を並べる
 * - 区域が掛からない半径を「安全」と読める言葉で出さない
 * - 但し書きは配信メタから読み、どの状態でも必ず出す。メタが読めないときも、
 *   公式の防災情報を見るよう求める一文だけは出す(但し書きの無い表示をつくらない)
 */
export function TsunamiTab({ tsunami }: { tsunami: TsunamiSection }) {
  const [meta, setMeta] = useState<TsunamiMeta | null>(null);
  const [metaError, setMetaError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch("/data/hazards/tsunami-meta.json")
      .then((res) => {
        if (!res.ok) throw new Error(String(res.status));
        return res.json();
      })
      .then((json: TsunamiMeta) => {
        if (!cancelled) setMeta(json);
      })
      .catch(() => {
        if (!cancelled) setMetaError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div data-testid="drawer-tsunami">
      <p className="hint" style={{ marginTop: 0 }}>
        津波浸水想定 —{" "}
        {tsunami.policy ? (POLICY_LABEL[tsunami.policy] ?? tsunami.policy) : "未構築"}
      </p>

      {tsunami.radii ? (
        <div className="table-scroll">
          <table className="radii" data-testid="drawer-tsunami-radii">
            <thead>
              <tr>
                <th className="num">代表点からの半径</th>
                <th>円に掛かる区域の最大浸水深</th>
                <th className="num">データの年度</th>
              </tr>
            </thead>
            <tbody>
              {tsunami.radii.map((entry) => (
                <tr key={entry.radius_m}>
                  <td className="num">{entry.radius_m} m</td>
                  <td>
                    {entry.max_rank ?? <span className="badge">区域が掛からない</span>}
                  </td>
                  <td className="num">{entry.vintage ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <p className="layer-row__note">{tsunami.note}</p>

      <p className="status-note" data-testid="drawer-tsunami-disclaimer">
        {meta
          ? meta.disclaimer
          : metaError
            ? "但し書きを読み込めなかった。避難の判断には、自治体・気象庁・国土交通省の最新の公式な防災情報を使うこと。"
            : "但し書きを読み込み中…"}
      </p>
      {meta ? (
        <p className="hint">
          {meta.attribution}(
          <a href={meta.source_page} target="_blank" rel="noreferrer">
            国土数値情報 津波浸水想定
          </a>
          )
        </p>
      ) : null}
    </div>
  );
}
