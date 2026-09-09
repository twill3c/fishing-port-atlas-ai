import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { Metadata } from "next";

import { OceanTable, type OceanRow } from "@/components/ocean/OceanTable";
import {
  LONG_SERIES_MIN_YEARS,
  annualNormal,
  formatSlope,
  median,
  sparklinePath,
  type OceanArea,
} from "@/lib/ocean";

export const metadata: Metadata = {
  title: "海の温度 | Fishing Port Atlas AI",
  description:
    "気象庁の沿岸海域 107 の海面水温を 1982 年から通しで測る。冷たい海ほど速く上がっている。",
};

const SPARK_W = 132;
const SPARK_H = 26;

function loadAreas(): OceanArea[] {
  const path = join(process.cwd(), "public", "data", "ocean", "areas.json");
  return JSON.parse(readFileSync(path, "utf-8")) as OceanArea[];
}

/** ピアソン相関。散布図に添える数を、図と同じデータから出す(HC-045)。 */
function pearson(xs: number[], ys: number[]): number {
  const n = xs.length;
  const mx = xs.reduce((a, b) => a + b, 0) / n;
  const my = ys.reduce((a, b) => a + b, 0) / n;
  let sxy = 0;
  let sxx = 0;
  let syy = 0;
  for (let i = 0; i < n; i += 1) {
    const dx = xs[i] - mx;
    const dy = ys[i] - my;
    sxy += dx * dy;
    sxx += dx * dx;
    syy += dy * dy;
  }
  return sxy / Math.sqrt(sxx * syy);
}

