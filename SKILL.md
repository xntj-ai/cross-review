---
name: cross-review
description: >
  多模型交叉审查 v1.0：通过 OpenRouter 调 4 个跨厂商模型 (Gemini Promoter + GPT Critic + Grok Troublemaker + Claude Pragmatist)
  做角色化对照审查，R2 真匿名化 (仅传 structured summary)，跑 1-2 轮辩论 + DeepSeek 跨厂商 judge 综合，
  输出双层 schema (summary 给人看 + audit 给机器看)。
  Use when: 用户要求多模型审查、跨模型讨论、设计决策校验、"拉其他模型一起看"、架构选型。
  适合架构决策、方案选型、设计审查等需要多视角 + 反附和判断的场景。
  不适合：纯编码实现、简单事实查询、紧急 hotfix。
---

# /cross-review [topic]

跨厂商 4-reviewer 议会 + 真匿名化 + DeepSeek 跨厂商 judge。详见 README 学界依据。

## v1.0 核心原则

**异质性 > 辩论本身**：4 个跨厂商模型（Google/OpenAI/xAI/Anthropic）+ 跨厂商 judge（DeepSeek）。
**真匿名化 > 仅替换品牌名**：R2 仅传 structured summary JSON（剥离风格 + 品牌 + 角色标签），不传原始 markdown。
**结构化早停 > 关键词匹配**：R1 强制输出 safe_to_stop + blocking_issues，全员 true && 0 blocking → 跳 R2。
**EmotionPrompt 仅对 GPT/Grok**：Claude 实测会反弹，故 Claude 模型不加 PUA-style prompt。

## 执行流程

### Step 1: 准备上下文包

`~/AppData/Local/Temp/cross_review_prompt.json`：

```json
{
  "context": "完整上下文（现有系统、方法论、文件示例、调研发现、约束条件）",
  "question": "具体的审查问题（多个问题用编号列出）"
}
```

### Step 2: 运行脚本

```bash
python ~/.claude/skills/cross-review/scripts/cross_review.py \
  ~/AppData/Local/Temp/cross_review_prompt.json \
  --profile premium \
  --rounds 2 \
  --with-judge \
  --output ~/AppData/Local/Temp/cross_review_result.md \
  --json-output ~/AppData/Local/Temp/cross_review_result.json
```

### 参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--profile` | `premium` | `cheap` / `balanced` / `premium`，决定 4 reviewer + judge 组合 |
| `--rounds` | `2` | 辩论轮次（推荐 2，超过 3 边际收益极低） |
| `--with-judge` / `--no-judge` | `--with-judge` | 是否跑 DeepSeek 独立 judge 综合 |
| `--no-early-stop` | off | 关闭结构化早停 |
| `--max-cost` | `5.00` | 美元成本上限 |
| `--output` | temp dir | markdown 报告路径 |
| `--json-output` | 不输出 | judge JSON 路径 |

## Profile 对照

| Profile | Promoter | Critic (PUA) | Troublemaker (PUA) | Pragmatist | Judge (跨厂商) | 单次成本 |
|---------|----------|--------------|---------------------|------------|----------------|---------|
| `cheap` | Gemini 3 Flash | GPT-5.4 Mini | Grok 4.20 | Claude Haiku 4.5 | DeepSeek V4 Flash | $0.20-0.40 |
| `balanced` | Gemini 3.1 Pro | GPT-5.4 | Grok 4.20 | Claude Sonnet 4.6 | DeepSeek V4 Pro | $0.40-0.80 |
| `premium` (default) | Gemini 3.1 Pro | GPT-5.5 | Grok 4.20 Multi-Agent | Claude Opus 4.7 | DeepSeek V4 Pro | $2.00-3.50 |

## Step 3: 读取结果

`--with-judge` 时，judge 输出**双层 JSON**：

**`summary` 字段**（给人看）:
- `consensus_issues[]`: 4/4 一致结论 = 高置信度
- `majority_issues[]`: 3/4 同意（含 dissenter_role）
- `split_issues[]`: 2/4 分裂（含 for/against 列表）
- `key_divergence`: 最关键分歧主题 + judge 推荐
- `final_recommendation`: 3-5 句直接建议

**`audit` 字段**（给机器/审计看）:
- `individual_observations[]`: 单方独有观点（含 merit high/medium/low）
- `ledger[]`: 每条 claim 的归因 + stance_evolution 复合对象
- `warnings[]`: sycophancy / drift / meta-sycophancy / performative-compliance

