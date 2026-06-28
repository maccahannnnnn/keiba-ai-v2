from dataclasses import dataclass


TARGET_COLUMNS = [
    "race_date",
    "racecourse",
    "race_number",
    "distance",
    "surface",
    "track_condition",
    "horse_number",
    "horse_name",
    "frame_number",
    "jockey",
    "weight",
    "body_weight",
    "body_weight_diff",
    "running_style",
    "last_runs",
    "past_lap_note",
    "expected_lap_note",
    "sire",
    "dam_sire",
    "bloodline_note",
]
"""分析AIが読む today_entries.csv の列順です。"""


@dataclass
class NormalizedEntry:
    """HTMLや元CSVから読み取った出走馬1頭分のデータです。"""

    race_date: str = ""
    racecourse: str = ""
    race_number: str = ""
    distance: str = ""
    surface: str = ""
    track_condition: str = ""
    horse_number: str = ""
    horse_name: str = ""
    frame_number: str = ""
    jockey: str = ""
    weight: str = ""
    body_weight: str = ""
    body_weight_diff: str = ""
    running_style: str = ""
    last_runs: str = ""
    past_lap_note: str = ""
    expected_lap_note: str = ""
    sire: str = ""
    dam_sire: str = ""
    bloodline_note: str = ""

    def to_row(self) -> dict[str, str]:
        """CSVに書き込むため、辞書形式に変換します。"""

        return {column: getattr(self, column) for column in TARGET_COLUMNS}
