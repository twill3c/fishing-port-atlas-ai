"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { PortDrawer } from "@/components/port/PortDrawer";
import {
  PORT_CLASS_COLOR,
  PORT_CLASS_LABEL,
  PORT_CLASS_NOTE,
  PORT_CLASS_ORDER,
  countByClass,
  filterPorts,
  type PortClass,
  type PortMin,
} from "@/lib/ports";

import type { BaseMapId } from "@/components/map/FishingPortMap";

const FishingPortMap = dynamic(
  () => import("@/components/map/FishingPortMap").then((m) => m.FishingPortMap),
  { ssr: false, loading: () => <p className="hint" style={{ padding: "1rem" }}>地図を用意中…</p> },
);

const MAX_LIST = 300;

export function AtlasApp() {
  const [ports, setPorts] = useState<PortMin[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [classes, setClasses] = useState<Set<PortClass>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [baseMap, setBaseMap] = useState<BaseMapId>("pale");
  const [showPoints, setShowPoints] = useState(true);

  useEffect(() => {
    fetch("/data/ports.min.json")
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status}`);
        return res.json();
      })
      .then((rows: PortMin[]) => setPorts(rows))
      .catch((err: Error) => setLoadError(err.message));
  }, []);

  // URL と状態を同期(実装仕様書 §41)。共有したリンクで同じ港が開く。
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const port = params.get("port");
    if (port) setSelected(port);
    const q = params.get("q");
    if (q) setQuery(q);
    const cls = params.get("class");
    if (cls) {
      const wanted = cls.split(",").filter((c): c is PortClass =>
        (PORT_CLASS_ORDER as readonly string[]).includes(c),
      );
      if (wanted.length) setClasses(new Set(wanted));
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams();
    if (selected) params.set("port", selected);
    if (query) params.set("q", query);
    if (classes.size) params.set("class", [...classes].join(","));
    const next = params.toString();
    const url = next ? `?${next}` : window.location.pathname;
    window.history.replaceState(null, "", url);
  }, [selected, query, classes]);

  const filtered = useMemo(
    () => (ports ? filterPorts(ports, { classes, query }) : []),
    [ports, classes, query],
  );
  const totals = useMemo(() => (ports ? countByClass(ports) : null), [ports]);
  const withoutCoords = filtered.filter((p) => p.x === null).length;

  function toggleClass(cls: PortClass) {
    setClasses((prev) => {
      const next = new Set(prev);
      if (next.has(cls)) next.delete(cls);
      else next.add(cls);
      return next;
    });
  }

  return (
    <div className="app">
      <header className="masthead">
        <h1 className="masthead__brand">
          Fishing Port Atlas AI<small>日本の漁港を公開データで眺める</small>
        </h1>
        <div className="masthead__search">
          <label className="visually-hidden" htmlFor="port-search">
            漁港を検索
          </label>
          <input
            id="port-search"
            type="search"
            placeholder="漁港名・読み・都道府県・市町村で検索"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            data-testid="search-input"
          />
        </div>
        <p className="masthead__count" data-testid="result-count">
          {ports ? `${filtered.length.toLocaleString()} / ${ports.length.toLocaleString()} 港` : "読み込み中…"}
        </p>
        <nav className="masthead__nav">
          <a href="/ocean/">海の温度</a>
          <a href="/ai/">AI</a>
          <a href="/data/">出典</a>
          <a href="/methodology/">方法</a>
          <a href="/about/">解説</a>
        </nav>
      </header>

      <div className={selected ? "workspace workspace--with-drawer" : "workspace"}>
        <div className="rail">
          <section className="group">
            <h2 className="group__title">背景地図</h2>
            {(
              [
                ["pale", "地理院 淡色地図"],
                ["std", "地理院 標準地図"],
              ] as const
            ).map(([id, label]) => (
              <label className="layer-row" key={id}>
                <input
                  type="radio"
                  name="basemap"
                  checked={baseMap === id}
                  onChange={() => setBaseMap(id)}
                />
                <span className="layer-row__body">
                  <span className="layer-row__label">{label}</span>
                </span>
              </label>
            ))}
          </section>

          <section className="group">
            <h2 className="group__title">漁港</h2>
            <label className="layer-row">
              <input
                type="checkbox"
                checked={showPoints}
                onChange={(event) => setShowPoints(event.target.checked)}
                data-testid="toggle-points"
              />
              <span className="layer-row__body">
                <span className="layer-row__label">漁港ポイント</span>
                <span className="layer-row__note">
                  座標を持つ港だけを描く。座標が無い港は下の一覧から辿れる
                </span>
              </span>
            </label>
          </section>

          <section className="group">
            <h2 className="group__title">種別で絞る</h2>
            {PORT_CLASS_ORDER.map((cls) => (
              <label className="layer-row" key={cls}>
                <input
                  type="checkbox"
                  checked={classes.has(cls)}
                  onChange={() => toggleClass(cls)}
                  data-testid={`class-${cls}`}
                />
                <span className="layer-row__body">
                  <span className="layer-row__label">
                    <span
                      className="swatch"
                      style={{ background: PORT_CLASS_COLOR[cls] }}
                      aria-hidden
                    />
                    {PORT_CLASS_LABEL[cls]}
                    <span className="layer-row__count">
                      {totals ? totals[cls].toLocaleString() : "—"}
                    </span>
                  </span>
                  <span className="layer-row__note">{PORT_CLASS_NOTE[cls]}</span>
                </span>
              </label>
            ))}
            <p className="hint">
              何も選ばないときは全種別を表示する(全解除で 0 件にはしない)
            </p>
            <div className="button-row">
              <button className="chip" onClick={() => setClasses(new Set())}>
                絞り込みを解除
              </button>
            </div>
          </section>

          <section className="group">
            <h2 className="group__title">
              一覧{withoutCoords > 0 ? `(うち座標なし ${withoutCoords})` : ""}
            </h2>
            {loadError ? (
              <p className="status-note">漁港データを読み込めなかった({loadError})</p>
            ) : null}
            <ul className="result-list" data-testid="result-list">
              {filtered.slice(0, MAX_LIST).map((port) => (
                <li key={port.id}>
                  <button onClick={() => setSelected(port.id)}>
                    {port.n}漁港
                    <span className="result-list__meta">
                      {PORT_CLASS_LABEL[port.c]} ／ {port.p}
                      {port.m}
                      {port.x === null ? (
                        <span className="no-coord">／ 座標なし</span>
                      ) : null}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {filtered.length > MAX_LIST ? (
              <p className="hint">
                先頭 {MAX_LIST} 件を表示している。絞り込むと残りが見える
              </p>
            ) : null}
            {filtered.length === 0 && ports ? (
              <p className="hint">条件に合う漁港が無い</p>
            ) : null}
          </section>
        </div>

        <div className="stage">
          <FishingPortMap
            ports={filtered}
            selectedPortNo={selected}
            onSelect={setSelected}
            baseMap={baseMap}
            showPoints={showPoints}
          />
          <div className="map-legend">
            <strong>漁港の種別</strong>
            <ul>
              {PORT_CLASS_ORDER.map((cls) => (
                <li key={cls}>
                  <span
                    className="swatch"
                    style={{ background: PORT_CLASS_COLOR[cls] }}
                    aria-hidden
                  />
                  {PORT_CLASS_LABEL[cls]}
                </li>
              ))}
            </ul>
          </div>
        </div>

        {selected ? (
          <PortDrawer portNo={selected} onClose={() => setSelected(null)} />
        ) : null}
      </div>
    </div>
  );
}