`--no-judge` 时回退 v3 流程：Claude 读 markdown 自己分类。

## v1.0 关键设计决策

### 4 reviewer 而非 3
v3 缺 Anthropic 视角。Claude Pragmatist 代表"实用主义/利益相关方"，弥补 promoter 理想化 + critic/troublemaker 极端化的偏。Peacemaker 论文证 3 是甜区下限，4 仍在合理范围。

### Pragmatist 不加 EmotionPrompt
[知乎 11 模型 PUA 实测](https://zhuanlan.zhihu.com/p/1921794165055923016) 显示 Sonnet 4 无 thinking 会反弹 ("我不会因压力改变工作方法")，Opus 4 + thinking 反吃这套。统一不加是稳妥选择。

### DeepSeek 跨厂商 judge
v3 用 Gemini judge 综合 Gemini Promoter 输出 = 同厂商有偏 (v3 meta-test 自审一致指出)。v1.0 用 DeepSeek 跨四方任意一家厂商，消除 self-preference bias。

### R2 真匿名化
v3 仅替换品牌名 → 模型可从 role 标签 + 风格反推身份。v1.0 仅传 structured summary（core_claims + key_evidence + stance + blocking_issues），不传原始 markdown，从源头消除风格指纹。

### 结构化早停
v3 关键词匹配 ("无重大问题") 易被礼貌语 / 反讽绕过。v1.0 强制 R1 输出 `safe_to_stop: bool + blocking_issues: list`，4/4 都 true && 0 blocking → 跳 R2。

### 双层 schema
v3 7 字段单 JSON 信息过载。v1.0 拆 `summary` (人类阅读 ≤2500字) + `audit` (机器审计 ≤6000字)，按使用场景分离。

## 学界依据 (2025-2026)

| 论文 | 影响 v1.0 哪部分设计 |
|------|----------------------|
| Peacemaker (arxiv 2509.23055) | 4 reviewer 而非 2，抗 sycophancy |
| Free-MAD (arxiv 2509.11035) | 结构化 summary 聚合替代自由辩论 |
| DRIFTJudge (arxiv 2502.19559) | 早停 + 限制 rounds≤3 |
| Self-Preference Bias (arxiv 2410.21819) | DeepSeek 跨厂商 judge (而非任一 reviewer 同厂商) |
| EmotionPrompt (arxiv 2307.11760) | GPT/Grok 用 PUA prompt 提升性能 (Claude 实测反弹故不用) |
| Diversity of Thought (arxiv 2410.12853) | 4 厂商 vs 3 厂商，更大覆盖训练分布 |
| v3 meta-test 自审 (2026-05-24) | 真匿名化 + 结构化早停 + 双盲 judge + schema 拆分 |

## v0 → v1 → v2 → v3 → v1.0 演进

| 维度 | v1 (2026-02) | v2 (2026-05) | v3 (2026-05) | **v1.0** (2026-05-24) |
|------|--------------|--------------|--------------|------------------------|
| Reviewer 数 | 2 | 3 | 3 | **4** |
| 角色 | 同质 | promoter/critic/troublemaker | 同 v2 | **+ pragmatist** |
| 综合者 | Claude 自评 | Gemini judge | 同 v2 | **DeepSeek 跨厂商** |
| R2 匿名化 | 无 | 无 | 仅品牌名 | **真匿名化 (仅传 summary JSON)** |
| 早停 | 无 | 无 | 关键词匹配 | **结构化 (safe_to_stop + blocking_issues)** |
| Schema | markdown | 单 JSON 5 字段 | 单 JSON 7 字段 | **双层 (summary + audit)** |
| stance_evolution | — | — | enum string | **复合对象 (type + evidence + trigger)** |
| EmotionPrompt | 无 | 无 | 无 | **GPT/Grok 用, Claude 不用** |

## 注意事项

- **Windows 路径**：用 `~/AppData/Local/Temp/`
- **编码**：脚本已处理 UTF-8
- **GPT 协议遵守**：v1.0 用三重 prompt 提醒强制 summary 输出，仍有少数情况 GPT 不附 JSON → judge 仍可从 markdown 推断，graceful degradation
- **不要用于事实验证**：LLM 集体可能错
- **失败模式**：若某 reviewer API 错误，其他继续，judge 仍可综合（缺失方在 ledger 标 null）
