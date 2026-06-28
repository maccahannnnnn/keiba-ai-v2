import csv
from datetime import datetime
from pathlib import Path

from analyzer.schemas import PastRace, TodayEntry


# この状態の馬は、予想や特徴量出力の対象から外します。
EXCLUDED_STATUSES = {"取消", "除外"}


def load_past_races(file_path: str) -> list[PastRace]:
    """過去レースCSVを読み込み、Pythonで扱いやすい形に変換します。"""

    races: list[PastRace] = []

    # encoding="utf-8" は、日本語を文字化けさせにくくするための指定です。
    with open(file_path, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            races.append(
                PastRace(
                    race_date=datetime.strptime(row["race_date"], "%Y-%m-%d"),
                    race_id=row["race_id"],
                    horse_name=row["horse_name"],
                    jockey=row["jockey"],
                    distance=int(row["distance"]),
                    track_condition=row["track_condition"],
                    field_size=int(row["field_size"]),
                    class_level=row["class_level"],
                    popularity=int(row["popularity"]),
                    finish_position=int(row["finish_position"]),
                    corner_positions=row["corner_positions"],
                    running_style=row["running_style"],
                    pace=row["pace"],
                    body_weight=int(row["body_weight"]),
                    body_weight_diff=int(row["body_weight_diff"]),
                    sire=row["sire"],
                    dam_sire=row["dam_sire"],
                )
            )

    return races


def load_today_entries(file_path: str) -> list[TodayEntry]:
    """分析対象の出走馬だけを読み込みます。取消・除外馬は含めません。"""

    active_entries, _ = load_today_entries_with_exclusions(file_path)
    return active_entries


def load_today_entries_with_exclusions(file_path: str) -> tuple[list[TodayEntry], list[TodayEntry]]:
    """today_entries.csvを読み込み、分析対象馬と分析対象外の馬に分けます。"""

    entries: list[TodayEntry] = []
    excluded_entries: list[TodayEntry] = []
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"{file_path} が見つかりません。data/today_entries_template.csv をコピーして、"
            "data/today_entries.csv を作成してください。"
        )

    with path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        for row in reader:
            entry = TodayEntry(
                race_date=row_text(row, "race_date"),
                racecourse=row_text(row, "racecourse"),
                race_number=to_int(row.get("race_number")),
                surface=row_text(row, "surface"),
                status=normalize_status(row_text(row, "status")),
                horse_number=to_int(row.get("horse_number")),
                horse_name=row_text(row, "horse_name"),
                frame_number=to_int(row.get("frame_number")),
                jockey=row_text(row, "jockey"),
                distance=to_int(row.get("distance")),
                track_condition=row_text(row, "track_condition"),
                weight=to_float(row.get("weight")),
                body_weight=to_int(row.get("body_weight")),
                body_weight_diff=to_int(row.get("body_weight_diff")),
                running_style=row_text(row, "running_style"),
                last_runs=row_text(row, "last_runs"),
                past_lap_note=row_text(row, "past_lap_note"),
                expected_lap_note=row_text(row, "expected_lap_note"),
                sire=row_text(row, "sire"),
                dam_sire=row_text(row, "dam_sire"),
                bloodline_note=row_text(row, "bloodline_note"),
                class_level=row_text(row, "class_level"),
            )

            if entry.status in EXCLUDED_STATUSES:
                excluded_entries.append(entry)
            else:
                entries.append(entry)

    return entries, excluded_entries


def normalize_status(value: str) -> str:
    """status が空欄や不明なら、通常出走として扱います。"""

    if value in {"", "不明"}:
        return "出走"
    return value


def row_text(row: dict[str, str], key: str) -> str:
    """CSVの空欄や不足列を「不明」として扱います。"""

    value = row.get(key, "")
    if value is None or value.strip() == "":
        return "不明"
    return value.strip()


def to_int(value: str | None) -> int:
    """CSVの文字を整数に変換します。空欄や不明は0にします。"""

    if value is None or value.strip() in {"", "不明"}:
        return 0
    return int(value)


def to_float(value: str | None) -> float:
    """CSVの文字を小数に変換します。空欄や不明は0.0にします。"""

    if value is None or value.strip() in {"", "不明"}:
        return 0.0
    return float(value)
