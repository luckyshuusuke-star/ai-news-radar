# Japanese Version Operations

The Japanese layer follows the upstream incremental-cache design. It preserves
the original and Chinese fields, and adds `title_ja` and `summary_ja`.

## Incremental translation limits

Every scheduled or manual generation uses the same bounded profile. Successful
translations are committed under `data/`, so later runs skip cached values and
gradually fill the Japanese layer without a separate migration job.

| Variable | Default | Scope |
|---|---:|---|
| `JA_TRANSLATE_MAX_NEW` | 80 | Main and broad-pool titles, with hot-board titles first |
| `JA_TRANSLATE_CREATOR_MAX_NEW` | 20 | Creator hot-list titles |
| `JA_SUMMARY_MAX_NEW` | 30 | Normal news summaries |
| `JA_WAYTOAGI_MAX_NEW` | 30 | WaytoAGI title or summary fields |

With the defaults, one generation attempts at most 160 new translation fields.
The budget counts unique uncached source values. If the same title or summary is
present in the curated and broad pools, it is attempted once per generation,
including when both providers fail. Failures are not persisted, so a later
scheduled run can retry them.

The generated `latest-24h.json` and `source-status.json` expose limits, maximum
provider-call counts, and current Japanese coverage under
`japanese_translation`.

## DeepSeek safety

Japanese DeepSeek processing is independently controlled by:

```text
JA_DEEPSEEK_ENABLED=0
```

It remains disabled even when `DEEPSEEK_API_KEY` is configured for existing
Chinese translation or persona processing. Set `JA_DEEPSEEK_ENABLED=1`
explicitly to allow Japanese DeepSeek requests. Google remains the fallback,
and the core pipeline runs without API keys.

## Initial cache fill

No special migration mode is required. After deployment, let the normal
scheduled workflow run until `japanese_translation.coverage.overall.missing`
reaches zero. A manual `Update AI News Snapshot` run uses the same limits and
can safely accelerate the initial cache fill without changing the workflow
contract.

## Publication URLs

The public deployment follows the upstream static-page pattern. Canonical and
Open Graph URLs are absolute values in `index.html` and `classic/index.html`:

```text
https://luckyshuusuke-star.github.io/ai-news-radar/
https://luckyshuusuke-star.github.io/ai-news-radar/classic/
```

The Japanese repository link points to:

```text
https://github.com/luckyshuusuke-star/ai-news-radar
```

The original author link remains:

```text
https://github.com/LearnPrompt/ai-news-radar
```

When moving to a custom domain, update the canonical and `og:url` values in both
HTML files directly, matching the upstream deployment style.
