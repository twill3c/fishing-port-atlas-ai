"use client";

import { useEffect, useState } from "react";

import { DEPTH_BINS } from "@/lib/tsunamiArea";

interface TsunamiMeta {
  disclaimer: string;
  attribution: string;
  source_page: string;
}

/**
 * 地図に重ねた津波浸水想定の区域の面の凡例(SPEC G-34)。
 *
 * - 塗りは区間の下限による 5 段。区分の刻みは都道府県・年度で違うので**束ねている**と書く
 * - 但し書きと出典は配信メタから読む。読めないときも、公式の防災情報を見るよう求める一文だけは出す
 */
export function TsunamiAreaLegend() {
  const [meta, setMeta] = useState<TsunamiMeta | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/data/hazards/tsunami-meta.json")
      .then((res) => (res.ok ? res.json() : null))
      .then((json: TsunamiMeta | null) => {
        if (!cancelled) setMeta(json);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="map-legend map-legend--area" data-testid="tsunami-area-legend">
      <strong>津波浸水想定(最大浸水深)</strong>
      <ul>
        {DEPTH_BINS.map((bin) => (
          <li key={bin.label}>
            <span className="swatch swatch--square" style={{ background: bin.color }} aria-hidden />
            {bin.label}
          </li>
        ))}
      </ul>
      <p className="map-legend__note">
        区分の刻みは都道府県・年度で違うので、区間の下限で 5 段に束ねた。正確な区分は「防災」タブの表で読む。
        輪は代表点から半径 100 / 200 / 500 m。
      </p>
      <p className="map-legend__note">
        {meta
          ? meta.disclaimer
          : "避難の判断には、自治体・気象庁・国土交通省の最新の公式な防災情報を使うこと。"}
      </p>
      <p className="map-legend__note">
        {meta ? meta.attribution : "出典: 国土交通省「国土数値情報(津波浸水想定データ)」を加工して作成"}
      </p>
    </div>
  );
}
