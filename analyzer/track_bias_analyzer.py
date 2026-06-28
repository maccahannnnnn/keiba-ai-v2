from dataclasses import dataclass

from analyzer.schemas import TodayEntry
from knowledge.track_bias import TrackBiasProfile, get_track_bias_profile


@dataclass
class TrackBiasHorseEvaluation:
    """1頭ごとの馬場バイアス適性です。"""

    horse_number: int
    horse_name: str
    running_style: str
    frame_number: int
    score: float
    reason: str


@dataclass
class TrackBiasAnalysis:
    """レース全体の馬場バイアス分析です。"""

    profile: TrackBiasProfile
    favorable_styles: list[str]
    favorable_frames: list[str]
    clock_tendency: str
    pace_compatibility: str
    reason: str
    horse_evaluations: dict[str, TrackBiasHorseEvaluation]

    def to_features(self) -> dict[str, float]:
        """将来、機械学習に渡しやすい数値へ変換します。"""

        return {
            "track_bias_inner_favorable": 1.0 if self.profile.inner_favorable else 0.0,
            "track_bias_outer_favorable": 1.0 if self.profile.outer_favorable else 0.0,
            "track_bias_front_favorable": 1.0 if self.profile.front_favorable else 0.0,
            "track_bias_closing_favorable": 1.0 if self.profile.closing_favorable else 0.0,
            "track_bias_fast_clock": 1.0 if self.profile.fast_clock else 0.0,
            "track_bias_slow_clock": 1.0 if self.profile.slow_clock else 0.0,
        }


def analyze_track_bias(entries: list[TodayEntry], pace_analysis) -> TrackBiasAnalysis:
    """入力されたレース条件から馬場バイアスを分析します。"""

    if not entries:
        profile = get_track_bias_profile("", "", 0)
        return TrackBiasAnalysis(
            profile=profile,
            favorable_styles=profile.favorable_styles(),
            favorable_frames=profile.favorable_frames(),
            clock_tendency=profile.clock_tendency(),
            pace_compatibility="出走馬データなし",
            reason="出走馬データがないため分析不可",
            horse_evaluations={},
        )

    first_entry = entries[0]
    profile = get_track_bias_profile(
        first_entry.racecourse,
        first_entry.surface,
        first_entry.distance,
    )
    favorable_styles = adjust_styles_by_condition(
        profile.favorable_styles(),
        first_entry.track_condition,
        profile,
    )
    favorable_frames = adjust_frames_by_condition(
        profile.favorable_frames(),
        first_entry.track_condition,
        profile,
    )
    clock_tendency = adjust_clock_by_condition(
        profile.clock_tendency(),
        first_entry.track_condition,
        profile,
    )
    pace_compatibility = describe_pace_compatibility(favorable_styles, pace_analysis.pace)
    reason = build_track_bias_reason(profile, first_entry.track_condition, pace_compatibility)

    horse_evaluations = {
        entry.horse_name: evaluate_horse_track_bias(
            entry,
            favorable_styles,
            favorable_frames,
            clock_tendency,
        )
        for entry in entries
    }

    return TrackBiasAnalysis(
        profile=profile,
        favorable_styles=favorable_styles,
        favorable_frames=favorable_frames,
        clock_tendency=clock_tendency,
        pace_compatibility=pace_compatibility,
        reason=reason,
        horse_evaluations=horse_evaluations,
    )


def adjust_styles_by_condition(
    base_styles: list[str],
    track_condition: str,
    profile: TrackBiasProfile,
) -> list[str]:
    """当日馬場状態を見て、有利脚質を微調整します。"""

    styles = list(base_styles)
    if track_condition in {"重", "不良"} and profile.closing_favorable:
        styles = add_unique(styles, ["差し", "追込"])
    elif track_condition in {"重", "不良"} and profile.front_favorable:
        styles = add_unique(styles, ["逃げ", "先行"])
    return styles


def adjust_frames_by_condition(
    base_frames: list[str],
    track_condition: str,
    profile: TrackBiasProfile,
) -> list[str]:
    """当日馬場状態を見て、有利枠を微調整します。"""

    frames = list(base_frames)
    if track_condition in {"重", "不良"} and profile.outer_favorable:
        frames = add_unique(frames, ["外枠"])
    return frames


