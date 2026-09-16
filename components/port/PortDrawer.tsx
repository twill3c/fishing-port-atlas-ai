"use client";

import { useEffect, useState } from "react";

import { TsunamiTab, type TsunamiSection } from "@/components/port/TsunamiTab";
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

/** 分割外予測(その港を学習に使っていないモデルの答え)。export_web.py の _ai_section と対応 */
interface AiEstimated {
  status: "estimated";
  question: string;
  official_class: PortClass;
  predicted_class: PortClass;
  vote_share: number;
  agrees: boolean;
  model: string;
  model_macro_f1: number;
  baseline_macro_f1: number;
  cv: string;
  data_vintage: { master: string; infrastructure: string };
}

interface AiUnavailable {
  status: string;
  note: string;
}

type AiSection = AiEstimated | AiUnavailable;

/** 類似漁港(F-08)。export_web.py の _similar_section と対応 */
interface SimilarNeighbor {
  port_no: string;
  name_ja: string;
  prefecture: string;
  port_class: PortClass;
  distance: number;
}

interface SimilarEstimated {
  status: "estimated";
  neighbors: SimilarNeighbor[];
  features: string[];
  sensitivity_notice: string | null;
  note: string;
}

type SimilarSection = SimilarEstimated | { status: string; note: string };

function isSimilarEstimated(s: SimilarSection): s is SimilarEstimated {
  return s.status === "estimated";
}

function isEstimated(ai: AiSection): ai is AiEstimated {
  return ai.status === "estimated";
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
  ai: AiSection;
  tsunami: TsunamiSection;
  similar: SimilarSection;
  sources: { source_id: string; role: string; artifact?: string }[];
}

const TABS = ["概要", "属性", "水揚げ", "海洋", "防災", "AI", "出典"] as const;
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

/** 学習器の名前を、読み手に通じる言葉へ(train_class.py のモデル名と対応) */
const MODEL_LABEL: Record<string, string> = {
  majority: "多数派(常に第1種と答える)",
  logistic_scale: "ロジスティック回帰(施設延長だけ)",
  logistic_full: "ロジスティック回帰(施設延長+属性)",
  hist_gradient_boosting_full: "勾配ブースティング(施設延長+属性)",
  mlp_full: "ニューラルネット MLP(施設延長+属性)",
};

function MarkedValue({ mark }: { mark: Marked }) {
  if (mark.value !== null) return <>{mark.value}</>;
  return <span className="badge">{STATUS_LABEL[mark.status] ?? mark.status}</span>;
}

