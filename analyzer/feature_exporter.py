import csv
import re
from pathlib import Path

from config import ANALYSIS_WEIGHTS
from analyzer.schemas import AnalysisResult


FEATURE_COLUMNS = [
    "race_date",
    "racecourse",
    "race_number",
    "horse_number",
    "horse_name",
    "running_style",
    "past_run_score",
    "opponent_score",
    "pace_score",
    "lap_score",
    "course_score",
    "distance_score",
    "track_bias_score",
    "bloodline_score",
    "body_weight_score",
    "total_score",
    "integrated_score",
    "estimated_top3_rate",
    "reason_ids",
    "reason_types",
    "reason_plus_count",
    "reason_minus_count",
]
WEIGHT_COLUMNS = [f"weight_{key}" for key in ANALYSIS_WEIGHTS]
"""features.csv に保存する列です。

1行が1頭になるように、機械学習へ渡しやすい横持ち形式にしています。
"""


def export_features(results: list[AnalysisResult], file_path: str) -> str:
    """分析結果を features.csv として保存します。

    CSVにしておくと、あとでExcelで確認したり、Pythonの機械学習ライブラリで
    読み込んだりしやすくなります。
    """

    path = Path(file_path)

    # data フォルダや reports フォルダが無い場合でも、自動で作成します。
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = [build_feature_row(result) for result in results]

    with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=FEATURE_COLUMNS + WEIGHT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    return str(path)


def build_feature_row(result: AnalysisResult) -> dict[str, object]:
    """1頭分の分析結果を、CSVの1行に変換します。"""

    race_info = parse_race_info(result.race_info)
    integrated = result.integrated_evaluation
    explain_features = get_explain_features(result)

    row = {
        "race_date": race_info["race_date"],
        "racecourse": race_info["racecourse"],
        "race_number": race_info["race_number"],
        "horse_number": result.horse_number,
        "horse_name": result.horse_name,
        "running_style": get_running_style(result),
        "past_run_score": get_item_score(result, "過去走分析"),
        "opponent_score": get_item_score(result, "相手関係"),
        "pace_score": get_item_score(result, "展開予想"),
        "lap_score": get_lap_score(result),
        "course_score": calculate_course_score(result),
        "distance_score": get_item_score(result, "距離適性"),
        "track_bias_score": get_track_bias_score(result),
        "bloodline_score": get_item_score(result, "血統"),
        "body_weight_score": get_item_score(result, "馬体重"),
        "total_score": integrated.base_score,
        "integrated_score": integrated.final_score,
        "estimated_top3_rate": round(result.in_the_money_rate * 100, 1),
        "reason_ids": explain_features["reason_ids"],
        "reason_types": explain_features["reason_types"],
        "reason_plus_count": explain_features["reason_plus_count"],
        "reason_minus_count": explain_features["reason_minus_count"],
    }

    # その時点の重みも一緒に保存します。
    # 後から検証するときに「どの設定で出した予想か」が分かります。
    row.update(build_weight_columns())
    return row


def get_explain_features(result: AnalysisResult) -> dict[str, object]:
    """Explain Engine の結果を、文章を含まないCSV用データに変換します。"""

    if result.explain_analysis is None:
        return {
            "reason_ids": "",
            "reason_types": "",
            "reason_plus_count": 0,
            "reason_minus_count": 0,
        }

    return result.explain_analysis.to_features()


def build_weight_columns() -> dict[str, int]:
    """features.csv 用に重み設定を列へ変換します。"""

    return {f"weight_{key}": value for key, value in ANALYSIS_WEIGHTS.items()}


def parse_race_info(race_info: str) -> dict[str, object]:
    """`2026-06-28 東京11R 芝1800m 良` のような文字からレース情報を取り出します。"""

    pattern = r"(?P<race_date>\d{4}-\d{2}-\d{2})\s+(?P<racecourse>.+?)(?P<race_number>\d+)R"
    match = re.search(pattern, race_info)
    if match is None:
        return {
            "race_date": "",
            "racecourse": "",
            "race_number": 0,
        }

    return {
        "race_date": match.group("race_date"),
        "racecourse": match.group("racecourse"),
        "race_number": int(match.group("race_number")),
    }


def get_item_score(result: AnalysisResult, item_name: str) -> float:
    """項目別スコアを安全に取り出します。"""

    detail = result.item_scores.get(item_name)
    if detail is None:
        return 0.0
    return detail.score


def get_running_style(result: AnalysisResult) -> str:
    """展開分析で使った脚質を取り出します。"""

    evaluation = result.pace_analysis.horse_evaluations.get(result.horse_name)
    if evaluation is None:
        return ""
    return evaluation.running_style


def get_track_bias_score(result: AnalysisResult) -> float:
    """馬場バイアス評価点を取り出します。"""

    evaluation = result.track_bias_analysis.horse_evaluations.get(result.horse_name)
    if evaluation is None:
        return 0.0
    return evaluation.score


def get_lap_score(result: AnalysisResult) -> float:
    """ラップ適性評価点を取り出します。"""

    evaluation = result.lap_analysis.horse_evaluations.get(result.horse_name)
    if evaluation is None:
        return 0.0
    return evaluation.score


def calculate_course_score(result: AnalysisResult) -> float:
    """コース辞書から見た簡易コース適性を点数化します。

    今は「その馬の脚質がコース辞書の有利脚質に合うか」を見ます。
    将来は枠順、騎手、コース実績などを足して本格化できます。
    """

    running_style = get_running_style(result)
    course_profile = result.pace_analysis.course_profile

    if running_style in course_profile.favorable_styles:
        return 80.0
    return 55.0
