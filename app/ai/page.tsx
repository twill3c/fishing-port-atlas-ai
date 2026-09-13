import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AI | Fishing Port Atlas AI",
  description:
    "公式の漁港種別は、施設の規模で読めるのか。事前登録した合格ラインで測り、読めなかった結果もそのまま出す。",
};

const CLASSES = ["1", "2", "3", "special_3", "4"] as const;
const CLASS_LABEL: Record<string, string> = {
  "1": "第1種",
  "2": "第2種",
  "3": "第3種",
  special_3: "特定第3種",
  "4": "第4種",
};

/** train_class.py のモデル名と対応。出荷しない陽性対照は明示する */
const MODEL_LABEL: Record<string, string> = {
  majority: "多数派(常に第1種と答える)",
  logistic_scale: "ロジスティック回帰 — 規模だけ",
  logistic_full: "ロジスティック回帰 — 規模+属性",
  hist_gradient_boosting_full: "勾配ブースティング — 規模+属性",
  mlp_full: "ニューラルネット MLP — 規模+属性",
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
            <strong>読める。</strong>施設の規模(係留・外郭施設延長)だけで、
            多数派ベースラインを macro-F1 で {f3(g16.margin)} 上回った。
          </>
        ) : (
          <>
            <strong>規模だけでは読めない。</strong>施設の規模(係留・外郭施設延長)だけで学習すると
            macro-F1 は {f3(scale.macro_f1_mean)} で、常に第1種と答える多数派
            ({f3(majority.macro_f1_mean)})を {f3(g16.margin)} しか上回らなかった。
            実測の前に決めておいた合格ライン({g16.threshold.toFixed(2)})に届かない。
          </>
        )}
      </p>
      <p>
        種別は法令上「利用範囲」で定義されており、施設の大きさでは決まらない。
        {g16.passed ? (
          <>それでも規模だけで合格ラインを越えたので、種別と施設の規模は強く結びついている。</>
        ) : (
          <>
            規模と種別には関係がある(大きい種別ほど施設も長い)が、
            <strong>重なりが大きく、規模から種別を言い当てられるほどではない</strong>。
          </>
        )}
      </p>
      <p className="hint">
        対象 {report.n_ports.toLocaleString()} 港(施設延長のある港だけ。無い港は 0 で埋めずに外した)/
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
            : "採用の判断は乱数によって変わる。規則は事前に決めたとおりに適用したが、この勝ちは頑健ではない。"}
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
            <strong>第4種は規模だけでは見分けにくく、属性を足すと見分けやすくなる。</strong>
          ) : (
            <strong>第4種は、属性を足しても規模だけより見分けやすくならなかった。</strong>
          )}
          規模だけの再現率 {f3(scale.per_class_recall["4"])}、離島・国境離島などの属性を足すと{" "}
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
          第4種の再現率は {f3(admin.per_class_recall["4"])}(規模だけでは{" "}
          {f3(scale.per_class_recall["4"])})、第3種は {f3(admin.per_class_recall["3"])}(同{" "}
          {f3(scale.per_class_recall["3"])})。第4種はほぼ都道府県が管理するので、
          当たるとしてもそれは種別の<strong>帰結</strong>を覚えただけで、手がかりではない。
          {report.expectations.E5.held
            ? "予想どおり、第3・第4種とも規模だけより高かった。"
            : "予想した「第3・第4種とも規模だけより高い」は成り立たなかった。"}
        </li>
      </ul>

      <h2>この AI が言っていないこと</h2>
      <ul>
        <li>公式と違う答えが出た港について、指定が誤っているとは言っていない</li>
        <li>水揚げ量・魚種・経営は入っていない(港別のデータが公開されていないため)</li>
        <li>
          施設延長は平成18年度、種別は令和8年の値である。その間に施設が変わった港では、
          答えが古い規模に引きずられる
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
    </main>
  );
}
