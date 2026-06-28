# 私専用 中央競馬分析AI

このプロジェクトは、中央競馬の分析を自動化し、将来的に自分専用の予想AIへ育てるための土台です。

第1段階では機械学習を使いません。
まずは、人間が競馬を分析するときの流れをAIの基本ルールとして固定します。

## 育成ステップ

1. 分析を自動化するAI
2. JRAのデータを自動取得
3. 機械学習を追加
4. 自分専用の予想AIに育てる

## 設計思想

このAIは、以下の流れを崩さないように育てます。
この流れは `config.py` の `DESIGN_PIPELINE` で管理しています。

```text
JRA出走表
↓
データ取得
↓
過去走取得
↓
展開分析
↓
馬場分析
↓
血統分析
↓
相手関係分析
↓
総合評価
↓
将来的に機械学習
```

今は自動取得や機械学習は行わず、保存済みHTMLやCSVから分析できる形を作っています。

## フォルダ構成

```text
keiba-ai-v2/
├── analyzer/          # 分析プログラム
├── knowledge/         # コース辞書・血統辞書などの競馬知識
├── data/              # レースデータ・試運転用CSV
├── importer/          # HTML/CSV変換・将来のデータ取得入口
├── models/            # 将来のAIモデル
├── reports/           # 分析結果・検証結果
├── config.py          # 分析ルール・重み管理
├── convert_entries.py # 出走表ファイル変換用
├── main.py            # 分析実行入口
└── README.md
```

## 実行方法

リポジトリ直下で実行します。

```powershell
cd "C:\Users\hikar\Desktop\keiba AI"
python main.py
```

このPCで `python` が使えない場合は、PythonのインストールまたはPATH設定が必要です。

## AIの基本ルール

以下の順番で、全頭を自動分析します。この順番は `config.py` の `ANALYSIS_RULES` で一か所管理しています。

1. 過去走分析
2. 相手関係
3. 通過順・脚質
4. 距離適性
5. 当日馬場
6. 血統
7. 馬体重
8. 展開予想
9. 全頭評価表
10. 3着内率

分析結果は見やすい表で画面に表示され、`reports/analysis_report.txt` にも保存されます。
将来の検証や機械学習で使うための特徴量は、`data/features.csv` に保存されます。

## 評価基準

各分析項目でAIが何を見るかは、`config.py` の `ANALYSIS_CRITERIA` で管理しています。
分析項目を増やす場合は `ANALYSIS_RULES` に項目名を追加し、必要に応じて `ANALYSIS_CRITERIA` に同じ項目名で評価基準を追加します。
分析項目を減らす場合も、基本的には `config.py` を編集すれば管理できます。

## スコア計算

項目別スコアは `analyzer/score_calculator.py` で計算します。
今は簡易ルールで、各項目を0〜100点にしています。

- 過去走分析: `last_runs` の着順が安定しているほど高評価
- 相手関係: `knowledge/opponent_profiles.py` のクラス別相手レベルを使用
- 通過順・脚質: `running_style` と過去の脚質を比較
- 距離適性: `distance` と過去の距離実績を比較
- 馬場: `track_condition`、`bloodline_note`、`knowledge/track_bias.py` の馬場バイアスを使用
- ラップ適性: `past_lap_note` と `expected_lap_note` からレース質との相性を評価
- 馬体重: `body_weight` と `body_weight_diff` を使用

将来、本格的な評価ロジックや機械学習を入れる場合は、まず `score_calculator.py` を差し替える方針です。

## 重み管理

分析項目ごとの重みは `config.py` の `ANALYSIS_WEIGHTS` で管理します。
`score_calculator.py` や `integrated_evaluator.py` は、この設定を参照して評価します。

例:

```python
ANALYSIS_WEIGHTS = {
    "past_run": 20,
    "opponent": 20,
    "pace": 20,
    "lap": 15,
    "track_bias": 10,
    "course": 5,
    "distance": 10,
    "bloodline": 5,
    "body_weight": 5,
}
```

