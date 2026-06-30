"""競馬場別コース知識ライブラリの入口です。

CourseProfile は knowledge.courses.base で定義しています。
ここでは循環 import を避けるため、各競馬場の辞書を必要になった時だけ読み込みます。
"""

__all__ = [
    "FUKUSHIMA_COURSE_PROFILES",
    "HAKODATE_COURSE_PROFILES",
    "KOKURA_COURSE_PROFILES",
    "SAPPORO_COURSE_PROFILES",
    "NIIGATA_COURSE_PROFILES",
    "TOKYO_COURSE_PROFILES",
    "NAKAYAMA_COURSE_PROFILES",
    "CHUKYO_COURSE_PROFILES",
    "KYOTO_COURSE_PROFILES",
    "HANSHIN_COURSE_PROFILES",
]


def __getattr__(name: str):
    """競馬場別の辞書を遅延読み込みします。"""

    if name == "FUKUSHIMA_COURSE_PROFILES":
        from knowledge.courses.fukushima import FUKUSHIMA_COURSE_PROFILES

        return FUKUSHIMA_COURSE_PROFILES
    if name == "HAKODATE_COURSE_PROFILES":
        from knowledge.courses.hakodate import HAKODATE_COURSE_PROFILES

        return HAKODATE_COURSE_PROFILES
    if name == "KOKURA_COURSE_PROFILES":
        from knowledge.courses.kokura import KOKURA_COURSE_PROFILES

        return KOKURA_COURSE_PROFILES
    if name == "SAPPORO_COURSE_PROFILES":
        from knowledge.courses.sapporo import SAPPORO_COURSE_PROFILES

        return SAPPORO_COURSE_PROFILES
    if name == "NIIGATA_COURSE_PROFILES":
        from knowledge.courses.niigata import NIIGATA_COURSE_PROFILES

        return NIIGATA_COURSE_PROFILES
    if name == "TOKYO_COURSE_PROFILES":
        from knowledge.courses.tokyo import TOKYO_COURSE_PROFILES

        return TOKYO_COURSE_PROFILES
    if name == "NAKAYAMA_COURSE_PROFILES":
        from knowledge.courses.nakayama import NAKAYAMA_COURSE_PROFILES

        return NAKAYAMA_COURSE_PROFILES
    if name == "CHUKYO_COURSE_PROFILES":
        from knowledge.courses.chukyo import CHUKYO_COURSE_PROFILES

        return CHUKYO_COURSE_PROFILES
    if name == "KYOTO_COURSE_PROFILES":
        from knowledge.courses.kyoto import KYOTO_COURSE_PROFILES

        return KYOTO_COURSE_PROFILES
    if name == "HANSHIN_COURSE_PROFILES":
        from knowledge.courses.hanshin import HANSHIN_COURSE_PROFILES

        return HANSHIN_COURSE_PROFILES
    raise AttributeError(f"module 'knowledge.courses' has no attribute {name!r}")