export default function OceanPage() {
  const areas = loadAreas();
  const long = areas.filter((a) => a.trend.n_years >= LONG_SERIES_MIN_YEARS);
  const short = areas.filter((a) => a.trend.n_years < LONG_SERIES_MIN_YEARS);

  const medianSlope = median(long.map((a) => a.trend.slope_per_decade));
  const rising = long.filter((a) => a.trend.slope_per_decade > 0);
  const risingSig = rising.filter((a) => a.trend.p < 0.05);

  // 地域ごとの中央値(北から南の順は気象庁の地域区分の並びに合わせる)
  const REGION_ORDER = [
    "北海道周辺",
    "東北周辺",
    "関東・東海・北陸",
    "近畿・中国・四国",
    "九州北部",
    "九州南部・奄美",
    "沖縄",
  ];
  const byRegion = REGION_ORDER.map((name) => {
    const items = long.filter((a) => a.region === name);
    return {
      name,
      n: items.length,
      median: items.length ? median(items.map((a) => a.trend.slope_per_decade)) : 0,
    };
  }).filter((r) => r.n > 0);

  // 平年水温(緯度の代理)と上がり方
  const withNormal = long
    .map((a) => ({ area: a, normal: annualNormal(a) }))
    .filter((r): r is { area: OceanArea; normal: number } => r.normal !== null);
  const xs = withNormal.map((r) => r.normal);
  const ys = withNormal.map((r) => r.area.trend.slope_per_decade);
  const r = pearson(xs, ys);

  const sortedByNormal = [...withNormal].sort((a, b) => a.normal - b.normal);
  const q = Math.floor(sortedByNormal.length / 4);
  const medianOf = (items: typeof sortedByNormal) =>
    median(items.map((i) => i.area.trend.slope_per_decade));
  const coldQuartile = medianOf(sortedByNormal.slice(0, q));
  const warmQuartile = medianOf(sortedByNormal.slice(-q));

  const rows: OceanRow[] = areas.map((a) => ({
    areaNo: a.area_no,
    areaName: a.area_name,
    region: a.region,
    slope: a.trend.slope_per_decade,
    p: a.trend.p,
    nYears: a.trend.n_years,
    firstYear: a.trend.first_year,
    lastYear: a.trend.last_year,
    firstMean: a.series[0].mean,
    lastMean: a.series[a.series.length - 1].mean,
    normal: annualNormal(a),
    spark: sparklinePath(a.series, SPARK_W, SPARK_H),
    long: a.trend.n_years >= LONG_SERIES_MIN_YEARS,
  }));

  const lastObs = areas.map((a) => a.last_observation).sort().at(-1)!;

  return (
    <main className="article article--wide">
      <p>
        <a href="/">← 地図へ戻る</a>
      </p>
      <h1>海の温度</h1>
      <p className="lede">
        気象庁は日本の沿岸を <strong>{areas.length} の海域</strong>に分け、
        1982 年から日ごとの海面水温を出している。
        {long.length} 海域ぶんの年平均を年に対して回帰すると、
        <strong>
          {rising.length} 海域で上がっており、うち {risingSig.length} 海域は p&lt;0.05
        </strong>
        である。上がり方の中央値は <strong>{formatSlope(medianSlope)} ℃/10年</strong>。
      </p>
      <p className="hint">最新の観測日: {lastObs}</p>

      <h2>冷たい海ほど、速く上がっている</h2>
      <p>
        海域ごとの平年水温(1991–2020 の年平均)を横軸、上がり方を縦軸に取ると、
        右下がりになる。相関は <strong>r = {r.toFixed(3)}</strong>({withNormal.length} 海域)。
        平年水温がいちばん低い四分の一の中央値が {formatSlope(coldQuartile)} ℃/10年、
        いちばん高い四分の一が {formatSlope(warmQuartile)} ℃/10年で、
        <strong>およそ 2 倍の開き</strong>がある。
      </p>

      <Scatter points={withNormal.map((w) => ({ x: w.normal, y: w.area.trend.slope_per_decade }))} />

      <p>
        平年水温は緯度の代理である(北の海ほど冷たい)。実際、地域区分でも同じ順に並ぶ。
      </p>

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>地域(北から南)</th>
              <th className="num">海域数</th>
              <th className="num">上がり方の中央値</th>
            </tr>
          </thead>
          <tbody>
            {byRegion.map((row) => (
              <tr key={row.name}>
                <td>{row.name}</td>
                <td className="num">{row.n}</td>
                <td className="num">{formatSlope(row.median)} ℃/10年</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>読むときの但し書き</h2>
      <ul>
        <li>
          <strong>瀬戸内海の {short.length} 海域は 1982 年から取れない。</strong>
          {short.map((a) => a.area_name).join("・")}は 2016 年からの速報値だけで、
          平年値も無い。10 年の傾きと 44 年の傾きは比べられないので、
          既定では表から外してある(チェックを外すと出る)。
        </li>
        <li>
          <strong>p 値は目安である。</strong>年平均どうしは独立ではない(自己相関がある)ので、
          検定の前提を厳密には満たさない。符号と大きさを読むための添え物として出している。
        </li>
        <li>
          <strong>長期の傾きは再解析値だけで出している。</strong>速報値(P)が入るのは
          取得時点の当年と、上の瀬戸内海 {short.length} 海域だけで、
          当年は有効日数の条件(330 日以上)で自動的に外れる。
        </li>
      </ul>

      <h2>なぜ漁港に海域が結びついていないのか</h2>
      <p>
        気象庁は<strong>海域のポリゴンを配布していない</strong>。配っているのは海域番号と
        海域名の対応表だけである。海域名から場所を引く規則を書いて実測すると、
        {areas.length} 海域のうち<strong>都道府県名を含むのは 29</strong> しかなかった。
        残りは「留萌地方沿岸北部」「玄界灘・響灘」「トカラ列島沿岸北部」のように、
        振興局名・灘や湾の名前・島名で呼ばれている。
      </p>
      <p>
        市町村名で照合する規則も試したが、<strong>偽の一致が出た</strong> ——
        青森県深浦町は日本海に面しているのに、郡名「西津軽郡」を通って「津軽海峡」に当たる。
        近いから、たぶんここだろう、では割り当てない。画面に出す海域名は
        「この港の海域はここである」という主張であり、裏づけの無い主張は出さない。
      </p>
      <p className="hint">
        測って捨てた記録は<a href="/methodology/">設計図</a>に残してある。
      </p>

      <h2>海域の一覧</h2>
      <OceanTable rows={rows} regions={REGION_ORDER} />

      <p className="hint" style={{ marginTop: "1.2rem" }}>
        気象庁「日本沿岸域の海面水温」をもとに Fishing Port Atlas AI が加工。
        年平均は有効日数 330 日以上の年のみ。上がり方は最小二乗回帰の傾き(℃/10年)。
      </p>
    </main>
  );
}

/** 平年水温 × 上がり方の散布図。軸ラベルまで viewBox に収める(HC-159)。 */
function Scatter({ points }: { points: { x: number; y: number }[] }) {
  const W = 640;
  const H = 300;
  const M = { top: 16, right: 16, bottom: 44, left: 56 };
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const x0 = Math.floor(Math.min(...xs) - 1);
  const x1 = Math.ceil(Math.max(...xs) + 1);
  const y0 = Math.min(0, Math.min(...ys) - 0.05);
  const y1 = Math.max(...ys) + 0.05;

  const sx = (x: number) => M.left + ((x - x0) / (x1 - x0)) * (W - M.left - M.right);
  const sy = (y: number) => H - M.bottom - ((y - y0) / (y1 - y0)) * (H - M.top - M.bottom);

  const xTicks = [5, 10, 15, 20, 25];
  const yTicks = [0, 0.1, 0.2, 0.3, 0.4, 0.5];

  return (
    <figure className="scatter">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
        aria-label="平年水温が低い海域ほど、水温の上がり方が大きい散布図">
        {yTicks.map((t) => (
          <g key={t}>
            <line x1={M.left} x2={W - M.right} y1={sy(t)} y2={sy(t)}
              stroke="currentColor" strokeOpacity="0.14" />
            <text x={M.left - 8} y={sy(t) + 4} textAnchor="end" fontSize="11" fill="currentColor"
              fillOpacity="0.62">
              {t.toFixed(1)}
            </text>
          </g>
        ))}
        {xTicks.map((t) => (
          <text key={t} x={sx(t)} y={H - M.bottom + 18} textAnchor="middle" fontSize="11"
            fill="currentColor" fillOpacity="0.62">
            {t}℃
          </text>
        ))}
        <line x1={M.left} x2={W - M.right} y1={sy(0)} y2={sy(0)}
          stroke="currentColor" strokeOpacity="0.35" />
        {points.map((p, i) => (
          <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r="3.4"
            fill="var(--accent)" fillOpacity="0.62" />
        ))}
        <text x={(M.left + W - M.right) / 2} y={H - 8} textAnchor="middle" fontSize="11.5"
          fill="currentColor" fillOpacity="0.72">
          平年水温(1991–2020 の年平均)
        </text>
        <text x={14} y={(M.top + H - M.bottom) / 2} fontSize="11.5" fill="currentColor"
          fillOpacity="0.72" textAnchor="middle"
          transform={`rotate(-90 14 ${(M.top + H - M.bottom) / 2})`}>
          上がり方(℃/10年)
        </text>
      </svg>
      <figcaption>
        点は 1982 年から取れる {points.length} 海域。横軸が右へ行くほど暖かい海。
      </figcaption>
    </figure>
  );
}
