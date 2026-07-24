from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.update_news import (
    JA_SUMMARY_CACHE_DS_PREFIX,
    JA_SUMMARY_CACHE_GOOGLE_PREFIX,
    add_japanese_fields,
    add_japanese_summaries,
    add_waytoagi_japanese_fields,
    build_japanese_translation_coverage,
    build_japanese_translation_policy,
    hot_story_translation_priority_sources,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "japanese-display.json"


def policy_args() -> argparse.Namespace:
    return argparse.Namespace(
        ja_translate_max_new=80,
        ja_translate_creator_max_new=20,
        ja_summary_max_new=30,
        ja_waytoagi_max_new=30,
    )


def test_incremental_profile_has_upstream_style_fixed_per_run_limits():
    with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}, clear=True):
        policy = build_japanese_translation_policy(policy_args())

    assert policy["limits"]["main_titles"] == 80
    assert policy["limits"]["summaries"] == 30
    assert policy["limits"]["creator_titles"] == 20
    assert policy["limits"]["waytoagi_title_or_summary_fields"] == 30
    assert policy["max_new_japanese_fields_per_run"] == 160
    assert policy["deepseek_enabled"] is False
    assert policy["max_paid_deepseek_requests_per_run"] == 0
    assert "mode" not in policy
    assert JA_SUMMARY_CACHE_DS_PREFIX.startswith("ja-summary-")
    assert JA_SUMMARY_CACHE_GOOGLE_PREFIX.startswith("ja-summary-")


def test_japanese_deepseek_is_independently_default_off_even_with_shared_key():
    source = "OpenAI launches a new Codex agent"
    item = {"title": source, "title_original": source, "url": "https://example.com"}
    session = MagicMock()
    response = MagicMock()
    response.json.return_value = [[["OpenAIが新しいCodexエージェントを公開", source]]]
    response.raise_for_status.return_value = None
    session.get.return_value = response

    with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}, clear=True), patch(
        "scripts.update_news.requests.post"
    ) as post:
        items, _, _ = add_japanese_fields([item], [], session, {}, 1)

    assert items[0]["title_ja"].startswith("OpenAIが")
    post.assert_not_called()


def test_enabled_deepseek_policy_stays_within_the_same_160_field_budget():
    with patch.dict(
        "os.environ",
        {"JA_DEEPSEEK_ENABLED": "1", "DEEPSEEK_API_KEY": "sk-test"},
        clear=True,
    ):
        policy = build_japanese_translation_policy(policy_args())

    assert set(policy["limits"]) == {
        "main_titles",
        "creator_titles",
        "summaries",
        "waytoagi_title_or_summary_fields",
    }
    assert policy["deepseek_enabled"] is True
    assert policy["max_new_japanese_fields_per_run"] == 160
    assert policy["max_paid_deepseek_requests_per_run"] == 160
    assert policy["max_keyless_google_requests_per_run"] == 160


def test_hot_titles_use_the_first_20_slots_of_the_shared_80_title_budget():
    regular_sources = [f"Regular English title {index}" for index in range(85)]
    priority_sources = regular_sources[65:85]
    items = [
        {
            "title": source,
            "title_original": source,
            "url": f"https://example.com/{index}",
        }
        for index, source in enumerate(regular_sources)
    ]

    with patch.dict("os.environ", {}, clear=True), patch(
        "scripts.update_news.translate_to_ja_google",
        side_effect=lambda _session, source: f"日本語のニュースタイトル{regular_sources.index(source)}",
    ) as translate, patch(
        "scripts.update_news.is_valid_ja_translation", return_value=True
    ):
        output, _, _ = add_japanese_fields(
            items,
            [],
            MagicMock(),
            {},
            max_new_translations=80,
            priority_sources=priority_sources,
        )

    attempted = [call.args[1] for call in translate.call_args_list]
    assert attempted[:20] == priority_sources
    assert attempted[20:] == regular_sources[:60]
    assert len(attempted) == 80
    assert [item["title_original"] for item in output] == regular_sources
    assert all(output[index]["title_ja"] for index in range(60))
    assert all(output[index]["title_ja"] is None for index in range(60, 65))
    assert all(output[index]["title_ja"] for index in range(65, 85))