今後、東京芝1600m用、道悪用、短距離用のように重みを変えたい場合は、`WEIGHT_PROFILES` に追加して拡張します。
今回使った重みは `analysis_report.txt` と `data/features.csv` にも保存されます。

## 特徴量保存

特徴量保存は `analyzer/feature_exporter.py` で行います。
`main.py` を実行すると、1行=1頭の形式で `data/features.csv` に保存されます。

保存する主な内容:

- レース情報
- 馬番、馬名、脚質
- 過去走、相手関係、展開、コース、距離、馬場バイアス、血統、馬体重のスコア
- 補正前総合点
- 統合評価点
- 3着内率の仮推定
- Explain Engine が作った reason_id、reason_type、理由数

このCSVは、後で予想の振り返りや機械学習モデルの入力データとして使うための土台です。
文章の理由は `analysis_report.txt` に表示し、`features.csv` には保存しません。

## Explain Engine

理由生成は `analyzer/explain_analyzer.py` で行います。
各分析エンジンの結果を集約し、加点理由・減点理由・総合評価理由に分けます。

- レポート用: 「なぜ加点したか」「なぜ減点したか」を文章で表示
- 機械学習用: `reason_id` や `reason_type` だけを `features.csv` に保存
- 設計方針: `score_calculator.py` では理由文章を組み立てず、Explain Engine が理由を管理

## Evaluation Engine

検証は `analyzer/evaluation_engine.py` で行います。
分析エンジンを増やすのではなく、AIの予想と実際の結果を比較して、予想精度を改善するための土台です。

入力CSV:

- `data/analysis_result.csv`: AIの予想順位、予想スコア、3着内率
- `data/result.csv`: 実際の着順、人気、単勝オッズ、タイム、上がり、通過順

算出できる指標:

- 順位一致率
- 3着内率
- 平均誤差
- スコア平均との差

実行例:

```powershell
python analyzer/evaluation_engine.py
```

実行すると `reports/evaluation_report.txt` に検証レポートを保存します。
将来的に比較項目を増やしたい場合は、`PredictionRecord`、`ActualResultRecord`、`HorseEvaluationRow` に列を追加して拡張します。

## 統合評価エンジン

統合評価は `analyzer/integrated_evaluator.py` で行います。
項目別スコアを単独で見るのではなく、複数条件の組み合わせで最終評価を補正します。

例:

- 展開評価、コース適性、血統評価がそろって高い場合は加点
- 展開は向くが馬場評価が低い場合は減点
- 距離適性と血統評価が同時に高い場合は加点
- 過去走と相手関係の裏付けが弱い場合は減点

統合評価では、補正前の総合点、補正量、補正後の統合評価点を分けて保存します。
この情報は将来、機械学習へ渡す特徴量としても使える設計です。

## 相手関係評価エンジン

相手関係評価は `analyzer/opponent_analyzer.py` で行います。
相手レベルの知識は `knowledge/opponent_profiles.py` で管理します。

今は簡易ルールとして、G1、G2、G3、リステッド、オープン、3勝クラス、2勝クラス、1勝クラス、未勝利、新馬を0〜100点で評価します。

評価する内容:

- 過去レースの平均相手レベル
- 最高相手レベル
- 直近相手レベル
- 相手レベルの推移
- 今回メンバー平均との差

将来JRA、JRA-VAN、netkeibaなどから取得したクラス表記に変わっても、基本的には `knowledge/opponent_profiles.py` に表記を追加すれば対応できる方針です。

## 馬場バイアス評価エンジン

馬場バイアス評価は `analyzer/track_bias_analyzer.py` で行います。
馬場バイアスの知識は `knowledge/track_bias.py` で管理します。

登録できる情報:

- 競馬場
- 芝/ダート
- 距離
- 内有利、外有利
- 前有利、差し有利
- 時計が速い、時計が掛かる
- 雨の影響
- 馬場悪化時の傾向

分析する内容:

- 有利な脚質
- 有利な枠
- 時計傾向
- 今回の展開との相性
- 今回有利になる馬