export function PortDrawer({
  portNo,
  onClose,
  areaVisible,
  onToggleArea,
  onAreaSource,
}: {
  portNo: string;
  onClose: () => void;
  /** 津波浸水想定の区域の面を地図に重ねているか(G-34) */
  areaVisible: boolean;
  onToggleArea: () => void;
  /**
   * 詳細を読んだら、その港の面のファイルの場所(無ければ null)を港番号つきで親へ知らせる。
   * 親は面を配っている港だけ取りに行く(面の無い港で 404 を出さない)
   */
  onAreaSource: (portNo: string, url: string | null) => void;
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
        if (cancelled) return;
        setDetail(json);
        onAreaSource(portNo, json.tsunami?.area ?? null);
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
                data-testid={`drawer-tab-${name}`}
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

          {tab === "防災" ? (
            <TsunamiTab tsunami={detail.tsunami} areaVisible={areaVisible} onToggleArea={onToggleArea} />
          ) : null}

          {tab === "AI" ? (
            <>
              {isEstimated(detail.ai) ? (
                <AiTab ai={detail.ai} />
              ) : (
                <p className="status-note" data-testid="drawer-ai-unavailable">
                  {detail.ai.note}
                </p>
              )}
              <SimilarBlock similar={detail.similar} />
            </>
          ) : null}

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

/**
 * AI タブ。実装仕様書 §64(断定しない)・§85(モデル・期間・精度・注意事項を併記)に従う。
 * 公式の値(OFFICIAL)と推定値(AI)を同じ行に並べず、印で区別する(§91)。
 */
function AiTab({ ai }: { ai: AiEstimated }) {
  const votes = Math.round(ai.vote_share * 5);
  return (
    <div data-testid="drawer-ai">
      <p className="hint" style={{ marginTop: 0 }}>
        問い: {ai.question}
      </p>
      <dl className="kv">
        <dt>公式の種別</dt>
        <dd>
          {PORT_CLASS_LABEL[ai.official_class]}{" "}
          <span className="badge badge--official">OFFICIAL</span>
        </dd>
        <dt>施設延長・属性から見た種別</dt>
        <dd data-testid="drawer-ai-predicted">
          {PORT_CLASS_LABEL[ai.predicted_class]} <span className="badge">AI</span>
          <br />
          <span className="layer-row__note">
            交差検証 5 回のうち {votes} 回がこの答え
          </span>
        </dd>
        <dt>公式との関係</dt>
        <dd>
          {ai.agrees
            ? "公式の種別と一致する"
            : `施設延長と属性だけを見ると、${PORT_CLASS_LABEL[ai.predicted_class]}の港に近い`}
        </dd>
        <dt>モデル</dt>
        <dd>
          {MODEL_LABEL[ai.model] ?? ai.model}
          <br />
          <span className="layer-row__note">
            macro-F1 {ai.model_macro_f1.toFixed(3)}(多数派ベースライン{" "}
            {ai.baseline_macro_f1.toFixed(3)})/ {ai.cv}
          </span>
        </dd>
        <dt>データの年次</dt>
        <dd>
          <span className="layer-row__note">
            種別: {ai.data_vintage.master}
            <br />
            施設延長: {ai.data_vintage.infrastructure}
          </span>
        </dd>
      </dl>
      <p className="status-note">
        種別は法令上「利用範囲」で決まり、施設の大きさでは決まらない。
        公式と違う答えが出ても、指定が誤っているという意味ではない。
        この推定は統計モデルの答えであり、行政上の区分ではない。
      </p>
      <p className="status-note" data-testid="drawer-ai-caveat">
        施設延長は国土数値情報のメタデータのとおり、普通交付税の算定基準に基づく数値で、
        実際の施設延長とは異なる。施設延長が 0 の港は、0 を欠測の印とみなして学習に入れていない。
      </p>
      <p className="hint">
        <a href="/ai/">この AI が何を測り、何が言えなかったか</a>
      </p>
    </div>
  );
}

/** 学習の特徴名を、読み手に通じる言葉へ(ml/features.py の FEATURES_FULL と対応) */
const FEATURE_LABEL: Record<string, string> = {
  log_mooring_m: "係留施設延長",
  log_outer_m: "外郭施設延長",
  is_island: "離島",
  is_peninsula: "半島",
  is_border_island: "有人国境離島",
  port_regulation_circle: "港則法適用(○)",
  port_regulation_double: "港則法適用(◎)",
  visitor_berth: "ビジター受入",
  subdistrict_count: "分区数",
  coast_conservation_circle: "海岸保全区域(○)",
  coast_conservation_double: "海岸保全区域(◎)",
  designation_year: "指定年",
};

/**
 * 類似漁港(F-08)。似ているの定義は一つの選び方にすぎないので、
 * 使った特徴と、選び方への感度の注意書き(G-26)を一覧と同じ場所に出す。
 */
function SimilarBlock({ similar }: { similar: SimilarSection }) {
  if (!isSimilarEstimated(similar)) {
    return (
      <p className="status-note" data-testid="drawer-similar-unavailable">
        {similar.note}
      </p>
    );
  }
  return (
    <section data-testid="drawer-similar">
      <h3>施設延長と属性が近い港</h3>
      <p className="hint">{similar.note}</p>
      {similar.sensitivity_notice ? (
        <p className="status-note" data-testid="drawer-similar-notice">
          {similar.sensitivity_notice}
        </p>
      ) : null}
      <ol className="similar-list">
        {similar.neighbors.map((n) => (
          <li key={n.port_no}>
            <a href={`/?port=${n.port_no}`}>{n.name_ja}</a>{" "}
            <span className="layer-row__note">
              {n.prefecture}・{PORT_CLASS_LABEL[n.port_class]}・距離 {n.distance.toFixed(2)}
            </span>
          </li>
        ))}
      </ol>
      <p className="layer-row__note">
        使った特徴: {similar.features.map((f) => FEATURE_LABEL[f] ?? f).join("・")}
      </p>
    </section>
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