def test_hot_story_priority_matches_multi_source_freshness_order_and_limit():
    now = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
    topics = [
        "amber falcon lattice",
        "birch galaxy compass",
        "cobalt harbor prism",
        "delta meadow turbine",
        "ember glacier signal",
        "forest helium circuit",
        "granite island beacon",
        "hazel junction orbit",
        "indigo kernel radar",
        "jade lantern vector",
        "kelp mountain sensor",
        "lunar nebula engine",
        "maple ocean matrix",
        "nickel prairie robot",
        "onyx quartz network",
        "pearl river compiler",
        "ruby summit protocol",
        "silver thunder database",
        "topaz valley processor",
        "umber willow satellite",
        "violet xenon browser",
        "winter yellow zephyr",
    ]
    items = []
    for index in range(22):
        source_count = 4 if index == 21 else 2
        published = now - timedelta(minutes=index)
        for source_index in range(source_count):
            title = f"{topics[index]} artificial intelligence research announcement"
            items.append(
                {
                    "id": f"{index}-{source_index}",
                    "site_id": f"site-{source_index}",
                    "site_name": f"Site {source_index}",
                    "source": f"Site {source_index}",
                    "title": title,
                    "title_original": title,
                    "url": f"https://example.com/story-{index}/source-{source_index}",
                    "published_at": published.isoformat(),
                    "ai_is_related": True,
                    "ai_score": 0.9,
                }
            )

    priorities = hot_story_translation_priority_sources(items, now, 24)

    assert len(priorities) == 20
    assert priorities[0].startswith(topics[0])
    assert any(source.startswith(topics[21]) for source in priorities[:3])


def test_failed_title_and_summary_attempts_still_consume_the_api_budget():
    title_items = [
        {"title": f"English title {index}", "title_original": f"English title {index}", "url": f"https://example.com/{index}"}
        for index in range(3)
    ]
    summary_items = [
        {**item, "summary": f"English summary for item {index} with enough detail."}
        for index, item in enumerate(title_items)
    ]
    session = MagicMock()
    session.get.side_effect = RuntimeError("offline")

    with patch.dict("os.environ", {}, clear=True):
        add_japanese_fields(title_items, [], session, {}, max_new_translations=1)
    assert session.get.call_count == 1

    session.reset_mock()
    session.get.side_effect = RuntimeError("offline")
    with patch.dict("os.environ", {}, clear=True):
        add_japanese_summaries(summary_items, [], session, {}, max_new_translations=1)
    assert session.get.call_count == 1


def test_duplicate_sources_across_pools_are_attempted_once_even_on_failure():
    source = "Same English title needing translation"
    summary = "Same English summary needing translation with sufficient detail."
    item = {
        "title": source,
        "title_original": source,
        "summary": summary,
        "url": "https://example.com/duplicate",
    }
    session = MagicMock()
    session.get.side_effect = RuntimeError("offline")

    with patch.dict("os.environ", {}, clear=True):
        ai_items, all_items, _ = add_japanese_fields([item], [item], session, {}, 10)
    assert session.get.call_count == 1
    assert ai_items[0]["title_ja"] is None
    assert all_items[0]["title_ja"] is None

    session.reset_mock()
    session.get.side_effect = RuntimeError("offline")
    with patch.dict("os.environ", {}, clear=True):
        ai_items, all_items, _ = add_japanese_summaries([item], [item], session, {}, 10)
    assert session.get.call_count == 1
    assert ai_items[0]["summary_ja"] is None
    assert all_items[0]["summary_ja"] is None


def test_duplicate_sources_across_pools_share_successful_results():
    source = "Same successful English title"
    summary = "Same successful English summary with enough detail."
    title_ja = "同じ英語タイトルの日本語訳です"
    summary_ja = "十分な詳細を含む同じ英語要約の日本語訳です。"
    item = {
        "title": source,
        "title_original": source,
        "summary": summary,
        "url": "https://example.com/success",
    }

    with patch.dict("os.environ", {}, clear=True), patch(
        "scripts.update_news.translate_to_ja_google", return_value=title_ja
    ) as translate_title:
        ai_items, all_items, _ = add_japanese_fields(
            [item], [item], MagicMock(), {}, max_new_translations=10
        )
    translate_title.assert_called_once()
    assert ai_items[0]["title_ja"] == title_ja
    assert all_items[0]["title_ja"] == title_ja

    with patch.dict("os.environ", {}, clear=True), patch(
        "scripts.update_news.translate_to_ja_google", return_value=summary_ja
    ) as translate_summary:
        ai_items, all_items, _ = add_japanese_summaries(
            [item], [item], MagicMock(), {}, max_new_translations=10
        )
    translate_summary.assert_called_once()
    assert ai_items[0]["summary_ja"] == summary_ja
    assert all_items[0]["summary_ja"] == summary_ja


