from analyzer.schemas import PastRace, TodayEntry


def load_past_runs_from_local_csv(entry: TodayEntry, races: list[PastRace]) -> list[PastRace]:
    """手元CSVに保存済みの過去走データを返します。

    今は `data/sample_races.csv` のようなローカルCSVだけを使います。
    将来、JRA公式、JRA-VAN、netkeibaなどから競走馬成績を取得する場合も、
    最終的に `PastRace` のリストへ変換できれば分析側はそのまま使えます。
    """

    return [race for race in races if race.horse_name == entry.horse_name]


def fetch_past_runs_from_jra_official(entry: TodayEntry) -> list[PastRace]:
    """将来、JRA公式サイトから過去走を取得するための入口です。"""

    raise NotImplementedError("JRA公式サイトからの自動取得は、今後の段階で追加します")


def fetch_past_runs_from_jra_van(entry: TodayEntry) -> list[PastRace]:
    """将来、JRA-VANから過去走を取得するための入口です。"""

    raise NotImplementedError("JRA-VAN連携は、今後の段階で追加します")


def fetch_past_runs_from_netkeiba(entry: TodayEntry) -> list[PastRace]:
    """将来、netkeibaなどから過去走を取得するための入口です。"""

    raise NotImplementedError("netkeiba連携は、今後の段階で追加します")