今後コース別・開催日別の馬場傾向を増やす場合は、基本的に `knowledge/track_bias.py` にデータを追加します。
分析ロジック側は `knowledge` を参照するだけにして、知識と分析ロジックを分離します。

## 展開予想エンジン

展開予想は `analyzer/pace_analyzer.py` で行います。
今は機械学習を使わず、以下のルールベースで分析します。

1. 各馬の脚質を逃げ・先行・差し・追込に分類
2. 逃げ馬と先行馬の頭数を数える
3. ペースをスロー・平均・ハイに分類
4. 展開で有利になりやすい脚質を判定
5. 各馬の展開適性を0〜100点で評価

将来はこのファイルに、ラップ分析、コース形態、枠順、騎手傾向などを追加します。

## ラップ分析エンジン

ラップ分析は `analyzer/lap_analyzer.py` で行います。
今は `today_entries.csv` の `past_lap_note` と `expected_lap_note` を使い、簡易ルールで判定します。

分析する内容:

- 前半3F
- 後半3F
- 前後半差
- ペース判定
- レース質判定
- 有利な脚質
- 各馬のラップ適性

例:

- 前半が遅く、後半が速い: 瞬発戦
- 前半が速く、後半が掛かる: 消耗戦
- 前後半差が少ない: 持続戦

将来、実際のラップタイムを取得できるようになったら、`lap_analyzer.py` の入力部分を差し替えて育てます。

## コース辞書

コース特徴は `knowledge/course_profiles.py` で管理します。

登録できる情報:

- 競馬場
- 芝/ダート
- 距離
- コース特徴
- 有利になりやすい脚質
- 枠順傾向
- 求められる能力
- 注意点

データを増やす場合は、`COURSE_PROFILES` に同じ形式でコースを追加します。
展開予想エンジンとスコア計算は、このコース辞書を参照します。

## knowledge設計方針

競馬AIの知識は `knowledge` フォルダで一元管理します。
分析プログラム側の `analyzer` は、`knowledge` を参照して分析します。
知識データと分析ロジックは分離します。

将来的な構成:

```text
knowledge/
├── course_profiles.py
├── bloodline_profiles.py
├── opponent_profiles.py
├── track_bias.py
├── class_profiles.py
├── pace_patterns.py
├── distance_profiles.py
```

今は `course_profiles.py` と `bloodline_profiles.py` を中心に使います。
他のファイルは、後から簡単に知識を追加できるように土台だけ用意しています。

## 血統辞書

血統特徴は `knowledge/bloodline_profiles.py` で管理します。

登録できる情報:

- 得意距離
- 得意馬場
- 芝/ダート適性
- 瞬発力型
- 持続力型
- 重馬場適性
- 成長力
- 注意点

`score_calculator.py` は血統辞書を参照し、血統評価・馬場評価・距離適性評価へ反映します。

## 出走表CSV

`data/today_entries.csv` に、JRAの出走表を見ながら手入力できます。
最初は `data/today_entries_template.csv` をコピーして、`data/today_entries.csv` という名前で保存してください。
空欄や不足列は、できるだけ「不明」として扱い、エラーで止まりにくいようにしています。

使える列は以下です。

```text
race_date
racecourse
race_number
distance
surface
track_condition
horse_number
horse_name
frame_number
jockey
weight
body_weight
body_weight_diff
running_style
last_runs
past_lap_note
expected_lap_note
sire
dam_sire
bloodline_note
class_level
```

入力の目安:

