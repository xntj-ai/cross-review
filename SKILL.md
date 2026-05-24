---
name: cross-review
description: >
  多模型交叉审查 v2：R0 Perplexity 联网调研 → 议会 4-7 人辩论 (默认 4 人, --multi-role 可扩到 7 人) →
  Claude Opus 4.7 跨厂商 Judge 双盲综合。输出双层 schema (summary + audit)。
  Use when: 用户要求多模型审查、跨模型讨论、设计决策校验、"拉其他模型一起看"、架构选型。
  v2 关键升级: 每个角色 (除 Pragmatist) 可由 1-2 模型并行扮演, 发现更多互补盲区。
  Pragmatist 由主调用方 (Claude Code with memory) 直接提供视角。
  不适合：纯编码实现、简单事实查询、紧急 hotfix。
---

# /cross-review [topic]

跨厂商 4-reviewer 议会 + R0 联网调研 + Pragmatist 由主调用方注入 + Opus judge 双盲综合。

## v1.1 核心原则

**调研先于判断**：R0 Perplexity 联网搜最新行业实况，议会基于真实信息辩论而非过时训练数据。
**Pragmatist 必须懂用户**：主调用方 (Claude Code) 用 memory + 项目历史直接写视角，比 fresh model 凭 prompt 推断准。
**Judge 用最强模型**：Claude Opus 4.7 综合能力强，且与议会 4 厂商任一家都跨厂商或不同模型（self-bias 小）。
**EmotionPrompt 选择性应用**：GPT/Grok 加 PUA 提升, Claude 反弹故不加, Gemini Promoter 不需要。

## 执行流程

### Step 1: 准备上下文包

`~/AppData/Local/Temp/cross_review_prompt.json`：

```json
{
  "context": "完整上下文（现有系统、方法论、文件示例、调研发现、约束条件）",
  "question": "具体的审查问题（多个问题用编号列出）",
  "pragmatist_view": "（可选）主调用方写的 Pragmatist 视角 (markdown + JSON summary 块结尾)。如未提供则 fallback 到 Sonnet 4.6 API"
}
```

### Step 2: Claude 主调用方应该如何写 pragmatist_view

如果你是 Claude Code 主调用方调这个 skill，你应该：

1. **读取相关 memory** (项目专题 + 历史踩坑 + 团队约束)
2. **基于项目实际情况** 写 Pragmatist 视角:
   - 团队能力/经验/学习曲线
   - 预算/服务器/运维约束
   - 用户群体的实际诉求
   - 历史踩坑（"6 个月前试过 X 失败了"）
3. **末尾附 JSON summary 块**（core_claims/key_evidence/stance/safe_to_stop/blocking_issues）
4. **直接给判断**，不要中立观察

样例参考 `examples/example_with_pragmatist.json`。

### Step 3: 运行脚本

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
| `--profile` | `premium` | `cheap` / `balanced` / `premium` |
| `--rounds` | `2` | 辩论轮次（推荐 2，超过 3 边际收益极低） |
| `--multi-role` | `None` (1:1) | v2 新增. 启用多模型扩展. 选项: `critic` / `troublemaker` / `promoter` / `all` / 逗号分隔. Pragmatist 不可扩展 (memory 唯一) |
| `--with-judge` / `--no-judge` | `--with-judge` | 是否跑独立 judge 综合 |
| `--no-research` | off | 跳过 R0 Perplexity 调研 |
| `--no-early-stop` | off | 关闭结构化早停 |
| `--max-cost` | `5.00` | 美元成本上限 |
| `--output` | temp dir | markdown 报告路径 |
| `--json-output` | 不输出 | judge JSON 路径 |

### v2 Multi-Role 模式 (新增)

每个角色 (除 Pragmatist) 可由 1-2 模型并行扮演, 发现更多互补盲区:

| 命令 | 议会规模 | 适用场景 |
|------|---------|---------|
| (default) | 4 人 (1:1) | 通用决策 |
| `--multi-role critic` | 5 人 (Critic ×2) | 边界情况、failure mode 多视角 |
| `--multi-role troublemaker` | 5 人 (Troublemaker ×2) | 反共识多视角, 找更多盲区 |
| `--multi-role promoter` | 5 人 (Promoter ×2) | 探索多种可行方案 |
| `--multi-role critic,troublemaker` | 6 人 | 找问题双重保险 |
| `--multi-role all` | 7 人 | 全角色多视角, 大型决策 |

