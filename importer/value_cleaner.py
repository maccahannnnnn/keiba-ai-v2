import re

from importer.csv_normalizer import KEIBAAI_V1_COLUMNS


TARGET_COLUMNS = KEIBAAI_V1_COLUMNS


def normalize_row(row: dict[str, str]) -> dict[str, str]:
    """入力ゆれを整えて、today_entries.csv の列をすべて埋めます。"""

    normalized = {column: row.get(column, "").strip() for column in TARGET_COLUMNS}

    surface, distance = split_surface_distance(normalized["surface"], normalized["distance"])
    normalized["surface"] = surface
    normalized["distance"] = distance

    body_weight, body_weight_diff = split_body_weight(
        normalized["body_weight"],
        normalized["body_weight_diff"],
    )
    normalized["body_weight"] = body_weight
    normalized["body_weight_diff"] = body_weight_diff

    normalized["race_number"] = only_number(normalized["race_number"])
    normalized["horse_number"] = only_number(normalized["horse_number"])
    normalized["frame_number"] = only_number(normalized["frame_number"])
    normalized["weight"] = normalize_weight(normalized["weight"])
    normalized["last_runs"] = normalize_last_runs(normalized["last_runs"])

    return normalized


def split_surface_distance(surface: str, distance: str) -> tuple[str, str]:
    """`芝1800m` のような文字から、コース種別と距離を分けます。"""

    combined = surface if surface else distance
    match = re.search(r"(芝|ダート|障害)?\s*(\d{3,4})", combined)

    if match:
        parsed_surface = match.group(1) or surface
        parsed_distance = match.group(2)
        return parsed_surface, parsed_distance

    return surface, only_number(distance)


def split_body_weight(body_weight: str, body_weight_diff: str) -> tuple[str, str]:
    """`492(+0)` のような馬体重を、体重と増減に分けます。"""

    match = re.search(r"(\d{3})\s*\(([+-]?\d+)\)", body_weight)
    if match:
        return match.group(1), match.group(2)

    return only_number(body_weight), normalize_signed_number(body_weight_diff)


def only_number(value: str) -> str:
    """文字列から数字だけを取り出します。"""

    match = re.search(r"\d+", value)
    return match.group(0) if match else ""


def normalize_signed_number(value: str) -> str:
    """増減のようにプラス・マイナスがある数字を整えます。"""

    match = re.search(r"[+-]?\d+", value)
    return match.group(0) if match else ""


def normalize_weight(value: str) -> str:
    """斤量を小数の文字に整えます。"""

    match = re.search(r"\d+(?:\.\d+)?", value)
    return match.group(0) if match else ""


def normalize_last_runs(value: str) -> str:
    """過去走を `1-3-4-2-1` の形に整えます。"""

    numbers = re.findall(r"\d+", value)
    return "-".join(numbers[:5])
