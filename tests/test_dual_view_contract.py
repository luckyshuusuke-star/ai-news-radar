"""Regression checks for the mobile/classic data and safety contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_FILES = (
    "latest-24h.json",
    "latest-24h-all.json",
    "waytoagi-7d.json",
    "source-status.json",
    "daily-brief.json",
    "stories-merged.json",
)


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_both_views_share_data_source_override_contract():
    for path in ("assets/app.js", "classic/assets/app.js"):
        source = read(path)
        assert 'get("data")' in source
        assert 'localStorage.getItem("dataBaseUrl")' in source
        assert "function dataUrl(path)" in source
        for filename in DATA_FILES:
            assert filename in source


def test_view_router_preserves_data_parameter_between_surfaces():
    source = read("assets/view-mode.js")
    assert 'passthrough.delete("view")' in source
    assert 'passthrough.delete("data")' not in source


def test_both_views_apply_same_last_mile_content_safety_gate():
    for path in ("assets/app.js", "classic/assets/app.js"):
        source = read(path)
        assert "UNSAFE_HARD_PATTERNS" in source
        assert "UNSAFE_PROMO_PATTERNS" in source
        assert "function safeItems(items)" in source
        assert "function isUnsafeStory(story)" in source


def test_both_views_search_japanese_display_titles():
    for path in ("assets/app.js", "classic/assets/app.js"):
        source = read(path)
        assert "item.title_ja" in source
        assert "function itemHaystack(item)" in source

    classic = read("classic/assets/app.js")
    filtered_items = classic[classic.index("function getFilteredItems()"):classic.index("function originalTitleValue")]
    assert "itemHaystack(item)" in filtered_items

    mobile = read("assets/app.js")
    story_query = mobile[mobile.index("function storyMatchesQuery"):mobile.index("function storyMatchesSiteFilter")]
    assert "itemHaystack(ref)" in story_query


def test_both_views_show_non_identical_original_titles_regardless_of_language():
    for path in ("assets/app.js", "classic/assets/app.js"):
        source = read(path)
        original_helper = source[
            source.index("function itemOriginalTitleText"):
            source.index("function itemOriginalTitleText") + 900
        ]
        assert "item?.title_original" in original_helper
        assert "original && original !== display" in original_helper
        assert "isMostlyEnglishTitle" not in original_helper

    for path in ("assets/app.js", "classic/assets/app.js"):
        source = read(path)
        story_original = source[
            source.index("function storyPrimaryOriginalText"):
            source.index("function storySourceCount")
        ]
        assert "primary.title_original" in story_original
        assert "rest.join(\" / \")" in story_original
        assert "isMostlyEnglishTitle" not in story_original

    classic = read("classic/assets/app.js")
    item_renderer = classic[
        classic.index("function renderItemNode"):
        classic.index("const SOURCE_ITEM_INITIAL_LIMIT")
    ]
    assert "itemOriginalTitleText(item)" in item_renderer
    assert 'sub.className = "title-sub"' in item_renderer


def test_both_views_fall_back_to_a_localized_secondary_story_source():
    for path in ("assets/app.js", "classic/assets/app.js"):
        source = read(path)
        localized_helper = source[
            source.index("function storyLocalizedTitleText"):
            source.index("function storyPrimaryTitleText")
        ]
        assert "story?.sources" in localized_helper
        assert "candidate?.title_ja" in localized_helper

        primary_helper = source[
            source.index("function storyPrimaryTitleText"):
            source.index("function storyPrimaryOriginalText")
        ]
        assert "storyLocalizedTitleText(story)" in primary_helper


def test_both_views_keep_tone_support_for_existing_chinese_source_labels():
    for path in ("assets/app.js", "classic/assets/app.js"):
        source = read(path)
        tone_helper = source[
            source.index("function sourceSignalTone"):
            source.index("function sourceSignalTone") + 1000
        ]
        for existing_label in ("官方", "精选", "自媒体", "媒体", "聚合", "日报"):
            assert existing_label in tone_helper


def test_both_pages_expose_bidirectional_view_switch():
    for path in ("index.html", "classic/index.html"):
        source = read(path)
        assert 'data-radar-view-target="mobile"' in source
        assert 'data-radar-view-target="classic"' in source
        assert "assets/view-mode.js" in source


def test_view_switch_follows_update_time_in_both_headers():
    for path in ("index.html", "classic/index.html"):
        source = read(path)
        updated_position = source.index('id="updatedAt"')
        switch_position = source.index('class="view-switch"')
        status_position = source.index('id="sourceStatusPill"')

        assert updated_position < switch_position < status_position
        assert 'class="view-toolbar"' not in source


def test_both_headers_keep_time_and_switch_inside_the_headline():
    for path in ("index.html", "classic/index.html"):
        source = read(path)
        headline_position = source.index('class="hero-headline"')
        updated_position = source.index('id="updatedAt"')
        switch_position = source.index('class="view-switch"')
        meta_position = source.index('class="hero-meta"')

        assert headline_position < updated_position < switch_position < meta_position
        assert 'class="hero-tag"' not in source
        assert ">原作者・オリジナル版</a>" in source
        assert "data-site-repository" in source


def test_classic_header_does_not_animate_the_view_switch_container():
    source = read("classic/assets/motion.js")

    assert 'addFrom(".hero-headline"' not in source
    assert 'addFrom(".hero-meta"' not in source


def test_mobile_is_the_versioned_default_view():
    source = read("assets/view-mode.js")

    assert 'const STORAGE_KEY = "aiNewsRadarViewV2"' in source
    assert 'const LEGACY_STORAGE_KEY = "aiNewsRadarView"' in source
    assert 'const MOBILE_OVERRIDE_KEY = "aiNewsRadarMobileViewOnce"' in source
    assert 'const MOBILE_BREAKPOINT = "(max-width: 760px)"' in source
    assert "const isMobileViewport = window.matchMedia(MOBILE_BREAKPOINT).matches" in source
    assert 'const mobileOverride = isMobileViewport ? readMobileOverride() : ""' in source
    assert "const preference = isMobileViewport" in source
    assert "? mobileOverride" in source
    assert 'const deviceDefault = "mobile"' in source


def test_mobile_classic_choice_is_one_navigation_only():
    source = read("assets/view-mode.js")

    assert "function readMobileOverride()" in source
    assert "window.sessionStorage.removeItem(MOBILE_OVERRIDE_KEY)" in source
    assert "function writeMobileOverride(view)" in source
    assert "writeMobileOverride(view)" in source
