import type { Metadata } from "next";

import { loadStats } from "@/lib/loadPublicData";
import { PORT_CLASS_LABEL, PORT_CLASS_NOTE, PORT_CLASS_ORDER } from "@/lib/ports";

export const metadata: Metadata = {
  title: "歩き方 | Fishing Port Atlas AI",
};

export default function AboutPage() {
  const stats = loadStats();

  return (
    <main className="article">
      <p>
        <a href="/">← 地図へ戻る</a>
      </p>
      <h1>漁港アトラスの歩き方</h1>
      <p>
        日本には <strong>{stats.official.total.toLocaleString()} の指定漁港</strong>がある
        (令和8年4月1日現在)。港湾でも漁場でもなく、漁港漁場整備法にもとづいて
        国と自治体が「ここは漁港である」と指定した場所である。
        この画面は、その全部を公開データだけで地図に載せたものだ。
      </p>

      <h2>種別を知ると地図が読める</h2>
      <p>
        漁港には 5 つの種別がある。地図の点の色と大きさはこれに対応している。
        「大きい港ほど大きな点」ではなく、<strong>利用範囲の広さ</strong>で分けられている。
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>種別</th>
              <th className="num">港数</th>
              <th>どういう港か</th>
            </tr>
          </thead>
          <tbody>
            {PORT_CLASS_ORDER.map((cls) => (
              <tr key={cls}>
                <td>{PORT_CLASS_LABEL[cls]}</td>
                <td className="num">{stats.built.by_class[cls].toLocaleString()}</td>
                <td>{PORT_CLASS_NOTE[cls]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        全体の 7 割が第1種、つまり<strong>地元の漁業のための小さな港</strong>である。
        名前を聞いたことのある港(焼津・銚子・気仙沼)は特定第3種の
        {stats.official.special_class_3_names.length} 港に集中している。
      </p>

      <h2>まず試すこと</h2>
      <ol>
        <li>
          左の「種別で絞る」で<strong>特定第3種</strong>だけを残す。
          日本の水産業の背骨がどこにあるかが一目で分かる
        </li>
        <li>
          <strong>第4種</strong>だけを残す。離島・辺地の避難港なので、
          本土の海岸線からいきなり外れた場所に点が並ぶ
        </li>
        <li>
          検索欄に県名を入れる。<strong>愛媛県 187 / 長崎県 222 / 北海道 241</strong> ——
          面積でも人口でもない並びになる
        </li>
        <li>
          <strong>滋賀県</strong>で検索する。海の無い県に 20 の漁港がある(琵琶湖)。
          いずれも座標がなく、一覧にだけ現れる
        </li>
      </ol>

      <h2>点をクリックすると</h2>
      <p>
        右に詳細が開く。漁港番号・種別・管理者・漁協・指定年月日は水産庁の一覧そのままで、
        <span className="badge badge--official">OFFICIAL</span> の印が付く。
        座標には <span className="badge">DERIVED</span> が付き、
        <strong>どうやってその座標に辿り着いたか</strong>が書いてある。
        20 年前の地理データと今のマスタを突き合わせているので、確からしさが港ごとに違う。
      </p>

      <h2>空欄は空欄のまま出している</h2>
      <p>
        水揚げ量・魚種・海面水温・AI の欄は今のところ空である。0 は入れていない。
        「データなし」「対象外」「未取得」を区別して出す。
        なぜ無いのかは<a href="/data/">出典のページ</a>に書いた。
      </p>

      <h2>この地図で答えられないこと</h2>
      <ul>
        <li>今どこで何が獲れているか(リアルタイムの情報は扱わない)</li>
        <li>避難の判断(津波の情報は自治体・気象庁・国土交通省の公式情報を見ること)</li>
        <li>港の良し悪し・行政評価・補助金の妥当性</li>
      </ul>
      <p>
        作り方と、確かめたことは<a href="/methodology/">設計図</a>に書いてある。
      </p>
    </main>
  );
}