def adjust_clock_by_condition(
    base_clock: str,
    track_condition: str,
    profile: TrackBiasProfile,
) -> str:
    """当日馬場状態を見て、時計傾向を決めます。"""

    if track_condition in {"重", "不良"}:
        if profile.surface == "芝":
            return "時計が掛かる"
        if profile.surface == "ダート":
            return "脚抜きが良く時計が速い"
    if track_condition == "稍重" and profile.surface == "芝":
        return "やや時計が掛かる"
    return base_clock


def describe_pace_compatibility(favorable_styles: list[str], pace: str) -> str:
    """馬場バイアスと展開予想の相性を説明します。"""

    front_styles = {"逃げ", "先行"}
    closing_styles = {"差し", "追込"}
    favorable_set = set(favorable_styles)

    if pace == "スロー" and favorable_set & front_styles:
        return "スロー想定と前有利バイアスが合う"
    if pace == "ハイ" and favorable_set & closing_styles:
        return "ハイ想定と差し有利バイアスが合う"
    if pace == "平均":
        return "平均ペース想定のため、馬場バイアスに合う馬を素直に評価"
    return "展開と馬場バイアスが完全には一致しない"


def evaluate_horse_track_bias(
    entry: TodayEntry,
    favorable_styles: list[str],
    favorable_frames: list[str],
    clock_tendency: str,
) -> TrackBiasHorseEvaluation:
    """1頭ごとに馬場バイアスへの適性を評価します。"""

    score = 55.0
    reasons: list[str] = []

    if entry.running_style in favorable_styles:
        score += 20
        reasons.append(f"脚質{entry.running_style}が馬場バイアスに合う")
    else:
        score -= 5
        reasons.append(f"脚質{entry.running_style}は馬場バイアスの中心ではない")

    frame_type = classify_frame(entry.frame_number)
    if frame_type in favorable_frames:
        score += 15
        reasons.append(f"{frame_type}が有利枠傾向に合う")
    elif "大きな偏りなし" in favorable_frames:
        reasons.append("枠順の大きな偏りはなし")
    else:
        score -= 5
        reasons.append(f"{frame_type}は有利枠傾向から少し外れる")

    if "速い" in clock_tendency and any(word in entry.bloodline_note for word in ["瞬発", "末脚", "スピード", "良馬場"]):
        score += 5
        reasons.append("速い時計へのメモがある")
    if "掛かる" in clock_tendency and any(word in entry.bloodline_note for word in ["持続", "パワー", "重", "道悪"]):
        score += 5
        reasons.append("時計が掛かる馬場へのメモがある")

    return TrackBiasHorseEvaluation(
        horse_number=entry.horse_number,
        horse_name=entry.horse_name,
        running_style=entry.running_style,
        frame_number=entry.frame_number,
        score=clamp(score),
        reason="、".join(reasons),
    )


def classify_frame(frame_number: int) -> str:
    """枠番を内枠・中枠・外枠に分けます。"""

    if frame_number <= 3:
        return "内枠"
    if frame_number >= 6:
        return "外枠"
    return "中枠"


def build_track_bias_reason(
    profile: TrackBiasProfile,
    track_condition: str,
    pace_compatibility: str,
) -> str:
    """レポートに出す馬場バイアス理由を作ります。"""

    notes = " / ".join(profile.notes)
    return (
        f"{profile.racecourse}{profile.surface}{profile.distance}mは"
        f"{'・'.join(profile.favorable_frames())}、"
        f"{'・'.join(profile.favorable_styles())}を評価。"
        f"当日馬場は{track_condition}。"
        f"雨の影響: {profile.rain_impact}。"
        f"馬場悪化時: {profile.deterioration_trend}。"
        f"{pace_compatibility}。"
        f"補足: {notes}"
    )


def add_unique(base: list[str], values: list[str]) -> list[str]:
    """重複しないようにリストへ追加します。"""

    result = list(base)
    for value in values:
        if value not in result:
            result.append(value)
    return result


def clamp(value: float, minimum: float = 0, maximum: float = 100) -> float:
    """点数を0〜100点に収めます。"""

    return round(max(minimum, min(maximum, value)), 1)
