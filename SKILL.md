---
name: cross-review
description: >
  多模型交叉审查 v2：通过 OpenRouter 调三个跨厂商模型 (Gemini Promoter + GPT Critic + Grok Troublemaker)
  做角色化对照审查，2 轮辩论 + 独立 judge 综合，输出结构化 consensus/divergences/unique_points JSON。
  Use when: 用户要求多模型审查、跨模型讨论、设计决策校验、"拉其他模型一起看"、架构选型。
  适合架构决策、方案选型、设计审查等需要不同视角和反附和判断的场景。
  不适合：纯编码实现、简单事实查询、紧急 hotfix。
---

# /cross-review [topic]

跨厂商对照审查 + 反附和设计 + 独立 judge。理论依据 2025-2026 学界共识（详见 README）。

## 核心原则

**异质性 > 辩论本身**：v2 的真正护城河是跨厂商模型（Gemini/GPT/Grok）的训练分布差异，而非"轮次"。
**反附和 > 共识**：v2 用角色分工 + 显式 anti-sycophancy prompt 对抗 2-agent sycophancy collapse（Peacemaker 论文实证）。
**独立 judge > 自评**：v2 用 Gemini 独立综合，消除主模型 Claude 的 self-preference bias（arxiv 2410.21819）。

## 执行流程

### Step 1: 准备上下文包

创建 JSON 文件 `~/AppData/Local/Temp/cross_review_prompt.json`：

```json
{
  "context": "完整上下文（现有系统、方法论、文件示例、调研发现、约束条件）",
  "question": "具体的审查问题（多个问题用编号列出）"
}
```

**上下文必须包含**（PoC 教训：缺上下文导致审查浮于表面）：

1. 现有系统/方法论（审查者需要知道什么已经在用）
2. 真实文件示例（不是抽象描述，是实际内容片段）
3. 行业调研发现（给审查者参照系，避免从零开始）
4. 约束条件（技术限制 + 用户偏好 + 运行环境）
5. 前轮审查共识（如果有，避免重复讨论已解决的问题）

### Step 2: 获取 OpenRouter API Key

查找顺序（脚本自动）：

1. 环境变量 `OPENROUTER_API_KEY`
2. `~/.claude/settings.local.json` 的 `credentials.{service}` 任意字段含 `OPENROUTER`
3. `~/.claude/settings.local.json` 的 `mcpServers.*.env` 任意字段含 `OPENROUTER`

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
| `--profile` | `premium` | `cheap` / `balanced` / `premium`，决定 3 模型组合 |
| `--rounds` | `2` | 辩论轮次（推荐 2，超过 3 边际收益极低且易 drift） |
| `--with-judge` / `--no-judge` | `--with-judge` | 是否跑独立 Gemini judge 综合 |
| `--no-early-stop` | off | 关闭 R1 共识早停（默认 R1 三方一致跳过 R2） |
| `--max-cost` | `3.00` | 美元成本上限，超过中断 |
| `--output` | temp dir | markdown 报告路径 |
| `--json-output` | 不输出 | judge JSON 路径（仅 with-judge 时） |
| `--models` | profile | 手动指定 3 个模型 ID（promoter/critic/troublemaker 顺序） |

## Profile 对照

| Profile | Promoter | Critic | Troublemaker | 单次成本 |
|---------|----------|--------|--------------|---------|
| `cheap` | gemini-3-flash | gpt-5.4-mini | grok-4.20 | $0.15-0.25 |
| `balanced` | gemini-3.1-pro | gpt-5.4 | grok-4.20 | $0.40-0.60 |
| `premium` (default) | gemini-3.1-pro | gpt-5.5 | grok-4.20-multi-agent | $1.20-1.80 |

`premium` 加 judge round 约 +$0.30-0.50。

## Step 4: 读取结果并综合

`--with-judge` 时，judge 已输出结构化 JSON。主调用方（Claude）只需读 JSON 字段：

- `consensus[]`：三方一致结论 = 高置信度决策
- `divergences[]`：分歧主题，含每方立场 + judge 推荐
- `unique_points[]`：单方独有观点 + merit 评级（high 重点关注）
- `warnings[]`：sycophancy / drift / 噪声警示
- `final_recommendation`：综合建议（2-4 句）

`--no-judge` 时，回退到 v1 流程：Claude 读 markdown 自己分类。

## 何时降级 `--no-judge`

- 上下文非常简单，judge 综合不增值
- 成本极度敏感
- 已经知道答案，只是想要多视角佐证

## 何时升级 `--profile premium`

- 重大架构决策（成本 < 决策错误代价）
- 需要 GPT-5.5 的最强推理 + Grok multi-agent 反共识力度
- 上下文复杂或问题多，需要顶级模型避免遗漏

## 学界依据 (2025-2026)

| 论文 | 影响 v2 哪部分设计 |
|------|-------------------|
| Peacemaker (arxiv 2509.23055) | 3 模型 default 而非 2（2-agent 易 sycophancy collapse） |
| Free-MAD (arxiv 2509.11035) | anti-sycophancy prompt + 反附和检测 |
| DRIFTJudge (arxiv 2502.19559) | R1 早停 + 限制 rounds<=3 |
| Self-Preference Bias (arxiv 2410.21819) | 独立 judge（用 Gemini 而非主模型 Claude） |
| Diversity of Thought (arxiv 2410.12853) | 跨厂商 default 而非单厂商多模型 |

## 注意事项

- **Windows 路径**：用 `~/AppData/Local/Temp/` 而非 `/tmp/`
- **编码**：脚本已处理 UTF-8
- **不要用于事实验证**：LLM 一致性不等于事实准确性
- **不要超过 3 轮**：DRIFTJudge 论文显示 35% 会原地踏步
- **失败模式**：若某模型 API 错误，其他模型继续，judge 仍可综合（缺失方标 null）
