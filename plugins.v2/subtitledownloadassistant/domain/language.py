"""中文字幕准入、偏好与格式归一规则。"""

import re
from collections.abc import Iterable, Mapping

from .enums import TranslationType
from .models import SubtitleCandidate

_SIMPLIFIED_EXPLICIT = re.compile(r"(?:简体|简中|zh[-_ ]?(?:cn|hans)|\bchs\b)", re.IGNORECASE)
_TRADITIONAL_EXPLICIT = re.compile(
    r"(?:繁体|繁體|繁中|正体|正體|zh[-_ ]?(?:tw|hk|hant)|\b(?:cht|zht)\b)",
    re.IGNORECASE,
)
_ENGLISH_EXPLICIT = re.compile(r"(?:英文|英语|英語|\benglish\b|\beng\b|\ben[-_ ](?:us|gb)\b)", re.IGNORECASE)
_SIMPLIFIED_FLAG_KEYS = {"langchs", "zh-cn", "zh_cn", "zh-hans", "zh_hans", "chs"}
_TRADITIONAL_FLAG_KEYS = {"langcht", "zh-tw", "zh_tw", "zh-hk", "zh_hk", "zh-hant", "zh_hant", "cht", "zht"}
_ENGLISH_FLAG_KEYS = {"langeng", "en", "eng", "english", "en-us", "en_us", "en-gb", "en_gb"}
_BILINGUAL_COMPACT_MARKERS = ("简英", "简中英文", "简体英文", "中英双语", "中英文双语")
_DEFAULT_FORMAT_ORDER = ("ASS", "SSA", "SRT", "SUP")
UNSUPPORTED_CHINESE_PRIORITY = 99


def candidate_chinese_priority(candidate: SubtitleCandidate) -> int:
    """返回简英双语、简中、繁中的固定优先级，非中文返回 99。"""

    flags = candidate.metadata.get("language_flags")
    normalized_flags = {
        str(key).strip().lower()
        for key, value in (flags.items() if isinstance(flags, Mapping) else ())
        if bool(value)
    }
    descriptive_values = [
        candidate.language,
        candidate.name,
        candidate.file_name or "",
    ]
    for key in ("description", "release", "native_name", "videoname"):
        value = candidate.metadata.get(key)
        if isinstance(value, str):
            descriptive_values.append(value)
    text = " ".join(descriptive_values)
    compact = re.sub(r"[\s&+/,|·._-]+", "", text.casefold())
    simplified = bool(_SIMPLIFIED_EXPLICIT.search(text) or normalized_flags & _SIMPLIFIED_FLAG_KEYS)
    traditional = bool(_TRADITIONAL_EXPLICIT.search(text) or normalized_flags & _TRADITIONAL_FLAG_KEYS)
    english = bool(_ENGLISH_EXPLICIT.search(text) or normalized_flags & _ENGLISH_FLAG_KEYS)
    bilingual = any(marker in compact for marker in _BILINGUAL_COMPACT_MARKERS) or (simplified and english)
    if bilingual:
        return 0
    if simplified:
        return 1
    if traditional:
        return 2
    return UNSUPPORTED_CHINESE_PRIORITY


def candidate_has_supported_chinese(candidate: SubtitleCandidate) -> bool:
    """判断候选是否属于简英双语、简中或繁中。"""

    return candidate_chinese_priority(candidate) < UNSUPPORTED_CHINESE_PRIORITY


def candidate_is_allowed(candidate: SubtitleCandidate, allow_machine: bool) -> bool:
    """判断候选是否满足翻译类型与内容范围约束。"""

    if candidate.foreign_parts_only:
        return False
    return allow_machine or candidate.translation_type not in {TranslationType.MACHINE, TranslationType.AI}


def normalize_format_priority(
    allowed_extensions: Iterable[str],
    saved_priority: Iterable[str] | None = None,
) -> list[str]:
    """将配置顺序归一为宿主允许的完整且无重复格式列表。"""

    allowed: list[str] = []
    for item in allowed_extensions:
        normalized = str(item).strip().lstrip(".").upper()
        if normalized and normalized not in allowed:
            allowed.append(normalized)

    preferred = list(saved_priority or _DEFAULT_FORMAT_ORDER)
    result: list[str] = []
    for item in preferred:
        normalized = str(item).strip().lstrip(".").upper()
        if normalized in allowed and normalized not in result:
            result.append(normalized)
    result.extend(item for item in allowed if item not in result)
    return result
