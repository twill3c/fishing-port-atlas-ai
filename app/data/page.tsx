import type { Metadata } from "next";

import { loadManifest, loadSources, loadStats } from "@/lib/loadPublicData";
import { PORT_CLASS_LABEL, PORT_CLASS_ORDER } from "@/lib/ports";

export const metadata: Metadata = {
  title: "出典 | Fishing Port Atlas AI",
};

const METHOD_LABEL: Record<string, string> = {
  code_name_pref: "漁港番号・港名・都道府県が一致",
  code_pref: "漁港番号と都道府県が一致",
  name_pref: "同一県に同名の港が1つだけ",
  boundary_centroid: "漁港区域線の重心",
  none: "座標なし",
};

export default function DataPage() {
  const stats = loadStats();
  const sources = loadSources();
  const manifest = loadManifest();

  return (
    <main className="article">
      <p>
        <a href="/">← 地図へ戻る</a>
      </p>
      <h1>出典とデータの作り方</h1>
      <p>
        この画面の数はすべて生成物(<code>public/data</code>)から読んでいる。
        手で書き写した数は置いていない。
      </p>
      <p className="hint">最終ビルド: {manifest.build}</p>

      <h2>データ源</h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>データ</th>
              <th>提供者</th>
              <th>対象期間</th>
              <th>取得日</th>
              <th>加工</th>
              <th>ライセンス</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
              <tr key={source.id}>
                <td>{source.id}</td>
                <td>
                  <a href={source.url} target="_blank" rel="noreferrer">
                    {source.title}
                  </a>
                </td>
                <td>{source.provider}</td>
                <td>{source.coverage}</td>
                <td>{source.retrieved}</td>
                <td>{source.processed ? source.processing : "加工なし"}</td>
                <td>{source.license}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">
        {sources.map((s) => s.attribution).join(" ／ ")}
      </p>

      <h2>公式の港数と、作った港数</h2>
      <p>
        期待値を定数で持たず、水産庁の総括表 PDF から毎回読んでいる
        (基準日 {stats.official.as_of})。公式が更新されればこの表も動く。
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>種別</th>
              <th className="num">総括表(公式)</th>
              <th className="num">明細から作った数</th>
            </tr>
          </thead>
          <tbody>
            {PORT_CLASS_ORDER.map((cls) => (
              <tr key={cls}>
                <td>{PORT_CLASS_LABEL[cls]}</td>
                <td className="num">{stats.official.by_class[cls].toLocaleString()}</td>
                <td className="num">{stats.built.by_class[cls].toLocaleString()}</td>
              </tr>
            ))}
            <tr>
              <th>合計</th>
              <th className="num">{stats.official.total.toLocaleString()}</th>
              <th className="num">{stats.built.total.toLocaleString()}</th>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        特定第3種の {stats.official.special_class_3_names.length} 港は総括表の脚注に
        港名で列挙されている:{" "}
        {stats.official.special_class_3_names.join("・")}。
        明細の種別欄とは独立に集合として突き合わせている。
      </p>

      <h2>座標がどこから来たか</h2>
      <p>
        座標は国土数値情報「漁港データ」(平成18年度)から漁港番号で突き合わせている。
        マスタは令和8年、座標は平成18年なので、番号が一致しても別の港に振り替わっている
        ことがある。そこで突合を段階に分け、港ごとにどの段階で座標が付いたかを残している。
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>段階</th>
              <th className="num">港数</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(stats.built.by_geometry_method)
              .filter(([key]) => key !== "boundary_rejected_by_bbox")
              .map(([key, value]) => (
                <tr key={key}>
                  <td>{METHOD_LABEL[key] ?? key}</td>
                  <td className="num">{value.toLocaleString()}</td>
                </tr>
              ))}
            <tr>
              <th>座標あり</th>
              <th className="num">
                {stats.built.with_coordinates.toLocaleString()}(
                {((stats.built.with_coordinates / stats.built.total) * 100).toFixed(2)}%)
              </th>
            </tr>
          </tbody>
        </table>
      </div>

      <h2>まだ無いもの</h2>
      <ul>
        <li>
          漁業センサス・海面漁業生産統計(e-Stat): 認証 ID が要るため未取得。
          該当欄は 0 ではなく「未取得」と出している
        </li>
        <li>主要漁港別上場水揚量(海しる API): API キーが要るため未取得</li>
        <li>津波浸水想定(国土数値情報 A40): 都道府県ごとの再配布条件を確認中のため未取得</li>
        <li>海面水温・AI 分析: 実装中(方法のページを参照)</li>
      </ul>

      <h2>都道府県別の港数</h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>都道府県</th>
              <th className="num">港数</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(stats.built.by_prefecture).map(([pref, n]) => (
              <tr key={pref}>
                <td>{pref}</td>
                <td className="num">{n.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