- `race_date`: レース日。例: `2026-06-28`
- `racecourse`: コース、競馬場。例: `東京`、`阪神`
- `race_number`: レース番号。例: `11`
- `distance`: 距離。メートルだけを数字で入力。例: `1800`
- `surface`: 芝/ダート。例: `芝`
- `track_condition`: 当日馬場状態。例: `良`、`稍重`、`重`、`不良`
- `horse_number`: 馬番。例: `1`
- `horse_name`: 馬名。例: `サンプルスター`
- `frame_number`: 枠順。例: `1`
- `jockey`: 騎手名。分からなければ空欄でもOK
- `weight`: 斤量。例: `56.0`
- `body_weight`: 馬体重。例: `492`
- `body_weight_diff`: 前走比。増加は `10`、減少は `-6`
- `running_style`: 脚質。`逃げ`、`先行`、`差し`、`追込` のどれかを推奨
- `last_runs`: 過去走。例: `1-3-4-2-1`
- `past_lap_note`: ラップメモ。例: `瞬発戦が得意`、`消耗戦は不安`
- `expected_lap_note`: 今回の想定ラップ。例: `前半3F:35.8 後半3F:34.2 瞬発戦想定`
- `sire`: 父。例: `ディープインパクト`
- `dam_sire`: 母父。例: `キズナ`
- `bloodline_note`: 血統メモ。例: `中距離向き・良馬場歓迎`
- `class_level`: 相手レベルの補助入力。例: `G1`、`G2`、`G3`、`3勝クラス`、`2勝クラス`、`1勝クラス`

`last_runs` は `1-3-4-2-1` のように、過去走の着順を左から順番に入力します。
今は `config.py` の `PAST_RUN_LIMIT = 5` により、入力された過去走のうち5走分を使います。
将来は `PAST_RUN_LIMIT = 10` や `PAST_RUN_LIMIT = "all"` に変更できます。
`past_lap_note` は「瞬発戦が得意」「消耗戦は不安」など、過去走のラップ適性メモを入れます。
`expected_lap_note` は「前半3F:35.8 後半3F:34.2 瞬発戦想定」のように、今回想定するラップを書きます。
`bloodline_note` は「中距離向き」「良馬場歓迎」「距離延長は不安」など、自分のメモを入れます。

## 過去走データの将来拡張

今は `today_entries.csv` の `last_runs` を使います。
将来、JRA公式、JRA-VAN、netkeibaなどから競走馬成績を取得する場合は、`importer/past_run_sources.py` に取得処理を追加します。

## 将来の拡張

- 第2段階: `data/` にJRAから取得したCSVを保存する
- 第3段階: `models/` に機械学習モデルを保存する
- 第4段階: 自分の予想結果と回収率を記録し、重みを調整する

## v0.4 試運転準備版

現在の到達点を `v0.4 試運転準備版` として整理します。
この版では、実際の1レースを手入力CSVで読み込み、分析・理由表示・検証準備までできる状態を目標にしています。

### 実装済み

- 分析エンジン
  - 過去走分析
  - 相手関係評価
  - 通過順・脚質評価
  - 距離適性評価
  - 馬場評価
  - 血統評価
  - 馬体重評価
  - 展開予想
  - コース辞書参照
  - 馬場バイアス評価
  - ラップ分析
  - 統合評価
- Explain Engine
  - 加点理由、減点理由、総合評価理由を構造化
  - `reason_id` と `reason_type` を将来の機械学習用に保存
- Evaluation Engine
  - AIの予想順位と実際の着順を比較
  - 人気、単勝オッズ、タイム、上がり、通過順を比較
  - 順位一致率、3着内率、平均誤差、スコア平均との差を算出
- 特徴量保存
  - `data/features.csv` に1行=1頭で保存
  - 将来の検証・機械学習に使いやすい形式
- 重み管理
  - `config.py` の `ANALYSIS_WEIGHTS` で分析項目の重みを管理
  - レポートと特徴量CSVにも使用重みを保存
- 試運転用テンプレート
  - `data/today_entries_template.csv` を追加
  - 人間がCSVを埋めれば `main.py` で分析できる状態
  - 空欄や不足列はできるだけ `不明` として扱う

### 今後やること

- JRA出走表や結果データの取り込みを安定化する
- コース辞書、血統辞書、馬場バイアス辞書を増やす
- `analysis_result.csv` と `result.csv` を実レースで蓄積する
- Evaluation Engine の検証指標を増やす
- 特徴量と検証結果を使って重みを調整する
- 十分にデータが集まったら機械学習モデルを追加する
