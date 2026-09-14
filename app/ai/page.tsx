import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AI | Fishing Port Atlas AI",
  description:
    "公式の漁港種別は、交付税の算定に使う施設延長で読めるのか。事前登録した合格ラインで測り、読めなかった結果もそのまま出す。",
};

const CLASSES = ["1", "2", "3", "special_3", "4"] as const;
const CLASS_LABEL: Record<string, string> = {
  "1": "第1種",
  "2": "第2種",
  "3": "第3種",
  special_3: "特定第3種",
  "4": "第4種",
};

/** train_class.py のモデル名と対応(名前の scale は loop_004 の呼び名の名残)。出荷しない陽性対照は明示する */
const MODEL_LABEL: Record<string, string> = {
  majority: "多数派(常に第1種と答える)",
  logistic_scale: "ロジスティック回帰 — 施設延長だけ",
  logistic_full: "ロジスティック回帰 — 施設延長+属性",
  hist_gradient_boosting_full: "勾配ブースティング — 施設延長+属性",
  mlp_full: "ニューラルネット MLP — 施設延長+属性",
  logistic_admin_only: "ロジスティック回帰 — 管理者区分だけ(陽性対照)",
};

interface Model {
  name: string;
  features: string[];
  macro_f1_mean: number;
  macro_f1_se: number;
  per_class_recall: Record<string, number>;
  confusion_pooled: { labels: string[]; matrix: number[][] };
}

interface Report {
  question: string;
  infrastructure_caveat: string;
  n_ports: number;
  class_counts: Record<string, number>;
  cv: { folds: number; repeats: number; seed: number };
  data_vintage: { master: string; infrastructure: string };
  models: Model[];
  gates: {
    "G-16": { threshold: number; margin: number; passed: boolean };
    "G-11": {
      best_non_nn: string;
      mlp_shipped: boolean;
      init_seed_robustness?: {
        macro_f1_mean_by_seed: Record<string, number>;
        line: number;
        seeds_above_line: string[];
        holds_for_all_seeds: boolean;
      };
    };
  };
  shipped_model: string;
  expectations: Record<string, { declared: string; observed: string; held: boolean }>;
  agreement_rate_shipped: number;
}

function loadReport(): Report {
  const path = join(process.cwd(), "public", "data", "ai", "class-report.json");
  return JSON.parse(readFileSync(path, "utf-8")) as Report;
}

const f3 = (v: number) => v.toFixed(3);