def test_successful_cache_skips_network_on_the_next_generation():
    source = "Cached English title"
    title_ja = "キャッシュ済み英語タイトルの日本語訳"
    summary = "Cached English summary with enough detail for translation."
    summary_ja = "十分な詳細を含むキャッシュ済み英語要約の日本語訳です。"
    item = {
        "title": source,
        "title_original": source,
        "summary": summary,
        "url": "https://example.com/cached",
    }
    session = MagicMock()
    response = MagicMock()
    response.json.return_value = [[[title_ja, source]]]
    response.raise_for_status.return_value = None
    session.get.return_value = response

    with patch.dict("os.environ", {}, clear=True):
        first, _, cache = add_japanese_fields([item], [], session, {}, 1)
        session.reset_mock()
        second, _, _ = add_japanese_fields([item], [], session, cache, 1)

    assert first[0]["title_ja"] == title_ja
    assert second[0]["title_ja"] == title_ja
    session.get.assert_not_called()

    with patch.dict("os.environ", {}, clear=True), patch(
        "scripts.update_news.translate_to_ja_google", return_value=summary_ja
    ) as translate_summary:
        first, _, summary_cache = add_japanese_summaries([item], [], MagicMock(), {}, 1)
        second, _, _ = add_japanese_summaries(
            [item], [], MagicMock(), summary_cache, 1
        )

    assert first[0]["summary_ja"] == summary_ja
    assert second[0]["summary_ja"] == summary_ja
    translate_summary.assert_called_once()


def test_failed_source_can_retry_on_the_next_generation():
    source = "English title retried by a later scheduled run"
    summary = "English summary retried by a later scheduled run with enough detail."
    item = {
        "title": source,
        "title_original": source,
        "summary": summary,
        "url": "https://example.com/retry",
    }
    session = MagicMock()
    session.get.side_effect = RuntimeError("offline")

    with patch.dict("os.environ", {}, clear=True):
        _, _, cache = add_japanese_fields(
            [item], [], session, {}, 1, priority_sources=[source]
        )
        add_japanese_fields(
            [item], [], session, cache, 1, priority_sources=[source]
        )

    assert session.get.call_count == 2
    assert cache == {}

    session.reset_mock()
    session.get.side_effect = RuntimeError("offline")
    with patch.dict("os.environ", {}, clear=True):
        _, _, cache = add_japanese_summaries([item], [], session, {}, 1)
        add_japanese_summaries([item], [], session, cache, 1)

    assert session.get.call_count == 2
    assert cache == {}


def test_realistic_fixture_translates_english_chinese_creator_and_summaries():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    translations = {
        "OpenAI launches a new Codex agent for developers": "OpenAIが開発者向けの新しいCodexエージェントを公開",
        "OpenAI 发布面向开发者的新 Codex 智能体": "OpenAIが開発者向けの新しいCodexエージェントを発表",
        "实测新的AI视频生成工作流": "新しいAI動画生成ワークフローを実際に検証",
    }
    summaries = {
        fixture["items"][0]["summary"]: "OpenAIは長時間のソフトウェア開発タスクを実行できるCodexエージェントを発表しました。",
        fixture["items"][1]["summary"]: "このエージェントは長時間の開発タスクに対応し、元の情報源リンクも保持します。",
    }

    with patch.dict("os.environ", {}, clear=True), patch(
        "scripts.update_news.translate_to_ja_deepseek", return_value=None
    ), patch(
        "scripts.update_news.translate_to_ja_google",
        side_effect=lambda _session, text: translations.get(text) or summaries.get(text),
    ):
        items, _, title_cache = add_japanese_fields(
            fixture["items"], [], MagicMock(), {}, max_new_translations=10
        )
        items, _, summary_cache = add_japanese_summaries(
            items, [], MagicMock(), {}, max_new_translations=10
        )
        creators, _, title_cache = add_japanese_fields(
            fixture["creator_items_ai"], [], MagicMock(), title_cache, max_new_translations=10
        )

    assert all(item["title_ja"] for item in items)
    assert all(item["summary_ja"] for item in items)
    assert creators[0]["title_ja"] == translations[creators[0]["title_original"]]
    assert items[1]["summary"] == fixture["items"][1]["summary"]
    assert creators[0]["title"] == fixture["creator_items_ai"][0]["title"]
    assert title_cache
    assert summary_cache


