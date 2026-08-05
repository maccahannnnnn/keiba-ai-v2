"""Column mapping tables for TARGET frontier JV trial importers.

The importers never depend on fixed column positions.  If TARGET changes
export order or a user changes the export template, update only the aliases
in this file.
"""


TARGET_ENTRY_COLUMN_MAP = {
    "horse_name": ["馬名", "horse_name", "name"],
    "frame_number": ["枠番", "枠", "frame", "frame_number"],
    "horse_number": ["馬番", "番", "horse_number"],
    "sex_age": ["性齢", "sex_age"],
    "weight_carried": ["斤量", "負担重量", "weight", "weight_carried"],
    "jockey": ["騎手", "jockey"],
    "sire": ["父", "種牡馬", "sire"],
    "dam": ["母", "dam"],
    "broodmare_sire": ["母父", "母父馬", "broodmare_sire", "dam_sire"],
    "trainer": ["調教師", "trainer"],
    "affiliation": ["所属", "affiliation"],
    "owner": ["馬主", "owner"],
    "breeder": ["生産者", "breeder"],
    "body_weight": ["当日馬体重", "馬体重", "body_weight"],
    "body_weight_diff": ["馬体重増減", "増減", "body_weight_diff"],
}


TARGET_HISTORY_COLUMN_MAP = {
    "horse_name": ["馬名", "horse_name", "name"],
    "race_date": ["日付", "年月日", "race_date", "date"],
    "race_name": ["レース名", "race_name"],
    "class_level": ["クラス", "class", "class_level"],
    "racecourse": ["場所", "競馬場", "racecourse"],
    "surface": ["芝ダ", "馬場種別", "surface"],
    "distance": ["距離", "distance"],
    "track_condition": ["馬場状態", "馬場", "track_condition"],
    "finish_position": ["着順", "finish_position"],
    "margin": ["着差", "margin"],
    "time": ["タイム", "time"],
    "adjusted_time": ["補正タイム", "adjusted_time"],
    "corner_1": ["1角", "1コーナー", "corner_1"],
    "corner_2": ["2角", "2コーナー", "corner_2"],
    "corner_3": ["3角", "3コーナー", "corner_3"],
    "corner_4": ["4角", "4コーナー", "corner_4"],
    "last_3f": ["上がり3F", "上り3F", "上3F", "last_3f"],
    "body_weight": ["馬体重", "body_weight"],
    "body_weight_diff": ["馬体重増減", "増減", "body_weight_diff"],
    "pci": ["PCI", "pci"],
    "rpci": ["RPCI", "rpci"],
}


TARGET_HISTORY_FIXED_COLUMN_MAP = {
    "year": 0,
    "month": 1,
    "day": 2,
    "racecourse": 4,
    "class_level": 8,
    "race_name": 9,
    "surface": 12,
    "distance": 14,
    "track_condition": 15,
    "horse_name": 16,
    "finish_position": 23,
    "margin": 26,
    "time_seconds": 28,
    "time": 29,
    "adjusted_time": 41,
    "sire": 46,
    "dam": 47,
    "broodmare_sire": 48,
    "corner_1": 31,
    "corner_2": 32,
    "corner_3": 33,
    "corner_4": 34,
    "last_3f": 35,
    "body_weight": 37,
    "body_weight_diff": 38,
    "pci": 51,
    "rpci": 52,
}
"""Headerless TARGET S fixed column map.

This is the only fixed-position table for TARGET S format.  The importer reads
through this table so future layout changes can be handled here.
"""


def get_mapped_value(row, column_map, field_name, default=None):
    """Return a row value by logical field name using the alias table."""

    aliases = column_map.get(field_name, [])
    normalized_row = {
        normalize_column_name(column_name): value
        for column_name, value in row.items()
    }

    for alias in aliases:
        normalized_alias = normalize_column_name(alias)
        if normalized_alias in normalized_row:
            value = normalized_row[normalized_alias]
            return clean_cell(value, default)
    return default


def get_fixed_value(row, fixed_column_map, field_name, default=None):
    """Return a row value by logical field name using fixed column mapping."""

    index = fixed_column_map.get(field_name)
    if index is None:
        return default
    if not isinstance(row, list) or index >= len(row):
        return default
    return clean_cell(row[index], default)


def clean_cell(value, default=None):
    """Normalize empty cells without changing meaningful text."""

    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def normalize_column_name(name):
    """Normalize column names for robust alias matching."""

    text = str(name).strip().lower()
    for char in [" ", "　", "_", "-", "・", "/", "\\", "(", ")", "（", "）"]:
        text = text.replace(char, "")
    return text
