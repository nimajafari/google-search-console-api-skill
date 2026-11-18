# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project overview

A single [Agent Skill](https://agentskills.io/specification) that teaches an agent to use the
[Google Search Console API](https://developers.google.com/webmaster-tools/about) (Search Analytics,
URL Inspection, Sitemaps, Sites) correctly and within quota.

## Structure

```
google-search-console-api-skill/
├── README.md
├── LICENSE
├── .claude-plugin/            # Claude Code plugin + marketplace manifests
├── .antigravity-plugin/       # Antigravity plugin manifest
├── .cursor-plugin/            # Cursor plugin manifest
├── codex/, .agents/plugins/   # Codex plugin + marketplace (codex/skills → ../skills)
├── gemini-extension.json      # Gemini CLI extension manifest
└── skills/
    └── google-search-console-api/
        ├── SKILL.md           # main instructions (keep under 500 lines)
        ├── scripts/
        │   └── gsc.py         # stdlib-only CLI (Python 3.9+)
        └── references/
            ├── LIMITS.md
            ├── SEARCH-ANALYTICS.md
            ├── URL-INSPECTION.md
            ├── SITES-AND-SITEMAPS.md
            ├── AUTH-AND-SETUP.md
            ├── ERRORS.md
            └── BATCH-AND-PERFORMANCE.md
```

## Conventions

- **SKILL.md** stays under 500 lines. Look-up material goes in `references/`.
- **Descriptions** carry trigger phrases so the skill activates on the right prompts.
- **Every number** (quotas, row limits, dates) must trace to a Google doc listed in SKILL.md's
  Sources. Keep the quota tables in LIMITS.md and SKILL.md in sync.
- **gsc.py**: standard library only (optional `google-auth`), Python 3.9-compatible syntax (no
  `match`, no `X | Y` at runtime), data to stdout, logs to stderr, writes require `--yes`, never
  print tokens.
- Bump the version in all manifests (`.claude-plugin/plugin.json`, `.antigravity-plugin/`,
  `.cursor-plugin/`, `codex/.codex-plugin/`, `gemini-extension.json`), SKILL.md `metadata.version`
  and `gsc.py __version__` together.

## Accuracy notes

- Google updates the limits page and adds Search Analytics fields (e.g. `brandedClassification`,
  `webMultimodal`, `filterLists`) without a version bump. Re-check
  https://developers.google.com/webmaster-tools/limits and the
  [`searchconsole` v1 discovery doc](https://searchconsole.googleapis.com/$discovery/rest?version=v1)
  when editing.
- `urlTestingTools.mobileFriendlyTest` is still in the discovery doc but the Mobile-Friendly Test
  was retired in December 2023. Don't add it back.

## Testing changes

1. Validate the YAML frontmatter in `SKILL.md`.
2. `python3 -m py_compile skills/google-search-console-api/scripts/gsc.py` and `pyflakes`.
3. `--dry-run` every subcommand to check request shapes without credentials.
4. Against a mock server: set `GSC_API_ROOT=http://127.0.0.1:PORT` and `GSC_ACCESS_TOKEN=...`.
   Exercise paging (> 25k rows), 429/403 rate-limit retry, `quotaExceeded` stop (exit 3), gzip,
   and the inspect ledger (`--ledger` to a temp path).
5. With real credentials: `gsc.py sites`, `gsc.py freshness <site>`, a one-day `query`.