def test_waytoagi_preserves_original_and_adds_japanese_fields_to_both_views():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload = fixture["waytoagi"]
    title_ja = "マルチエージェント協調チュートリアルを追加"
    summary_ja = "複数のエージェントが役割分担して複雑なタスクを進める方法を解説します。"

    with patch.dict("os.environ", {}, clear=True), patch(
        "scripts.update_news.translate_to_ja_deepseek", return_value=None
    ), patch(
        "scripts.update_news.translate_to_ja_google",
        side_effect=lambda _session, text: title_ja if text == payload["updates_7d"][0]["title"] else summary_ja,
    ):
        enriched, _, _ = add_waytoagi_japanese_fields(
            payload, MagicMock(), {}, {}, max_new_translations=10
        )

    for field in ("updates_today", "updates_7d"):
        update = enriched[field][0]
        assert update["title"] == payload[field][0]["title"]
        assert update["summary"] == payload[field][0]["summary"]
        assert update["title_ja"] == title_ja
        assert update["summary_ja"] == summary_ja


def test_waytoagi_duplicate_failed_sources_are_attempted_once_per_run():
    title = "Same English WaytoAGI title"
    summary = "Same English WaytoAGI summary with enough detail."
    payload = {
        "updates_7d": [
            {"date": "2026-07-17", "title": title, "summary": summary, "url": "https://example.com/a"},
            {"date": "2026-07-16", "title": title, "summary": summary, "url": "https://example.com/b"},
        ],
        "updates_today": [],
    }

    with patch.dict("os.environ", {}, clear=True), patch(
        "scripts.update_news.translate_to_ja_deepseek", return_value=None
    ), patch(
        "scripts.update_news.translate_to_ja_google", return_value=None
    ) as google:
        enriched, title_cache, summary_cache = add_waytoagi_japanese_fields(
            payload, MagicMock(), {}, {}, max_new_translations=10
        )

    assert google.call_count == 2
    assert all(item["title_ja"] is None for item in enriched["updates_7d"])
    assert all(item["summary_ja"] is None for item in enriched["updates_7d"])
    assert title_cache == {}
    assert summary_cache == {}


def test_waytoagi_uses_cached_summary_when_new_budget_is_zero():
    summary = "English WaytoAGI summary already translated in an earlier run."
    summary_ja = (
        "\u65e5\u672c\u8a9e\u3067\u4fdd\u5b58\u6e08\u307f\u306e"
        "\u8a73\u3057\u3044\u8981\u7d04\u3067\u3059\u3002"
    )
    cache_key = JA_SUMMARY_CACHE_GOOGLE_PREFIX + hashlib.sha1(
        summary.encode("utf-8")
    ).hexdigest()
    payload = {
        "updates_7d": [
            {
                "date": "2026-07-17",
                "title": "Uncached English title",
                "summary": summary,
                "url": "https://example.com/cached-summary",
            }
        ],
        "updates_today": [],
    }

    with patch.dict("os.environ", {}, clear=True), patch(
        "scripts.update_news.translate_to_ja_google"
    ) as google:
        enriched, _, _ = add_waytoagi_japanese_fields(
            payload,
            MagicMock(),
            {},
            {cache_key: summary_ja},
            max_new_translations=0,
        )

    assert enriched["updates_7d"][0]["summary_ja"] == summary_ja
    google.assert_not_called()


