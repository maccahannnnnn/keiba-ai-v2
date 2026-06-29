"""競馬場別コース知識ライブラリの入口です。

CourseProfile は knowledge.courses.base で定義しています。
ここでは循環 import を避けるため、各競馬場の辞書を必要になった時だけ読み込みます。
"""

__all__ = [
    "FUKUSHIMA_COURSE_PROFILES",
    "HAKODATE_COURSE_PROFILES",
    "KOKURA_COURSE_PROFILES",
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
    raise AttributeError(f"module 'knowledge.courses' has no attribute {name!r}")
