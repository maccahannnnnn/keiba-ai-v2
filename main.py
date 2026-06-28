from pathlib import Path

from analyzer.data_loader import load_past_races, load_today_entries_with_exclusions
from analyzer.feature_exporter import export_analysis_results, export_features
from analyzer.keiba_analyzer import KeibaAnalyzer
from analyzer.report_writer import build_report_text, save_report
from review.self_review import run_self_review


def main() -> None:
    """プログラムの入口です。最初はここから読むと全体の流れが分かります。"""

    today_entries_path = Path("data/today_entries.csv")
    template_path = Path("data/today_entries_template.csv")

    if not today_entries_path.exists():
        print("data/today_entries.csv が見つかりません。")
        print(f"まず {template_path} を参考にして、出走馬データを入力してください。")
        print("入力後、もう一度 python main.py を実行してください。")
        return

    # 1. CSVファイルから、過去レースと今回の出走馬を読み込みます。
    past_races = load_past_races("data/sample_races.csv")
    today_entries, excluded_entries = load_today_entries_with_exclusions(str(today_entries_path))

    # 2. 分析AIを作ります。今は機械学習ではなく、ルールベース分析です。
    analyzer = KeibaAnalyzer(past_races)

    # 3. 想定ペースを指定して、全頭を分析します。
    #    ここは将来、出走メンバーから自動判定するように育てられます。
    results = analyzer.analyze(today_entries, expected_pace="ミドル")

    # 4. 将来の検証や機械学習に使えるように、特徴量CSVを保存します。
    feature_file_path = export_features(results, "data/features.csv")
    export_analysis_results(results, "data/analysis_result.csv")

    # 5. 分析結果を文章にして、画面表示とファイル保存を行います。
    report_text = build_report_text(
        results,
        feature_file_path=feature_file_path,
        excluded_entries=excluded_entries,
    )
    print(report_text)
    save_report("reports/analysis_report.txt", report_text)

    # 6. レース結果CSVがあれば、予想と結果を比較する自己採点レポートも作ります。
    #    まだ data/race_result.csv がない場合でも、案内用のレポートを生成して止まらないようにします。
    review_report_path = run_self_review(
        analysis_result_csv="data/analysis_result.csv",
        race_result_csv="data/race_result.csv",
        feature_csv="data/features.csv",
        report_path="reports/review_report.txt",
    )
    print("")
    print(f"自己採点レポートを保存しました: {review_report_path}")


if __name__ == "__main__":
    main()
