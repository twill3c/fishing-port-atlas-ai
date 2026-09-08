# Fishing Port Atlas AI

日本全国 **2,768 の指定漁港**(令和8年4月1日現在)を、公開データだけで地図に載せる。

港名・種別・管理者・漁協・指定年月日は水産庁「漁港一覧」から、座標は国土数値情報
「漁港データ」から取り、**どの港の座標がどれくらい確かか**を港ごとに残している。

## 何ができるか

- 全国の漁港を地図で見る(種別で色分け・第1種から特定第3種まで)
- 港名・読み・都道府県・市町村で検索する(ひらがな入力でも読みで引ける)
- 種別で絞る(特定第3種の 13 港だけ、離島の第4種だけ、など)
- 港をクリックして基本情報と**出典**を読む
- 座標が無い港も一覧から辿れる(0,0 に置いたりしない)

## スクリーンショット

`shots/atlas-map.png`(`npm run verify:browser` が生成する)

## データ源

| ID | データ | 提供者 | 対象 |
|---|---|---|---|
| DS-001 | 漁港一覧(総括表・都道府県別集計・都道府県別明細 40 県) | 水産庁 | 令和8年4月1日現在 |
| DS-002 | 国土数値情報 漁港データ C09-06(点 2,931 / 区域線 3,292) | 国土交通省 | 平成18年度 |
| DS-004 | 地理院タイル(淡色・標準) | 国土地理院 | 背景地図 |

出典: 水産庁「漁港一覧」／ 国土交通省「国土数値情報(漁港データ)」／ 地理院タイル

**海しる API と e-Stat API は使っていない。**どちらも認証キーが必要で、
キー無しでは 404 / 認証失敗を返す(実測 2026-09-08)。漁業統計の欄は 0 で埋めず、
「未取得」と表示している。詳しくは `/data/` と `SPEC.md` §7。

## アーキテクチャ

```
公開データ(PDF / Shapefile)
  → data-pipeline/download   取得と manifest(URL・sha256・取得日時)
  → data-pipeline/normalize  PDF の罫線座標から表を再構成 / 集計表をオラクル化
  → data-pipeline/integrate  漁港番号で突合 → data/canonical/ports.json
  → data-pipeline/export     public/data(manifest・ports.min.json・港ごとの詳細)
  → Next.js + MapLibre GL    静的書き出し(Vercel では ETL も学習も走らせない)
```

## ローカルで動かす

```bash
python -m venv .venv
.venv\Scripts\activate          # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm ci

# データを作る(初回は PDF 42 本と Shapefile を取得する)
python data-pipeline/download/fetch_jfa_ports.py
python data-pipeline/normalize/parse_jfa_ports.py
python data-pipeline/normalize/parse_jfa_summary.py
python data-pipeline/integrate/build_port_master.py
python data-pipeline/export/export_web.py

# 検査
pytest -q                 # パイプラインとデータ(二文書突合)
npm test                  # フロントエンドの規則
npm run typecheck
npm run build
npm run verify:browser    # 実ブラウザ検品(要 npx playwright install chromium)
```

国土数値情報 C09 の Shapefile は `data/raw/ksj/C09-06/` に展開しておくこと
(`https://nlftp.mlit.go.jp/ksj/gml/data/C09/C09-06/C09-06_GML.zip`)。

## 環境変数

**不要である。**このアプリは認証の要る API を使わない。
`.env` も API キーも無く、クライアントバンドルに秘密は入らない(テスト T-020 で検査)。

## どう確かめているか

明細から作った表を、明細を数えた値で検査しても何も分からない。
**明細とは別の 2 枚の文書**(総括表 / 都道府県別集計)を正解に使っている。

- 総数 2,768 港 / 種別内訳(2,031・524・101・13・99)
- 都道府県 40 件それぞれの港数・種別内訳・管理者内訳
- 特定第3種の港名の集合(総括表の脚注に列挙されている 13 港)

照合の途中で、実装仕様書に無い事実がひとつ出た ——
**都道府県別表の「第3種」は特定第3種を含む 114 である**。

方法と、測って分かったことは `/methodology/` と `SPEC.md` に書いてある。

## ライセンス

コードは MIT License(`LICENSE`)。
データは各配布元の利用条件に従う(`public/data/sources.json` と `/data/` を参照)。

## 免責

この地図は公開データの可視化であり、避難判断・行政評価・漁業上の判断には使えない。
津波など防災に関わる判断は、自治体・気象庁・国土交通省の最新の公式情報によること。
