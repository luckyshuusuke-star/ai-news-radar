from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.update_news import (
    JA_CACHE_DS_PREFIX,
    JA_CACHE_GOOGLE_PREFIX,
    add_japanese_fields,
    add_source_tier_fields,
    is_natural_japanese_title,
    is_valid_ja_summary_translation,
    is_valid_ja_translation,
    load_title_ja_cache,
    load_translation_glossary_ja,
    merge_story_items,
    repair_ja_title_translation,
)


ROOT = Path(__file__).resolve().parents[1]
EN_TITLE = "OpenAI launches a new Codex agent for developers"
ZH_TITLE = "OpenAI 为开发者推出全新 Codex 智能体"
JA_TITLE = "OpenAIが開発者向けに新しいCodexエージェントを公開"
DS_ENV = {"DEEPSEEK_API_KEY": "sk-test", "JA_DEEPSEEK_ENABLED": "1"}


def item(title: str = EN_TITLE, url: str = "https://example.com/news") -> dict:
    return {"title": title, "title_original": title, "url": url}


def deepseek_response(content: str = JA_TITLE, status: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = {"choices": [{"message": {"content": content}}]}
    return response


def google_session(content: str = JA_TITLE) -> MagicMock:
    session = MagicMock()
    response = MagicMock()
    response.json.return_value = [[[content, EN_TITLE]]]
    response.raise_for_status.return_value = None
    session.get.return_value = response
    return session


def enrich(title: str, session: MagicMock, cache: dict[str, str] | None = None):
    items, _, cache_out = add_japanese_fields(
        [item(title)],
        [],
        session,
        cache or {},
        max_new_translations=10,
    )
    return items[0], cache_out


def test_english_to_japanese_deepseek_success_skips_google():
    session = google_session()
    with patch.dict("os.environ", DS_ENV, clear=True), patch(
        "scripts.update_news.requests.post",
        return_value=deepseek_response(),
    ):
        result, cache = enrich(EN_TITLE, session)

    assert result["title_ja"] == JA_TITLE
    assert cache[JA_CACHE_DS_PREFIX + EN_TITLE] == JA_TITLE
    session.get.assert_not_called()


def test_chinese_to_japanese_is_direct_from_original():
    session = google_session("OpenAIが開発者向けに新しいCodexエージェントを発表")
    with patch.dict("os.environ", {}, clear=True):
        result, cache = enrich(ZH_TITLE, session)

    assert result["title_ja"].startswith("OpenAIが")
    assert cache[JA_CACHE_GOOGLE_PREFIX + ZH_TITLE] == result["title_ja"]
    assert session.get.call_args.kwargs["params"]["q"] == ZH_TITLE
    assert session.get.call_args.kwargs["params"]["tl"] == "ja"


def test_natural_japanese_original_is_preserved_without_network():
    original = "OpenAIが新しい音声モデルを発表"
    session = MagicMock()
    with patch.dict("os.environ", DS_ENV, clear=True), patch(
        "scripts.update_news.requests.post"
    ) as post:
        result, cache = enrich(original, session)

    assert result["title_ja"] == original
    assert cache == {}
    post.assert_not_called()
    session.get.assert_not_called()


def test_chinese_title_with_katakana_product_term_is_not_treated_as_japanese():
    mixed_title = (
        "OpenAI\u63a8\u51fa\u65b0\u30e2\u30c7\u30eb"
        "\u5e76\u5f00\u653eAPI"
    )

    assert is_natural_japanese_title(mixed_title) is False
    assert is_valid_ja_translation("English source title", mixed_title) is False
    assert is_valid_ja_summary_translation(
        "English source summary with sufficient detail.", mixed_title
    ) is False


def test_common_japanese_kanji_do_not_make_a_valid_translation_look_chinese():
    title = "AIが社会に与える影響を分析"

    assert is_natural_japanese_title(title) is True
    assert is_valid_ja_translation("Analyzing AI's impact on society", title) is True


def test_deepseek_failure_falls_back_to_google():
    session = google_session()
    with patch.dict("os.environ", DS_ENV, clear=True), patch(
        "scripts.update_news.requests.post",
        return_value=deepseek_response(status=500),
    ):
        result, cache = enrich(EN_TITLE, session)

    assert result["title_ja"] == JA_TITLE
    assert cache[JA_CACHE_GOOGLE_PREFIX + EN_TITLE] == JA_TITLE


def test_both_providers_fail_leaves_original_as_ui_fallback():
    session = MagicMock()
    session.get.side_effect = RuntimeError("offline")
    with patch.dict("os.environ", DS_ENV, clear=True), patch(
        "scripts.update_news.requests.post",
        return_value=deepseek_response(status=500),
    ):
        result, cache = enrich(EN_TITLE, session)

    assert result["title_original"] == EN_TITLE
    assert result["title_ja"] is None
    assert cache == {}


def test_japanese_cache_file_and_namespaces_are_independent(tmp_path: Path):
    path = tmp_path / "title-ja-cache.json"
    path.write_text(
        f'{{"{JA_CACHE_DS_PREFIX}{EN_TITLE}": "{JA_TITLE}"}}',
        encoding="utf-8",
    )
    cache = load_title_ja_cache(path)

    assert cache[JA_CACHE_DS_PREFIX + EN_TITLE] == JA_TITLE
    assert all(not key.startswith("ds1|") for key in cache)


def test_japanese_glossary_repairs_are_independent(tmp_path: Path):
    glossary = tmp_path / "translation-glossary-ja.txt"
    glossary.write_text("誤訳 => Codex @Codex\nOpenAI\n", encoding="utf-8")

    protected, repairs = load_translation_glossary_ja(glossary)
    assert protected == ["OpenAI"]
    assert repairs == [("誤訳", "Codex", "Codex")]

    with patch("scripts.update_news._JA_GLOSSARY_CACHE", (protected, repairs)):
        assert repair_ja_title_translation("Codex update", "誤訳の更新") == "Codexの更新"


def test_refusal_chinese_and_too_short_outputs_are_not_cached_or_displayed():
    session = MagicMock()
    session.get.side_effect = RuntimeError("offline")
    for invalid in ("申し訳ありませんが、翻訳できません", "先駆", "OpenAI为开发者推出全新智能体"):
        with patch.dict("os.environ", DS_ENV, clear=True), patch(
            "scripts.update_news.requests.post",
            return_value=deepseek_response(invalid),
        ):
            result, cache = enrich(EN_TITLE, session)
        assert result["title_ja"] is None
        assert cache == {}
        assert not is_valid_ja_translation(EN_TITLE, invalid)


def test_adding_japanese_fields_does_not_modify_chinese_fields():
    original = {
        **item(),
        "title_zh": "OpenAI 为开发者推出 Codex",
        "title_enhanced_zh": "OpenAI 发布面向开发者的 Codex 智能体",
        "recommend_reason_zh": "中文推荐理由",
    }
    with patch.dict("os.environ", {}, clear=True):
        items, _, _ = add_japanese_fields([original], [], google_session(), {}, 10)

    for field in ("title_zh", "title_enhanced_zh", "recommend_reason_zh"):
        assert items[0][field] == original[field]


def test_japanese_fields_do_not_change_story_merge_identity():
    now = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
    base = add_source_tier_fields(
        {
            "id": "a",
            "site_id": "aihot",
            "site_name": "AI HOT",
            "source": "Test",
            "title": EN_TITLE,
            "title_original": EN_TITLE,
            "url": "https://example.com/story?utm_source=rss",
            "published_at": now.isoformat(),
            "ai_is_related": True,
            "ai_score": 0.9,
        }
    )
    translated = {
        **base,
        "id": "b",
        "url": "https://example.com/story?ref=feed",
        "title_ja": JA_TITLE,
    }
    stories, events = merge_story_items([base, translated], now, 24)

    assert len(stories) == 1
    assert events[0]["reason"] == "canonical_url"
    assert stories[0]["primary_item"]["title_ja"] in (None, JA_TITLE)
    assert stories[0]["importance_label_ja"] in {
        "公式アップデート",
        "複数ソースで話題",
        "業界動向",
        "要注目",
    }
    assert stories[0]["importance_label"] in {
        "官方更新",
        "多源热议",
        "行业动态",
        "值得关注",
    }


def test_both_views_use_the_same_japanese_title_priority():
    for relative in ("assets/app.js", "classic/assets/app.js"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        block = source[source.index("function itemTitleText"):source.index("function itemTitleText") + 500]
        assert re.search(
            r"item\?\.title_ja\s*\|\|\s*item\?\.title_original\s*"
            r"\|\|\s*item\?\.title_en\s*"
            r"\|\|\s*originalTitleValue\(item\?\.title\)",
            block,
        )
        assert "title_zh" not in block


def test_japanese_pages_keep_links_and_have_no_mojibake():
    for relative in ("index.html", "classic/index.html"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert '<html lang="ja"' in source
        assert "https://github.com/LearnPrompt/ai-news-radar" in source
        assert "�" not in source


def test_reader_ui_has_no_known_project_generated_chinese_labels():
    forbidden = (
        'Intl.DateTimeFormat("zh-CN"',
        "抖音自媒体",
        "小红书自媒体",
        "`X 博主 ${",
        " 源正常",
        " · 失败",
    )
    for relative in ("assets/app.js", "classic/assets/app.js"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase not in source

    classic = (ROOT / "classic/assets/app.js").read_text(encoding="utf-8")
    assert "story.importance_label_ja" in classic
    assert "imp.textContent = story.importance_label;" not in classic
