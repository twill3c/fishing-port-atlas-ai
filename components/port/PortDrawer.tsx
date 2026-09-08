"use client";

import { useEffect, useState } from "react";

import {
  GEOMETRY_METHOD_LABEL,
  PORT_CLASS_LABEL,
  PORT_CLASS_NOTE,
  type PortClass,
} from "@/lib/ports";

interface Marked {
  value: string | null;
  status: string;
}

interface PortDetail {
  port: {
    port_no: string;
    name_ja: string;
    name_kana: string;
    port_class: PortClass;
    prefecture: string;
    municipality: string | null;
    lat: number | null;
    lon: number | null;
    geometry_method: string | null;
  };
  administration: Record<string, Marked>;
  attributes: Record<string, Marked>;
  landing: { status: string; note: string };
  species: { status: string; note: string };
  ocean: { status: string; note: string };
  ai: { status: string; note: string };
  sources: { source_id: string; role: string; artifact?: string }[];
}

const TABS = ["概要", "属性", "水揚げ", "海洋", "AI", "出典"] as const;
type Tab = (typeof TABS)[number];

const ADMIN_LABEL: Record<string, string> = {
  administrator_name: "漁港管理者",
  administrator_type: "管理者区分",
  fishery_coop: "漁業協同組合",
  designation_date: "指定年月日",
  area_change_date: "区域変更年月日",
};

const ATTR_LABEL: Record<string, string> = {
  island_peninsula: "離島・半島",
  inhabited_border_island: "有人国境離島",
  coast_conservation: "海岸保全区域",
  port_regulation_law: "港則法適用",
  visitor_berth: "ビジター受入",
  subdistrict: "分区",
  remarks: "備考",
};

const ADMIN_TYPE_LABEL: Record<string, string> = {
  prefecture: "都道府県",
  municipality: "市町村",
};

/** 値が無い理由の語彙(export_web.py の STATUS_VOCAB と対応) */
const STATUS_LABEL: Record<string, string> = {
  not_available: "データなし",
  not_applicable: "対象外",
  missing_source: "未取得",
  suppressed: "非公表",
  estimated: "推定値",
};

function MarkedValue({ mark }: { mark: Marked }) {
  if (mark.value !== null) return <>{mark.value}</>;
  return <span className="badge">{STATUS_LABEL[mark.status] ?? mark.status}</span>;
}

export function PortDrawer({
  portNo,
  onClose,
}: {
  portNo: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<PortDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("概要");

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setError(null);
    setTab("概要");
    fetch(`/data/ports/${portNo}.json`)
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status}`);
        return res.json();
      })
      .then((json: PortDetail) => {
        if (!cancelled) setDetail(json);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [portNo]);

  return (
    <aside className="drawer" aria-label="漁港の詳細" data-testid="port-drawer">
      {error ? <p className="status-note">詳細を読み込めなかった({error})</p> : null}
      {!detail && !error ? <p className="hint">読み込み中…</p> : null}

      {detail ? (
        <>
          <div className="drawer__head">
            <div>
              <h2 className="drawer__title" data-testid="drawer-port-name">
                {detail.port.name_ja}漁港
              </h2>
              <p className="drawer__sub">
                {detail.port.name_kana} ／ {detail.port.prefecture}
                {detail.port.municipality ?? ""}
              </p>
            </div>
            <button className="drawer__close" onClick={onClose} aria-label="詳細を閉じる">
              ×
            </button>
          </div>

          <div className="tabs" role="tablist">
            {TABS.map((name) => (
              <button
                key={name}
                role="tab"
                aria-selected={tab === name}
                onClick={() => setTab(name)}
              >
                {name}
              </button>
            ))}
          </div>

          {tab === "概要" ? (
            <dl className="kv">
              <dt>漁港番号</dt>
              <dd>
                {detail.port.port_no} <span className="badge badge--official">OFFICIAL</span>
              </dd>
              <dt>種別</dt>
              <dd>
                {PORT_CLASS_LABEL[detail.port.port_class]}
                <br />
                <span className="layer-row__note">
                  {PORT_CLASS_NOTE[detail.port.port_class]}
                </span>
              </dd>
              {Object.entries(detail.administration).map(([key, mark]) => (
                <Row key={key} label={ADMIN_LABEL[key] ?? key}>
                  {key === "administrator_type" && mark.value ? (
                    (ADMIN_TYPE_LABEL[mark.value] ?? mark.value)
                  ) : (
                    <MarkedValue mark={mark} />
                  )}
                </Row>
              ))}
              <dt>座標</dt>
              <dd>
                {detail.port.lat !== null && detail.port.lon !== null ? (
                  <>
                    {detail.port.lat.toFixed(5)}, {detail.port.lon.toFixed(5)}
                    <br />
                    <span className="layer-row__note">
                      由来: {GEOMETRY_METHOD_LABEL[detail.port.geometry_method ?? ""] ?? "—"}
                      <span className="badge"> DERIVED</span>
                    </span>
                  </>
                ) : (
                  <span className="badge no-coord">座標なし</span>
                )}
              </dd>
            </dl>
          ) : null}

          {tab === "属性" ? (
            <dl className="kv">
              {Object.entries(detail.attributes).map(([key, mark]) => (
                <Row key={key} label={ATTR_LABEL[key] ?? key}>
                  <MarkedValue mark={mark} />
                </Row>
              ))}
            </dl>
          ) : null}

          {tab === "水揚げ" ? (
            <>
              <p className="status-note">{detail.landing.note}</p>
              <p className="hint">
                魚種別の内訳も同じ理由で空欄である。0 は入れていない。
              </p>
            </>
          ) : null}

          {tab === "海洋" ? <p className="status-note">{detail.ocean.note}</p> : null}
          {tab === "AI" ? <p className="status-note">{detail.ai.note}</p> : null}

          {tab === "出典" ? (
            <ul>
              {detail.sources.map((source) => (
                <li key={`${source.source_id}-${source.role}`}>
                  <strong>{source.source_id}</strong> — {source.role}
                  {source.artifact ? `(${source.artifact})` : ""}
                </li>
              ))}
              <li>
                <a href="/data/">出典の一覧を見る</a>
              </li>
            </ul>
          ) : null}
        </>
      ) : null}
    </aside>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}