实测成本 (balanced profile):
- default 1:1: $0.40-0.80
- multi-role critic: $0.50-1.00
- multi-role all: $0.70-1.30

Pragmatist 不可扩展 — 它由主调用方 memory 提供, 不能复制。

## Profile 对照

| Profile | R0 Research | Promoter | Critic (+PUA) | Troublemaker (+PUA) | Pragmatist | Judge | 成本/次 |
|---------|-------------|----------|---------------|---------------------|------------|-------|---------|
| `cheap` | Perplexity Sonar | Gemini 3 Flash | GPT-5.4 Mini | Grok 4.20 | external 或 Claude Haiku 4.5 | Claude Haiku 4.5 | $0.20-0.40 |
| `balanced` | Perplexity Sonar Pro | Gemini 3.1 Pro | GPT-5.4 | Grok 4.20 | external 或 Claude Sonnet 4.6 | Claude Sonnet 4.6 | $0.40-0.80 |
| `premium` (default) | Perplexity Sonar Pro | Gemini 3.1 Pro | GPT-5.5 | Grok 4.20 Multi-Agent | external 或 Claude Sonnet 4.6 | Claude Opus 4.7 | $1.20-2.50 |

如果 prompt 包含 `pragmatist_view` 字段, Pragmatist 不调 API ($0)。

## Step 4: 读取结果

Judge 输出**双层 JSON**：

**`summary` 字段**（给人看）:
- `consensus_issues[]`: 4/4 一致结论 = 高置信度
- `majority_issues[]`: 3/4 同意（含 dissenter_role）
- `split_issues[]`: 2/4 分裂（含 for/against 列表）
- `key_divergence`: 最关键分歧主题 + judge 推荐
- `final_recommendation`: 3-5 句直接建议

**`audit` 字段**（给机器/审计看）:
- `individual_observations[]`: 单方独有观点（含 merit high/medium/low）
- `ledger[]`: 每条 claim 的 raised_by_role + raised_at_round + stance_evolution 复合对象
- `warnings[]`: sycophancy / drift / meta-sycophancy / performative-compliance

## v1.0 → v1.1 关键升级

| 维度 | v1.0 | v1.1 |
|------|------|------|
| R0 调研 | 无 | **Perplexity Sonar Pro 联网, 输出 augmented context** |
| Pragmatist | Claude Opus 4.7 (议会内) | **主调用方提供 view (无 API 成本)** 或 Sonnet 4.6 fallback |
| Judge | DeepSeek V4 Pro | **Claude Opus 4.7** (最强综合) |
| 议会构成 | 4 reviewer 全 API | 3 reviewer API + 1 Pragmatist external/fallback |

## v1.1 设计驱动力

| 问题 | 解决 |
|------|------|
| 模型靠 training data 判断, 信息可能过时 | R0 Perplexity 联网调研 |
| Fresh model 不知道用户实际处境 | Pragmatist 由 Claude Code 主调用方带 memory 直接写 |
| DeepSeek 当 Pragmatist 不擅长该角色 | 议会移除 DeepSeek, Pragmatist 由 Anthropic Sonnet fallback |
| Judge 应该是最强模型 | Claude Opus 4.7 (与议会 reviewer 任一家都跨厂商或同厂商不同模型) |

## 学界依据 (2025-2026)

| 论文 | 影响 |
|------|------|
| Peacemaker (arxiv 2509.23055) | 4 reviewer 而非 2，抗 sycophancy |
| Free-MAD (arxiv 2509.11035) | structured summary 聚合 |
| DRIFTJudge (arxiv 2502.19559) | 早停 + 限 rounds≤3 |
| Self-Preference Bias (arxiv 2410.21819) | 议会移除 Anthropic 后 Opus 可当 judge |
| EmotionPrompt (arxiv 2307.11760) | GPT/Grok 加 PUA, Claude 不加 |
| v3 meta-test 自审 (2026-05-24) | 5 个根本修复 |
| 知乎 11 模型 PUA 实测 | Sonnet 4 无 thinking 反弹, Opus 4 + thinking 吃 |

## 注意事项

- **GPT 偶尔不附 JSON summary** → fallback extractor 自动补提取 (~$0.02)
- **None content 防御** → OpenRouter 偶发空 content 不崩主流程
- **External pragmatist 不参与 R2 演化** → R1 view 作为 anchor, R2 复用 (Pragmatist 立场来自 memory, 不需要 fresh model 推断的演化)
- **Windows 路径**: 用 `~/AppData/Local/Temp/`
- **不要用于事实验证**: LLM 集体可能错
