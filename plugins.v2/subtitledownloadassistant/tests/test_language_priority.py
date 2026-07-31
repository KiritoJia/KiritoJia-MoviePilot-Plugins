"""中文字幕准入与候选排序测试。"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def _module(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


def _load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_domain() -> tuple[types.ModuleType, types.ModuleType, types.ModuleType, types.ModuleType]:
    root = Path(__file__).resolve().parents[1]
    package = "subtitledownloadassistant_language_test"
    package_module = _module(package)
    package_module.__path__ = [str(root)]
    domain = _module(f"{package}.domain")
    domain.__path__ = [str(root / "domain")]
    enums = _load_module(f"{package}.domain.enums", root / "domain/enums.py")
    models = _load_module(f"{package}.domain.models", root / "domain/models.py")
    language = _load_module(f"{package}.domain.language", root / "domain/language.py")
    ranking = _load_module(f"{package}.domain.ranking", root / "domain/ranking.py")
    return enums, models, language, ranking


def test_chinese_language_priority_and_package_order() -> None:
    enums, models, language, ranking = _load_domain()

    def candidate(
        key: str,
        language_marker: str,
        *,
        name: str = "字幕",
        metadata: dict[str, object] | None = None,
        package_scope=None,
        translation_type=None,
    ):
        return models.SubtitleCandidate(
            stable_key=key,
            source=enums.SubtitleSource.ASSRT,
            name=name,
            format="ASS",
            language=language_marker,
            metadata=metadata or {},
            package_scope=package_scope or enums.PackageScope.EPISODE,
            translation_type=translation_type or enums.TranslationType.HUMAN,
        )

    bilingual = candidate("bilingual", "简中&英文")
    bilingual_flags = candidate(
        "bilingual-flags",
        "",
        metadata={"language_flags": {"langchs": True, "langeng": True}},
    )
    simplified = candidate("simplified", "zh-CN")
    traditional = candidate("traditional", "繁體中文")
    unsupported = candidate("unsupported", "English")

    assert language.candidate_chinese_priority(bilingual) == 0
    assert language.candidate_chinese_priority(bilingual_flags) == 0
    assert language.candidate_chinese_priority(simplified) == 1
    assert language.candidate_chinese_priority(traditional) == 2
    assert language.candidate_chinese_priority(unsupported) == 99
    assert language.candidate_has_supported_chinese(traditional) is True
    assert language.candidate_has_supported_chinese(unsupported) is False

    bilingual_machine = candidate(
        "bilingual-machine",
        "简英双语",
        translation_type=enums.TranslationType.MACHINE,
    )
    ordered = ranking.sort_candidates(
        [traditional, simplified, bilingual_machine],
        ["ASS", "SRT"],
        ["assrt"],
    )
    assert [item.stable_key for item in ordered] == [
        "bilingual-machine",
        "simplified",
        "traditional",
    ]

    season_pack = candidate(
        "season-pack",
        "简中",
        package_scope=enums.PackageScope.SEASON_PACK,
    )
    episode = candidate(
        "episode",
        "简中",
        package_scope=enums.PackageScope.EPISODE,
    )
    ordered_scope = ranking.sort_candidates(
        [season_pack, episode],
        ["ASS"],
        ["assrt"],
    )
    assert [item.stable_key for item in ordered_scope] == ["episode", "season-pack"]