export default function AiPage() {
  const report = loadReport();
  const by = Object.fromEntries(report.models.map((m) => [m.name, m])) as Record<string, Model>;
  const g16 = report.gates["G-16"];
  const g11 = report.gates["G-11"];
  const robust = g11.init_seed_robustness;
  const shipped = by[report.shipped_model];
  const scale = by.logistic_scale;
  const majority = by.majority;
  const admin = by.logistic_admin_only;
  const full = by.logistic_full;

  return (
    <main className="article article--wide">
      <p>
        <a href="/">← 地図へ戻る</a>
      </p>
      <h1>AI — {report.question}</h1>

      <p className="lede" data-testid="ai-answer">
        {g16.passed ? (
          <>
            <strong>読める。</strong>係留・外郭施設延長だけで、
            多数派ベースラインを macro-F1 で {f3(g16.margin)} 上回った。
          </>
        ) : (
          <>
            <strong>施設延長だけでは読めない。</strong>係留・外郭施設延長だけで学習すると
            macro-F1 は {f3(scale.macro_f1_mean)} で、常に第1種と答える多数派
            ({f3(majority.macro_f1_mean)})を {f3(g16.margin)} しか上回らなかった。
            実測の前に決めておいた合格ライン({g16.threshold.toFixed(2)})に届かない。
          </>
        )}
      </p>
      <p>
        種別は法令上「利用範囲」で定義されており、施設の大きさでは決まらない。
        {g16.passed ? (
          <>それでも施設延長だけで合格ラインを越えたので、種別と施設延長は強く結びついている。</>
        ) : (
          <>
            施設延長と種別には関係がある(上の種別ほど延長も長い)が、
            <strong>重なりが大きく、施設延長から種別を言い当てられるほどではない</strong>。
          </>
        )}
      </p>
      <p data-testid="ai-caveat">
        <strong>施設延長は、施設の実際の長さではない。</strong>
        国土数値情報(漁港データ)のメタデータは、この二つの属性を次のように説明している ——
        「{report.infrastructure_caveat}」。
        最初の版(2026-09-14)はこれを読まずに「施設の規模」と呼び、
        さらに施設延長 0 を値として学習していた。0 は八戸(特定第3種)にも付いていて、
        青森県・岩手県に固まる欠測の印である。2026-09-15 に 0 の港を外して学習し直すと、
        <strong>最初の版の答え「読めない」(多数派との差 0.128)は「読める」(差 0.233)に変わった</strong>。
        合格ライン・予想の文面・手順は変えていない。
      </p>
      <p className="hint">
        対象 {report.n_ports.toLocaleString()} 港(施設延長のある港だけ。無い港と 0 の港は外した)/
        種別: {report.data_vintage.master} / 施設延長: {report.data_vintage.infrastructure}
      </p>

      <h2>比べたモデル</h2>
      <p>
        同じ層化 {report.cv.folds} 分割 × {report.cv.repeats} 反復の交差検証で比べた。
        値はすべて<strong>その港を学習に使っていないモデルの答え</strong>(分割外予測)から出している。
        種別の偏りは全モデルで同じ重みで補正し、ハイパーパラメータは調整していない。
        特定第3種は {report.class_counts.special_3} 港しかないので、指標は正解率ではなく macro-F1 にした。
      </p>
      <div className="table-scroll">
        <table data-testid="ai-models">
          <thead>
            <tr>
              <th>モデル</th>
              <th className="num">macro-F1</th>
              {CLASSES.map((c) => (
                <th key={c} className="num">
                  {CLASS_LABEL[c]}
                  <br />
                  再現率
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {report.models.map((m) => (
              <tr key={m.name}>
                <td>
                  {MODEL_LABEL[m.name] ?? m.name}
                  {m.name === report.shipped_model ? <span className="badge"> 出荷</span> : null}
                  {m.name === "logistic_admin_only" ? (
                    <span className="badge"> 出荷しない</span>
                  ) : null}
                </td>
                <td className="num">
                  {f3(m.macro_f1_mean)} ± {f3(m.macro_f1_se)}
                </td>
                {CLASSES.map((c) => (
                  <td key={c} className="num">
                    {f3(m.per_class_recall[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">± は反復 {report.cv.repeats} 回の macro-F1 の標準誤差。</p>

      <h2>ニューラルネットを出すかどうか</h2>
      <p>
        ニューラルネット(MLP)は、非ニューラルネットで最良の
        {MODEL_LABEL[g11.best_non_nn] ?? g11.best_non_nn}を
        <strong>1 標準誤差を超えて上回ったときだけ</strong>出す、と実測の前に決めた。
        結果は {g11.mlp_shipped ? "上回った" : "上回らなかった"}ので、
        地図の各港の AI 欄には <strong>{MODEL_LABEL[report.shipped_model] ?? report.shipped_model}</strong>
        の答えを出している(公式の種別と一致したのは{" "}
        {(report.agreement_rate_shipped * 100).toFixed(1)}%)。
      </p>
      {robust ? (
        <p data-testid="ai-robustness">
          ただし交差検証の反復は「分割」のばらつきしか見ていない。そこで同じ分割のまま
          MLP の初期化の乱数だけを {Object.keys(robust.macro_f1_mean_by_seed).length} 通りに替えて測った。
          線({f3(robust.line)})を越えたのは {robust.seeds_above_line.length} 通り
          (
          {Object.entries(robust.macro_f1_mean_by_seed)
            .map(([s, v]) => `乱数 ${s}: ${f3(v)}`)
            .join(" / ")}
          )で、
          {robust.holds_for_all_seeds
            ? "どの乱数でも採用の判断は変わらない。"
            : robust.seeds_above_line.length === 0
              ? "どの乱数でも線を越えなかったので、ニューラルネットを出さない判断は乱数によって変わらない。"
              : "採用の判断は乱数によって変わる。規則は事前に決めたとおりに適用したが、この判断は頑健ではない。"}
        </p>
      ) : null}

      <h2>実測の前に書いた予想と、その結果</h2>
      <p>
        予想の文面は測る前に仕様書へ書き、測った後に変えていない。外れたものも外れたと書く。
      </p>
      <div className="table-scroll">
        <table data-testid="ai-expectations">
          <thead>
            <tr>
              <th>ID</th>
              <th>予想</th>
              <th>観測</th>
              <th>結果</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(report.expectations).map(([id, e]) => (
              <tr key={id}>
                <td>{id}</td>
                <td>{e.declared}</td>
                <td>{e.observed}</td>
                <td>
                  <span className="badge">{e.held ? "成立" : "不成立"}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>測って分かったこと</h2>
      {/* 各項目は予想 E2・E3・E5 の成否から出し分ける。結論を無条件に書くと、
          データが動いたときに数だけが変わって文が嘘になる(HC-045) */}
      <ul data-testid="ai-findings">
        <li>
          {report.expectations.E2.held ? (
            <strong>第4種は施設延長だけでは見分けにくく、属性を足すと見分けやすくなる。</strong>
          ) : (
            <strong>第4種は、属性を足しても施設延長だけより見分けやすくならなかった。</strong>
          )}
          施設延長だけの再現率 {f3(scale.per_class_recall["4"])}、離島・国境離島などの属性を足すと{" "}
          {f3(full.per_class_recall["4"])}。第4種は「離島その他辺地」で定義される種別である。
        </li>
        <li>
          {report.expectations.E3.held ? (
            <strong>特定第3種の取り違えは、第3種へ向かうのがいちばん多い。</strong>
          ) : (
            <strong>特定第3種の取り違えは、第3種へ向かうのがいちばん多いわけではなかった。</strong>
          )}
          {report.expectations.E3.observed}。
        </li>
        <li>
          <strong>管理者区分を特徴に入れなかった理由。</strong>管理者区分だけで学習すると、
          第4種の再現率は {f3(admin.per_class_recall["4"])}(施設延長だけでは{" "}
          {f3(scale.per_class_recall["4"])})、第3種は {f3(admin.per_class_recall["3"])}(同{" "}
          {f3(scale.per_class_recall["3"])})。第4種はほぼ都道府県が管理するので、
          当たるとしてもそれは種別の<strong>帰結</strong>を覚えただけで、手がかりではない。
          {report.expectations.E5.held
            ? "予想どおり、第3・第4種とも施設延長だけより高かった。"
            : "予想した「第3・第4種とも規模だけより高い」は成り立たなかった(予想の文面は登録したときのまま)。"}
        </li>
      </ul>

      <h2>この AI が言っていないこと</h2>
      <ul>
        <li>公式と違う答えが出た港について、指定が誤っているとは言っていない</li>
        <li>水揚げ量・魚種・経営は入っていない(港別のデータが公開されていないため)</li>
        <li>
          施設延長は平成18年度、種別は令和8年の値である。その間に施設が変わった港では、
          答えが古い施設延長に引きずられる
        </li>
        <li>座標・都道府県は入れていない(地域を覚えて当ててしまうため)</li>
      </ul>

      <h2>出荷したモデルの取り違え</h2>
      <p className="hint">
        行が公式の種別、列が {MODEL_LABEL[report.shipped_model] ?? report.shipped_model} の答え。
        {report.cv.repeats} 反復の合算なので、各港が {report.cv.repeats} 回数えられている。
      </p>
      <div className="table-scroll">
        <table data-testid="ai-confusion">
          <thead>
            <tr>
              <th>公式 \ 推定</th>
              {shipped.confusion_pooled.labels.map((c) => (
                <th key={c} className="num">
                  {CLASS_LABEL[c]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shipped.confusion_pooled.matrix.map((row, i) => (
              <tr key={shipped.confusion_pooled.labels[i]}>
                <th>{CLASS_LABEL[shipped.confusion_pooled.labels[i]]}</th>
                {row.map((v, j) => (
                  <td key={j} className="num">
                    {i === j ? <strong>{v.toLocaleString()}</strong> : v.toLocaleString()}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <SimilarReport />
    </main>
  );
}

interface Agreement {
  "1": number;
  "2": number;
  "3": number;
  special_3: number;
  "4": number;
  macro: number;
}

interface ClusterK {
  silhouette: number;
  null_silhouette: number;
  seed_ari_min: number;
  subsample_ari_min: number;
  max_single_flag_ari: number;
  max_single_flag: string;
  sizes: number[];
  qualifies: boolean;
}

interface SimilarMeta {
  features: string[];
  k: number;
  n_ports: number;
  identical_feature_rows: number;
  tie_rule: string;
  class_agreement: { shipped: Agreement; lengths_only: Agreement; random: Agreement };
  gates: {
    "G-25": { threshold: number; margin: number; passed: boolean };
    "G-26": { threshold: number; overlap_with_lengths_only: number; notice_required: boolean };
    "G-28": { by_k: Record<string, ClusterK>; selected_k: number | null; passed: boolean };
  };
  sensitivity_notice: string | null;
  clusters: {
    k: number;
    profiles: {
      cluster: number;
      size: number;
      class_counts: Record<string, number>;
      medians: Record<string, number>;
      flag_shares: Record<string, number>;
    }[];
    best_two_flag: { flags: string[]; ari: number; post_hoc: boolean; note: string };
  } | null;
}

const FLAG_LABEL: Record<string, string> = {
  is_island: "離島",
  is_peninsula: "半島",
  is_border_island: "有人国境離島",
  port_regulation_circle: "港則法適用(○)",
  port_regulation_double: "港則法適用(◎)",
  visitor_berth: "ビジター受入",
  coast_conservation_circle: "海岸保全区域(○)",
  coast_conservation_double: "海岸保全区域(◎)",
};

function loadSimilarMeta(): SimilarMeta | null {
  try {
    const path = join(process.cwd(), "public", "data", "similar", "meta.json");
    return JSON.parse(readFileSync(path, "utf-8")) as SimilarMeta;
  } catch {
    return null; // G-25 を通らなかったので配っていない
  }
}

/** F-08 類似漁港とクラスタ。判定の規則は SPEC G-25〜G-28 に実測前に書いた */
function SimilarReport() {
  const meta = loadSimilarMeta();
  if (meta === null) {
    return (
      <section data-testid="ai-similar">
        <h2>似た港とクラスタ</h2>
        <p>近傍の種別の一致が無作為と十分に違わなかったので、似た港は出していない。</p>
      </section>
    );
  }
  const g25 = meta.gates["G-25"];
  const g26 = meta.gates["G-26"];
  const g28 = meta.gates["G-28"];
  const rows: [string, Agreement][] = [
    ["出荷した近傍(施設延長+属性 12 特徴)", meta.class_agreement.shipped],
    ["施設延長 2 特徴だけの近傍", meta.class_agreement.lengths_only],
    ["無作為に選んだ港(閉じた式)", meta.class_agreement.random],
  ];
  return (
    <section data-testid="ai-similar">
      <h2>似た港とクラスタ</h2>
      <p>
        施設延長と属性を標準化した距離で、各港に近い {meta.k} 港を出している(対象{" "}
        {meta.n_ports.toLocaleString()} 港)。似ているかどうかに外部の正解は無いので、
        特徴に入れていない<strong>公式の種別</strong>が近傍でどれだけ一致するかで確かめた。
      </p>
      <div className="table-scroll">
        <table data-testid="ai-similar-agreement">
          <thead>
            <tr>
              <th>近傍の選び方</th>
              {CLASSES.map((c) => (
                <th key={c} className="num">
                  {CLASS_LABEL[c]}
                </th>
              ))}
              <th className="num">平均(macro)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, a]) => (
              <tr key={label}>
                <td>{label}</td>
                {CLASSES.map((c) => (
                  <td key={c} className="num">
                    {f3(a[c])}
                  </td>
                ))}
                <td className="num">{f3(a.macro)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        出荷した近傍の一致は無作為を {f3(g25.margin)} 上回り、実測の前に決めた線(
        {g25.threshold.toFixed(2)})を{g25.passed ? "越えた" : "越えなかった"}。
        ただし<strong>施設延長だけで選んだ近傍と、上位 {meta.k} 港のうち平均{" "}
        {(g26.overlap_with_lengths_only * 100).toFixed(1)}% しか重ならない</strong>。
        {g26.notice_required ? "何を似ているとみなすかで答えが大きく変わるので、港の AI タブでも使った特徴と一緒に出している。" : ""}
      </p>

      <h3>クラスタ</h3>
      <p>
        k-means の群を「港の型」と呼ぶには、実測の前に 4 つの条件を決めた ——
        並べ替えた帰無より silhouette が 0.05 以上高い・初期化の乱数を替えても同じ群になる(ARI 0.80 以上)・
        8 割の部分標本でも同じ群になる(同)・一つの印で切った 2 群と同じではない(ARI 0.80 未満)。
      </p>
      <div className="table-scroll">
        <table data-testid="ai-similar-clusters">
          <thead>
            <tr>
              <th className="num">k</th>
              <th className="num">silhouette</th>
              <th className="num">帰無</th>
              <th className="num">乱数替え ARI 最小</th>
              <th className="num">部分標本 ARI 最小</th>
              <th>いちばん重なる印(ARI)</th>
              <th>判定</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(g28.by_k).map(([k, m]) => (
              <tr key={k}>
                <td className="num">{k}</td>
                <td className="num">{f3(m.silhouette)}</td>
                <td className="num">{f3(m.null_silhouette)}</td>
                <td className="num">{f3(m.seed_ari_min)}</td>
                <td className="num">{f3(m.subsample_ari_min)}</td>
                <td>
                  {FLAG_LABEL[m.max_single_flag] ?? m.max_single_flag}({f3(m.max_single_flag_ari)})
                </td>
                <td>
                  <span className="badge">{m.qualifies ? "満たす" : "満たさない"}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {g28.passed && meta.clusters ? (
        <>
          <p>
            条件を満たしたのは k={g28.selected_k} だけだった。
            <strong>
              ただしこの群は{" "}
              {FLAG_LABEL[g28.by_k[String(g28.selected_k)].max_single_flag] ??
                g28.by_k[String(g28.selected_k)].max_single_flag}
              の有無と ARI {f3(g28.by_k[String(g28.selected_k)].max_single_flag_ari)} で重なる
            </strong>
            。線(0.80)の内側ではあるが、群の多くはこの一つの印で説明がつく。下に中身を並べる。
          </p>
          <p data-testid="ai-similar-two-flag">
            <strong>
              中身を読むと、群を分けているのは施設延長ではなく印だった。
            </strong>
            係留施設延長の中央値は群どうしでほとんど変わらない。
            {meta.clusters.best_two_flag.flags.map((f) => FLAG_LABEL[f] ?? f).join("と")}
            の二つの印の組み合わせで切った分割と比べると ARI は{" "}
            {f3(meta.clusters.best_two_flag.ari)} になる。
            この値は群を読んだ後に測ったもので、判定には使っていない ——
            実測の前に書いた条件は「一つの印で切った 2 群」しか見ておらず、
            二つの印で切れる場合を覆っていなかった。
          </p>
          <div className="table-scroll">
            <table data-testid="ai-similar-profiles">
              <thead>
                <tr>
                  <th>群</th>
                  <th className="num">港</th>
                  <th className="num">係留施設延長の中央値</th>
                  <th>種別の内訳</th>
                  <th>印の割合(50% 以上)</th>
                </tr>
              </thead>
              <tbody>
                {meta.clusters.profiles.map((p) => (
                  <tr key={p.cluster}>
                    <td>群 {p.cluster + 1}</td>
                    <td className="num">{p.size.toLocaleString()}</td>
                    <td className="num">{Math.round(Math.expm1(p.medians.log_mooring_m)).toLocaleString()} m</td>
                    <td>
                      {CLASSES.filter((c) => p.class_counts[c] > 0)
                        .map((c) => `${CLASS_LABEL[c]} ${p.class_counts[c]}`)
                        .join(" / ")}
                    </td>
                    <td>
                      {Object.entries(p.flag_shares)
                        .filter(([, v]) => v >= 0.5)
                        .map(([f, v]) => `${FLAG_LABEL[f] ?? f} ${(v * 100).toFixed(0)}%`)
                        .join(" / ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p>条件を満たす k が無かったので、クラスタは出していない。</p>
      )}
    </section>
  );
}