def test_coverage_reports_unique_localized_and_missing_fields():
    translated = {
        "title": "English title",
        "title_original": "English title",
        "title_ja": "英語タイトルの日本語訳",
        "summary": "English summary with detail.",
        "summary_ja": "詳細を含む英語要約の日本語訳です。",
    }
    missing = {
        "title": "Missing title",
        "title_original": "Missing title",
        "title_ja": None,
        "summary": "Missing summary with detail.",
        "summary_ja": None,
    }
    coverage = build_japanese_translation_coverage(
        [translated],
        [translated, missing],
        [],
        [],
        {"updates_today": [], "updates_7d": []},
    )

    assert coverage["main_titles"] == {"eligible": 2, "localized": 1, "missing": 1}
    assert coverage["summaries"] == {"eligible": 2, "localized": 1, "missing": 1}
    assert coverage["overall"]["eligible"] == coverage["overall"]["localized"] + coverage["overall"]["missing"]


def test_actions_pass_only_incremental_japanese_limits():
    workflow = (ROOT / ".github/workflows/update-news.yml").read_text(encoding="utf-8")
    for name in (
        "JA_DEEPSEEK_ENABLED",
        "JA_TRANSLATE_MAX_NEW",
        "JA_TRANSLATE_CREATOR_MAX_NEW",
        "JA_SUMMARY_MAX_NEW",
        "JA_WAYTOAGI_MAX_NEW",
    ):
        assert name in workflow
    assert "JA_TRANSLATE_MAX_NEW || 80" in workflow
    assert "TITLE_ENHANCE_JA_MAX_PER_RUN" not in workflow
    assert "REASON_ENHANCE_JA_MAX_PER_RUN" not in workflow
    assert "JA_TRANSLATION_MODE" not in workflow
    assert "MIGRATION" not in workflow
    assert "ja_translation_mode:" not in workflow
    assert "timeout-minutes: 40" in workflow


def test_main_pipeline_uses_only_japanese_limits_for_japanese_work():
    source = (ROOT / "scripts/update_news.py").read_text(encoding="utf-8")
    pipeline = source[source.index("title_ja_cache = load_title_ja_cache"):source.index("stories, merge_events")]
    assert "args.translate_max_new" not in pipeline
    assert 'ja_policy["limits"]["main_titles"]' in pipeline
    assert 'ja_policy["limits"]["creator_titles"]' in pipeline
    assert 'ja_policy["limits"]["summaries"]' in pipeline
    assert 'ja_policy["limits"]["waytoagi_title_or_summary_fields"]' in pipeline
    assert 'ja_policy["coverage"] = build_japanese_translation_coverage' in pipeline

    assert "add_title_enhancements_ja(" not in pipeline
    assert "add_recommend_reasons_ja(" not in pipeline
    assert "TITLE_ENHANCE_JA_MAX_PER_RUN" not in source
    assert "REASON_ENHANCE_JA_MAX_PER_RUN" not in source


def test_both_views_prefer_japanese_summary_and_waytoagi_fields():
    for relative in ("assets/app.js", "classic/assets/app.js"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "item?.summary_ja || item?.summary" in source
        assert "u.title_ja || u.title" in source
        assert "u.summary_ja || u.summary" in source


def test_publication_urls_are_static_and_keep_original_author_separate():
    expected = {
        "index.html": "https://luckyshuusuke-star.github.io/ai-news-radar/",
        "classic/index.html": "https://luckyshuusuke-star.github.io/ai-news-radar/classic/",
    }
    assert not (ROOT / "assets/site-config.js").exists()
    assert not (ROOT / "CNAME").exists()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "https://luckyshuusuke-star.github.io/ai-news-radar/" in readme
    assert "`update-news.yml` 每小时第17分钟自动跑" in readme
    for relative, page_url in expected.items():
        html = (ROOT / relative).read_text(encoding="utf-8")
        assert f'<link rel="canonical" href="{page_url}"' in html
        assert f'<meta property="og:url" content="{page_url}"' in html
        assert "site-config.js" not in html
        assert "data-site-repository" in html
        assert "data-original-repository" in html
        assert "原作者・オリジナル版" in html
        assert "https://github.com/luckyshuusuke-star/ai-news-radar" in html
        assert "https://github.com/LearnPrompt/ai-news-radar" in html
        assert "https://news.learnprompt.pro" not in html
