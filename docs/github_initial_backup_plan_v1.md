# GitHub Initial Backup Plan v1

## 基本方針

初回GitHubバックアップは、再構築可能なソースコードを中心にする。大量のRaw CSV、実行生成JSON、解析Markdown、Ledger、Smoke成果物はGitへ含めず、ローカルまたは別のartifact storageで保管する。秘密情報・個人情報・ライセンス不明データはコミット前に別途確認する。

## KEEP

- `evaluation/`, `review/`, `engine/`, `evaluators/`, `importer/`: `.py`ソース。今回のSafety修正を含む。
- `tests/`: 固定テスト、fixture生成コード。テスト実行時に作られた一時成果物は除外。
- `analysis/`: `.py`分析ロジックのみ。
- `learning/`: `.py`ロジックのみ。実行状態JSONは除外。
- `config/`: 秘密情報を含まない設定、スキーマ、サンプル。
- `docs/`, `operations/`, ルートの実行用`.py`: 設計・運用文書と再現用entry point。
- `.gitignore`、依存関係定義、README、ライセンス。

## OPTIONAL

- `knowledge/`: 小型で出所・ライセンスが確認済みの固定知識だけ。自動更新スナップショットは除外。
- `data/`: 単体テストに不可欠な最小fixtureだけ。匿名化し、サイズと再配布条件を確認する。
- `reports/`: リリース判定や事故記録として長期保存すべき少数の文書のみ。必要なら`docs/`へ昇格するか、明示的にforce-addする。
- `learning/`の初期テンプレート: 空または匿名化されたseedだけ。運用中DBは含めない。
- 固定Baseline manifest: 実データ本体を含まず、SHA・schema・由来だけを記録する小型manifest。

## IGNORE

- `reports/`配下のCSV、JSON、JSONL、Markdown、log、Historical Replay run directory。
- `data/`配下のRaw entry、horses、result、trial set、生成CSV/JSON/JSONL。
- `analysis/`配下の生成CSV/JSON/JSONL。
- `learning/*.json`, `learning/*.jsonl`: 運用中Learning DB・状態。
- `__pycache__/`, `*.pyc`, `.pytest_cache/`, coverage、一時テストディレクトリ、ログ。
- 外部から再取得可能な大容量ファイル、秘密情報、ローカル環境固有ファイル。

## 初回コミット推奨順序

1. `.gitignore`とリポジトリ基本文書。
2. source directoriesと設定。
3. tests。
4. 出所確認済みの最小knowledge/fixture。
5. `git diff --cached --stat`と秘密情報スキャン後にコミット。

生成物は削除していない。ignoreはGitの候補表示から除外するだけである。
