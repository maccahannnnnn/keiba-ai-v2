from dataclasses import dataclass

from importer.csv_normalizer import KEIBAAI_V1_COLUMNS

TARGET_COLUMNS = KEIBAAI_V1_COLUMNS
"""KeibaAI v1.0 標準CSVの列順です。"""


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
    class_level: str = ""

    def to_row(self) -> dict[str, str]:
        """CSVに書き込むため、辞書形式に変換します。"""

        return {column: getattr(self, column) for column in TARGET_COLUMNS}
