# cross-review

> A Claude Code skill for multi-model deliberative design review.
> 多模型辩论式设计审查 — Gemini & GPT 看到彼此的观点后再做判断。

## What it does

Most "ask multiple models" implementations are **monologues** — you query each model independently and play judge yourself. They never see each other's blind spots.

`cross-review` is a **debate**:

- **Round 1** — Gemini 3.1 Pro and GPT-5.2 each review your context independently
- **Round 2** — Each model sees the other's full critique, then must explicitly agree / disagree / supplement, paying special attention to blind spots the other raised
- **Synthesis** — Claude (the main model) extracts: shared consensus / disagreements / unique points

The result is a structured report you can act on.

## When to use

| Scenario | Fit |
|---|---|
| Architecture decisions, technology selection | ✓ Recommended |
| Comparing 2–3 candidate solutions | ✓ Recommended |
| Design / UX / API review | ✓ Recommended |
| Writing implementation code | ✗ Just let Claude write it |
| Fact verification | ✗ LLMs can be collectively wrong |
| Emergency hotfix | ✗ Takes 2–3 minutes; just fix it |

## Install

### Prerequisites

- Claude Code installed
- Python 3.10+
- An OpenRouter API key — sign up at [openrouter.ai](https://openrouter.ai), pay-per-token

### Steps

```bash
# 1. Clone into your Claude Code skills directory
# macOS / Linux
cd ~/.claude/skills
git clone https://github.com/xntj-ai/cross-review.git

# Windows (PowerShell)
cd $env:USERPROFILE\.claude\skills
git clone https://github.com/xntj-ai/cross-review.git
```

```bash
# 2. Set your OpenRouter key (pick one)

# Option A — environment variable (recommended)
export OPENROUTER_API_KEY="sk-or-..."

# Option B — add to ~/.claude/settings.local.json under mcpServers.*.env
```

```bash
# 3. (Optional) Configure proxy if you're behind a regional restriction
# Default is http://127.0.0.1:10808
export OPENROUTER_PROXY="http://127.0.0.1:7890"
```

```bash
# 4. Restart Claude Code. The skill will appear in /<slash> menu as `cross-review`.
```

## Usage

### A. Via Claude Code (natural language)

Just talk to Claude:

```
"用 cross-review 审一下这个架构方案"
"Run cross-review on whether to use Redis incr vs Postgres advisory lock for the counter"
"Pull Gemini and GPT in on this UI design"
```

Claude will prepare the context bundle and invoke the script.

### B. Standalone (no Claude)

```bash
# Prepare a prompt JSON
cat > /tmp/review.json <<'EOF'
{
  "context": "Existing system: X. Constraints: Y. Real file excerpts: ...",
  "question": "1. Cost boundary of plan A vs B?  2. Blind spots I might have missed?"
}
EOF

# Run
python ~/.claude/skills/cross-review/scripts/cross_review.py \
  /tmp/review.json \
  --rounds 2 \
  --output /tmp/result.md
```

Flags:

- `--rounds N` — debate rounds (default 2; 3+ has diminishing returns)
- `--output <path>` — output markdown file
- `--models <id1> <id2> ...` — override model selection

## Cost & limits

| | |
|---|---|
| Typical 2-round review | **$0.10 – $0.20** (varies by context length) |
| Time per round | 60 – 90 seconds (parallel API calls) |
| Rounds | 2 is the sweet spot; 3+ → models start parroting |
| Budget mode | `--models google/gemini-3-flash openai/gpt-5-mini` |

## What it gives you (output shape)

```markdown
# Cross-Review Report
**Models**: Gemini 3.1 Pro, GPT-5.2
**Rounds**: 2

## Round 1
### Gemini 3.1 Pro ($0.04)
[independent review]

### GPT-5.2 ($0.05)
[independent review]

## Round 2
### Gemini 3.1 Pro ($0.05)
[response: agrees / disagrees / supplements re GPT's points]

### GPT-5.2 ($0.05)
[response: agrees / disagrees / supplements re Gemini's points]

## 成本汇总
**Total**: $0.19
```

Claude then reads this and synthesizes into a final consensus/disagreement table.

## Customize

Edit `scripts/cross_review.py`:

- `DEFAULT_MODELS` — swap in your preferred model combo
- `build_system_prompt()` — adjust the reviewer persona
- `MAX_TOKENS` / `TEMPERATURE` — tune verbosity and creativity

## License

MIT — see `LICENSE`.

## Author

Created by **张拼拼 (Max Pin)** · [zpplife@gmail.com](mailto:zpplife@gmail.com)

If you find this useful, a star on the repo is appreciated. Issues and PRs welcome.
