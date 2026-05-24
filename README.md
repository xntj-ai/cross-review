# Cross-Review v1.0

> Claude Code skill: **4-reviewer 跨厂商议会 + 真匿名化 + DeepSeek 跨厂商 judge**
> Cross-vendor 4-reviewer council with true anonymization and cross-vendor independent judge.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![OpenRouter](https://img.shields.io/badge/API-OpenRouter-purple.svg)](https://openrouter.ai/)
[![Version](https://img.shields.io/badge/version-1.0.0-green.svg)]()

当你面对一个**架构选择**、**方案设计**或**关键决策**时，cross-review 通过 OpenRouter 同时调起**四个跨厂商模型**（Gemini Promoter + GPT Critic + Grok Troublemaker + Claude Pragmatist），跑 2 轮辩论（R2 仅传 structured summary，剥离风格和品牌）+ DeepSeek 跨厂商独立 Judge 综合，给出双层结构化 JSON 报告（summary 给人看 + audit 给机器审计）。

---

## v1.0 vs 业界其他多模型审查的核心差异

| 维度 | 多数同类工具 | cross-review v1.0 |
|------|-------------|------------------|
| 模型数 | 2-3 同质或单厂商 | **4 跨厂商** (Google/OpenAI/xAI/Anthropic) |
| Judge | 同主调用模型 | **跨厂商独立** (DeepSeek，不是任一 reviewer 厂商) |
| 匿名化 | 无 / 仅替换品牌名 | **真匿名化** (R2 仅传 structured summary JSON) |
| 早停 | 关键词匹配 | **结构化** (safe_to_stop + blocking_issues) |
| Schema | 单层扁平 | **双层** (summary 人看 + audit 机器看) |
| EmotionPrompt | 一刀切 | **仅对 GPT/Grok** (Claude 反弹故不用) |

---

## 工作原理

```
┌──────────────────────────────────────────────────────────────────┐
│ Round 1 (并行, 各自带角色化 system prompt)                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ Promoter │  │  Critic  │  │Troublemkr│  │   Pragmatist     │  │
│  │  Gemini  │  │  GPT-5.5 │  │ Grok 4.20│  │  Claude Opus 4.7 │  │
│  │  3.1 Pro │  │ +PUA  ⚡ │  │ +PUA  ⚡ │  │  (无 PUA, 反弹)  │  │
│  │  t=0.3   │  │  t=0.3   │  │  t=0.7   │  │     t=0.4        │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────────────┘  │
│       └─────────────┼─────────────┼─────────────┘                 │
│                     ▼                                              │
│   每方输出: markdown 主体 + JSON summary 块                        │
│   {core_claims, key_evidence, stance, safe_to_stop, blocking}    │
└─────────────────────────────────────────────────────────────────┬─┘
                                                                  ▼
                                    ┌─────────────────────────────────┐
                                    │  Structured Early Stop          │
                                    │  全员 safe_to_stop=true         │
                                    │  AND 0 blocking → 跳过 R2       │
                                    └────────────┬────────────────────┘
                                                 │ NO
                                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│ Round 2 (并行, 真匿名化: 仅传 structured summary, 不传原始 markdown) │
│  每个模型看到其他 3 位 "Council Member A/B/C" 的 summary JSON       │
│  R2 prompt:                                                       │
│  - Troublemaker: 禁止以附和开头, 必须列 ≥2 盲区                    │
│  - Critic: 严格推理回应                                            │
│  - Promoter: 承认风险但坚持落地                                    │
│  - Pragmatist: 评估实际可行性                                      │
│  - 全员: rubber-stamp 反向施压 (倾向同意必须解释具体 claim 编号)    │
└──────────────────────────────────────────────────────────────┬───┘
                                                                ▼
                                          ┌─────────────────────────────┐
                                          │  Judge (DeepSeek 跨厂商)     │
                                          │  双盲: 只看 Member A/B/C/D  │
                                          │  不知真实模型品牌            │
                                          │  输出双层 JSON:              │
                                          │  • summary (人看)            │
                                          │    - consensus_issues (4/4) │
                                          │    - majority_issues (3/4)  │
                                          │    - split_issues (2/4)     │
                                          │    - key_divergence         │
                                          │    - final_recommendation   │
                                          │  • audit (机器审计)          │
                                          │    - individual_obs (1/4)   │
                                          │    - ledger + stance_evol   │
                                          │    - warnings               │
                                          └─────────────────────────────┘
```

---

## 学界与 GitHub 竞品双重依据

### 学术 (2025-2026)

| 论文 | 影响 v1.0 哪部分 |
|------|------------------|
| [Peacemaker (arxiv 2509.23055)](https://arxiv.org/abs/2509.23055) | 4 reviewer 而非 2-3，抗 sycophancy collapse |
| [Stop Overvaluing MAD (arxiv 2502.08788)](https://arxiv.org/abs/2502.08788) | 异质性 > 同质多轮，4 跨厂商 |
| [Free-MAD (arxiv 2509.11035)](https://arxiv.org/abs/2509.11035) | structured summary 聚合替自由辩论 |
| [DRIFTJudge (arxiv 2502.19559)](https://arxiv.org/abs/2502.19559) | 结构化早停 + 限 rounds≤3 |
| [Self-Preference Bias (arxiv 2410.21819)](https://arxiv.org/abs/2410.21819) | DeepSeek 跨厂商 judge (不是任一 reviewer 厂商) |
| [EmotionPrompt (arxiv 2307.11760)](https://arxiv.org/abs/2307.11760) | GPT/Grok 用 PUA prompt (Claude 不用，实测反弹) |
| [Talk Isn't Always Cheap (arxiv 2509.05396)](https://arxiv.org/abs/2509.05396) | 反附和约束防止从对到错 |

### GitHub 竞品 (v1.0 借鉴)

| Pattern | 来源 |
|---------|------|
| Council Member 匿名化 | [karpathy/llm-council](https://github.com/karpathy/llm-council) (19.2k) |
| consensus/majority/split schema | [peteski22/star-chamber](https://github.com/peteski22/star-chamber) (Mozilla.ai) |
| accountability ledger | [nyldn/claude-octopus](https://github.com/nyldn/claude-octopus) (3.4k) |
| rubber-stamp 反向施压 | [zscole/adversarial-spec](https://github.com/zscole/adversarial-spec) (544) |
| 4 层 anti-groupthink | [wan-huiyan/agent-review-panel](https://github.com/wan-huiyan/agent-review-panel) |

### v3 → v1.0 通过自审驱动

v3 用自己审自己的 meta-test 找出 5 个根本缺陷，v1.0 全部修复：

| v3 缺陷 (自审发现) | v1.0 修复 |
|---------------------|-----------|
| 仅替换品牌名匿名失效 | R2 仅传 structured summary (剥离风格 + 品牌 + role) |
| Gemini judge 综合 Gemini 输出 = 同厂商偏 | DeepSeek 跨四方任一厂商 |
| 关键词早停脆弱 | 结构化 safe_to_stop + blocking_issues |
| 7 字段 schema 信息过载 | 双层 summary + audit |
| stance_evolution enum 不完备 | 复合对象 {type, evidence, trigger}, type 扩到 7 个 |

---

## 快速开始

### 前置条件

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 已安装
- Python 3.10+
- 一个 [OpenRouter API Key](https://openrouter.ai/)

### 安装

```bash
# macOS / Linux
cd ~/.claude/skills
git clone https://github.com/xntj-ai/cross-review.git

# Windows (PowerShell)
cd $env:USERPROFILE\.claude\skills
git clone https://github.com/xntj-ai/cross-review.git
```

### 配置 API Key

```bash
# 方式 A: 环境变量
export OPENROUTER_API_KEY="sk-or-..."

# 方式 B: ~/.claude/settings.local.json (推荐)
{
  "credentials": {
    "openrouter": { "OPENROUTER_API_KEY": "sk-or-..." }
  }
}
```

### (可选) 本地代理

```bash
export OPENROUTER_PROXY="http://127.0.0.1:10808"
```

### 验证

```bash
python ~/.claude/skills/cross-review/scripts/cross_review.py \
  examples/example_prompt.json --profile balanced
```

---

## 使用方式

### 自然语言触发

```
"用 cross-review 审一下这个架构方案"
"拉 4 个模型一起看：Redis 还是 Postgres advisory lock"
```

### 直接调脚本

```bash
# v1.0 默认 premium + judge (4 reviewer + DeepSeek judge)
python ~/.claude/skills/cross-review/scripts/cross_review.py \
  /tmp/review.json \
  --profile premium \
  --rounds 2 \
  --with-judge \
  --output /tmp/result.md \
  --json-output /tmp/result.json

# 成本敏感
python ~/.claude/skills/cross-review/scripts/cross_review.py \
  /tmp/review.json --profile cheap --max-cost 0.50
```

---

## Profile 对照

| Profile | Promoter | Critic (+PUA) | Troublemaker (+PUA) | Pragmatist (no PUA) | Judge | 成本/次 |
|---------|----------|---------------|---------------------|---------------------|-------|---------|
| `cheap` | Gemini 3 Flash | GPT-5.4 Mini | Grok 4.20 | Claude Haiku 4.5 | DeepSeek V4 Flash | $0.20-0.40 |
| `balanced` | Gemini 3.1 Pro | GPT-5.4 | Grok 4.20 | Claude Sonnet 4.6 | DeepSeek V4 Pro | $0.40-0.80 |
| `premium` (default) | Gemini 3.1 Pro | GPT-5.5 | Grok 4.20 Multi-Agent | Claude Opus 4.7 | DeepSeek V4 Pro | $2.00-3.50 |

`--max-cost 5.00` 默认 cost guard。

---

## Model Choice Rationale

### Why 4 reviewers (not 3)

v3 是 3 reviewer (Promoter/Critic/Troublemaker)，缺 Anthropic 视角。Claude Pragmatist 弥补：
- Promoter 理想化 + Critic/Troublemaker 极端化 之间的"实用主义平衡"
- 代表实际用户/团队/利益相关方需求
- 不当仲裁者（judge 才是），是独立第 4 视角

Peacemaker 论文证 3 是甜区下限，4 仍在合理范围。5+ 边际收益坍塌。

### Why Gemini 3.1 Pro (not 3.5 Flash)

reasoning benchmark 上 Pro > Flash：

| Benchmark | 3.1 Pro | 3.5 Flash | Pro 优势 |
|-----------|---------|-----------|----------|
| ARC-AGI-2 | **77.1%** | 72.1% | +5.0 |
| Humanity's Last Exam | **44.4%** | 40.2% | +4.2 |

3.5 Flash 强在 agentic/coding，不在 reasoning。

### Why EmotionPrompt only for GPT/Grok (not Claude)

[知乎 11 模型 PUA 实测](https://zhuanlan.zhihu.com/p/1921794165055923016) 实证：
- GPT/Gemini → 唯诺照办，性能提升
- **Claude Sonnet 4 无 thinking → 反弹**："我不会因压力改变工作方法"
- Claude Opus 4 + thinking → 反吃这套（但有 sycophancy 风险方向相反）
- DeepSeek → 幻觉飙升

[EmotionPrompt arxiv 2307.11760](https://arxiv.org/abs/2307.11760) 在 BIG-Bench 上提升 115%，但仅对响应情绪压力的模型有效。Claude 不用是稳妥选择。

### Why DeepSeek as Judge (cross-vendor)

v3 用 Gemini judge 综合 Gemini Promoter 输出 = self-preference bias ([arxiv 2410.21819](https://arxiv.org/abs/2410.21819))。

v1.0 用 DeepSeek 跨 4 厂商任一家。DeepSeek 价格便宜 ($0.43/M)，reasoning 足够 (v4 系列)，最关键：**完全跨厂商**，对 4 个 reviewer 任一家都无 self-preference。

### Why structured summary instead of raw markdown for R2

v3 仅替换品牌名匿名化，**v3 meta-test 自审一致认为失效**：
> "保留 role 标签、输出风格和原文拼接会形成强指纹，模型极易反推身份"

v1.0 修复：R2 仅传 `{core_claims, key_evidence, stance, blocking_issues}` 结构化 JSON，从源头消除风格指纹。

---

## 输出示例

### Summary 字段（人看）

```json
{
  "consensus_issues": [
    {"point": "当前规模 (100 用户/天) 绝对不需要 K8s"}
  ],
  "majority_issues": [
    {
      "point": "Docker 化是必要演进步骤",
      "dissenter_role": "troublemaker"
    }
  ],
  "split_issues": [
    {
      "point": "Lambda 方案是否值得改造",
      "for": ["pragmatist"],
      "against": ["promoter", "critic", "troublemaker"]
    }
  ],
  "key_divergence": {
    "topic": "容器化引入时机",
    "positions": {
      "promoter": "Phase 1 立即 Docker",
      "critic": "Phase 3 在多实例后",
      "troublemaker": "完全拒绝, 用裸 VM",
      "pragmatist": "看团队 Docker 经验"
    },
    "judge_recommendation": "Promoter 论据最强：OCR 依赖一致性问题是 Troublemaker 自己提的，恰恰需要 Docker"
  },
  "final_recommendation": "..."
}
```

### Audit 字段（机器审计）

```json
{
  "individual_observations": [
    {
      "source_role": "troublemaker",
      "point": "节假日峰值流量未考虑",
      "merit": "high",
      "merit_reason": "实际业务存在春节峰值"
    }
  ],
  "ledger": [
    {
      "claim": "Redis incr 足够",
      "raised_by_role": "promoter",
      "raised_at_round": 1,
      "stance_evolution": {
        "type": "revised",
        "evidence": "R2 接受了 Critic 的反驳",
        "trigger": "critic R1 的 high-concurrency 论据"
      }
    }
  ],
  "warnings": [
    "meta-sycophancy 警告: 三方对 Critic 论据接受过快, 缺少独立质疑"
  ]
}
```

---

## 适用场景

| 场景 | 适合度 | 说明 |
|------|--------|------|
| 架构决策 | ✓✓✓ | 4 视角识别耦合点 |
| 方案对比 | ✓✓✓ | A/B 代价边界 |
| 设计审查 | ✓✓✓ | UI/API/数据流 |
| 编码实现 | ✗ | 不需要辩论，Claude 直接做 |
| 事实验证 | ✗ | LLM 集体可能错 |
| 紧急 hotfix | ✗ | 2-4 分钟时长 |

---

## 限制（诚实说明）

- **不替代 Claude Opus thinking 模式**：简单单维度决策直接深思更高效
- **集体幻觉**: 跨厂商已是最强对冲，但 [Majority Rules (arxiv 2511.15714)](https://arxiv.org/html/2511.15714v1) 提醒 correlated errors 真实存在
- **GPT 偶尔不附 JSON summary**：v1.0 三重 prompt 提醒已显著缓解，仍偶有少数情况；judge 仍能从 markdown 推断，graceful degradation
- **Judge 不是绝对真理**：DeepSeek 综合时仍有自己视角偏好，最终决策权在用户
- **不要超过 3 轮**：DRIFTJudge 实证 R3+ 显著恶化
- **上下文必须真实具体**：抽象问题得抽象答案

---

## 成本与时间

| Profile | 1 轮 | 2 轮 + judge | 时长 |
|---------|------|--------------|------|
| cheap | ~$0.10 | ~$0.30-0.50 | 60-120s |
| balanced | ~$0.25 | ~$0.50-0.90 | 90-180s |
| premium | ~$0.90 | ~$2.00-3.50 | 120-240s |

---

## License

MIT © 2026 张拼拼 (Max Pin) / xntj-ai

---

## 贡献

欢迎 fork 修改 model 组合、角色定义、prompt 风格。
- v1.0 已修复 v3 meta-test 自审发现的 5 个根本缺陷
- v1.1+ 候选：DOWN 算法 confidence-based 早停、稀疏通信拓扑、Sakana RL Conductor 路由
