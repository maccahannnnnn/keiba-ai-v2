from dataclasses import dataclass


@dataclass(frozen=True)
class HistoryGradeProfile:
    """過去走評価のランク定義です。

    ここは評価ロジックではなく、「何点ならどの評価か」という知識を管理します。
    将来、ランク名やコメントを変えたい場合はこの辞書を編集します。
    """

    grade: str
    min_score: float
    comment: str


HISTORY_GRADE_PROFILES = [
    HistoryGradeProfile("A", 80, "近走内容優秀"),
    HistoryGradeProfile("B", 65, "近走内容は安定"),
    HistoryGradeProfile("C", 50, "標準的な近走内容"),
    HistoryGradeProfile("D", 0, "近走内容に課題あり"),
]


HISTORY_COMMENT_RULES = {
    "all_board": "近5走すべて掲示板以内",
    "stable": "成績が安定",
    "rising": "近走で上昇傾向",
    "declining": "近走で下降傾向",
    "distance_match": "距離実績あり",
    "class_consistent": "同程度のクラスを継続して経験",
    "missing_margin": "着差データなし",
    "missing_closing": "上がり順位データなし",
}
"""history_comment に使う定型コメントです。"""


def get_history_grade(score: float) -> HistoryGradeProfile:
    """history_score からランク定義を取得します。"""

    for profile in HISTORY_GRADE_PROFILES:
        if score >= profile.min_score:
            return profile
    return HISTORY_GRADE_PROFILES[-1]
