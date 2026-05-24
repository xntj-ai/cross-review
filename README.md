# Cross-Review

> Claude Code skill: **跨厂商对照审查 + 反附和设计 + 独立 judge**。
> Heterogeneous multi-model review with anti-sycophancy prompting and independent judge synthesis.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![OpenRouter](https://img.shields.io/badge/API-OpenRouter-purple.svg)](https://openrouter.ai/)

当你面对一个**架构选择**、**方案设计**或**关键决策**时，cross-review 通过 OpenRouter 同时调起**三个跨厂商模型**（Gemini Promoter + GPT Critic + Grok Troublemaker），跑 2 轮辩论 + 独立 Judge 综合，给出结构化 consensus / divergences / unique_points 的 JSON 报告。

---

## 为什么不用"独白式多模型咨询"

大多数"拉模型一起看"的实现，是**你单独问每一个模型，由你来当法官综合**——这等于让每个模型在真空里发言，看不到彼此的盲区，也无法回应对方论点。但 2025-2026 学界已经验证了几个反直觉结论：

| 误区 | 学术反驳 |
|------|---------|
| "模型越多越准" | [Stop Overvaluing MAD (arxiv 2502.08788)](https://arxiv.org/abs/2502.08788)：同质模型多轮辩论性价比常低于单模型 CoT/SC |
| "2 个模型就够" | [Peacemaker (arxiv 2509.23055)](https://arxiv.org/abs/2509.23055)：2-agent 反而比 3-agent 更易陷入 sycophancy collapse |
| "辩论自然能找盲区" | [Talk Isn't Always Cheap (arxiv 2509.05396)](https://arxiv.org/abs/2509.05396)：模型频繁"从对到错"，被同侪推理同化 |
| "Claude 综合最准" | [Self-Preference Bias (arxiv 2410.21819)](https://arxiv.org/abs/2410.21819)：LLM-as-judge 给自家风格输出系统性偏高分 |
| "辩论越多越深" | [DRIFTJudge (arxiv 2502.19559)](https://arxiv.org/abs/2502.19559)：35% 多轮辩论原地踏步，26% 质量下降 |

v2 的设计**正面回应了每一条**：跨厂商 3 模型 + 角色化反附和 + 独立 judge + R1 早停 + 限制轮次。

---

## 工作原理

```
┌──────────────────────────────────────────────────────────┐
│ Round 1 (并行)                                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  Promoter    │  │  Critic      │  │ Troublemaker │    │
│  │  Gemini 3.1  │  │  GPT-5.5     │  │  Grok 4.20   │    │
│  │  temp 0.3    │  │  temp 0.3    │  │  temp 0.7    │    │
│  │  建设性视角  │  │  深度推理    │  │  禁止附和    │    │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │
└─────────┼─────────────────┼─────────────────┼────────────┘
          └─────────────────┼─────────────────┘
                            ▼
              ┌─────────────────────────┐
              │  Early Stop Check       │
              │  三方一致? -> 跳过 R2   │
              └────────┬────────────────┘
                       │ NO
                       ▼
┌──────────────────────────────────────────────────────────┐
│ Round 2 (并行 + 强制反附和)                                │
│  每个模型看到其他两方 R1。                                 │
│  Troublemaker prompt: "禁止以'我同意'开头,                 │
│   必须找对方未提及的 ≥2 盲区"                              │
└──────────────────────────┬────────────────────────────────┘
                           ▼
              ┌──────────────────────────┐
              │  Judge (Gemini 独立)      │
              │  输出结构化 JSON         │
              │  - consensus[]           │
              │  - divergences[]         │
              │  - unique_points[]       │
              │  - warnings[]            │
              │  - final_recommendation  │
              └──────────────────────────┘
```

---

## 快速开始

### 前置条件

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 已安装
- Python 3.10+
- 一个 [OpenRouter API Key](https://openrouter.ai/)（按 token 付费，注册即送试用额度）

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

三种方式任选其一（脚本按顺序查找）：

**方式 A：环境变量（推荐，跨 session 复用）**

```bash
export OPENROUTER_API_KEY="sk-or-..."
```

**方式 B：写入 `~/.claude/settings.local.json`**

```json
{
  "credentials": {
    "openrouter": {
      "OPENROUTER_API_KEY": "sk-or-..."
    }
  }
}
```

**方式 C：MCP servers env**

```json
{
  "mcpServers": {
    "openrouter": {
      "env": { "OPENROUTER_API_KEY": "sk-or-..." }
    }
  }
}
```

### （可选）本地代理

如果在中国大陆访问 OpenRouter 受限：

```bash
export OPENROUTER_PROXY="http://127.0.0.1:10808"
```

脚本默认走 `http://127.0.0.1:10808`（常见 V2RayN 混合端口）。

### 验证

重启 Claude Code，对话中说：

> "用 cross-review 审一下这个方案"

或直接调脚本：

```bash
python ~/.claude/skills/cross-review/scripts/cross_review.py \
  examples/example_prompt.json \
  --profile balanced
```

---

## 使用方式

### 自然语言触发（推荐）

```
# 架构决策
"我准备把 cruna-studio 从 systemd 迁到 Docker，先用 cross-review 审一下方案"

# 方案对比
"用多模型审一下：积分系统用 Redis incr 还是 Postgres advisory lock"

# 设计审查
"这版 UI 稿拉 Gemini、GPT、Grok 一起看，找盲区"
```

Claude 会自动构建 prompt JSON 并调脚本。

### 直接调脚本

```bash
# 准备 prompt JSON
cat > /tmp/review.json <<'EOF'
{
  "context": "现有系统: ... 技术约束: ... 已有调研: ...",
  "question": "1. 方案 A vs B 的代价边界? 2. 有什么盲区?"
}
EOF

# 跑 v2
python ~/.claude/skills/cross-review/scripts/cross_review.py \
  /tmp/review.json \
  --profile premium \
  --with-judge \
  --output /tmp/result.md \
  --json-output /tmp/result.json
```

---

## Profile 对照

| Profile | Promoter | Critic | Troublemaker | 成本/次 | 适用 |
|---------|----------|--------|--------------|---------|------|
| `cheap` | Gemini 3 Flash | GPT-5.4 Mini | Grok 4.20 | $0.15-0.25 | 探索性、批量 |
| `balanced` | Gemini 3.1 Pro | GPT-5.4 | Grok 4.20 | $0.40-0.60 | 日常审查（性价比甜点） |
| `premium` *(default)* | Gemini 3.1 Pro | GPT-5.5 | Grok 4.20 Multi-Agent | $1.20-1.80 | 重大决策 |

`--with-judge` 额外 +$0.30-0.50（用 Gemini 3.1 Pro 综合）。

完整参数列表 `python cross_review.py --help`。

---

## 输出示例

`--with-judge` 时，judge JSON 输出：

```json
{
  "consensus": [
    {
      "point": "三方都同意先迁数据再切流量",
      "details": "Promoter/Critic/Troublemaker 均强调灰度的必要性"
    }
  ],
  "divergences": [
    {
      "topic": "是否需要 advisory lock",
      "promoter": "Redis incr 足够，无需复杂锁",
      "critic": "高并发下 Redis 可能丢失增量，建议 PG advisory",
      "troublemaker": "二者都不解决 race condition 边界 X",
      "judge_recommendation": "Critic 论据最强，引用了具体边界条件"
    }
  ],
  "unique_points": [
    {
      "source": "troublemaker",
      "point": "未考虑节假日突发流量场景",
      "merit": "high",
      "merit_reason": "实际业务存在春节高峰，应补充压测"
    }
  ],
  "warnings": [],
  "final_recommendation": "采用 PG advisory lock 方案，但保留 Redis 作 cache 层。补充节假日峰值压测。"
}
```

---

## 适用场景

| 场景 | 适合度 | 说明 |
|------|--------|------|
| 架构决策 | ✓✓✓ | 三方视角识别耦合点 |
| 方案对比 | ✓✓✓ | 让模型辩论 A/B 代价边界 |
| 设计审查 | ✓✓✓ | UI/API/数据流的可用性 + 一致性 |
| 编码实现 | ✗ | 写代码不需要辩论，Claude 直接做 |
| 事实验证 | ✗ | LLM 集体可能记错事实，用文档/源码验证 |
| 紧急 hotfix | ✗ | 2-3 分钟辩论时间不适合紧急场景 |

---

## 限制（诚实说明）

- **不替代 Claude Opus thinking mode 的内部推理深度**：简单单维度决策，直接让 Claude 深思可能更高效
- **集体幻觉风险**：[Majority Rules (arxiv 2511.15714)](https://arxiv.org/html/2511.15714v1) 显示 LLM 间存在跨模型的 correlated errors；跨厂商 + 反附和是已知最强对冲，但不能根除
- **不要超过 3 轮**：DRIFTJudge 证明 R3+ 显著恶化
- **judge 不是绝对真理**：Gemini 综合时仍有自己的视角偏好，最终决策权在用户
- **上下文必须真实具体**：抽象问题得抽象答案——给真实文件片段、实际代码、具体数字

---

## 成本与时间

| Profile | 1 轮 | 2 轮 + judge | 平均时长 |
|---------|------|--------------|---------|
| cheap | ~$0.08 | ~$0.20-0.30 | 60-90s |
| balanced | ~$0.20 | ~$0.50-0.70 | 90-150s |
| premium | ~$0.60 | ~$1.50-2.30 | 120-180s |

`--max-cost 3.00` 默认 cost guard 在超支时中断。

---

## v1 → v2 变化

| 维度 | v1 (2026-02) | v2 (2026-05) |
|------|--------------|--------------|
| 模型数 | 2 | 3 |
| 角色分工 | 同质（资深架构师 ×2） | promoter / critic / troublemaker |
| temperature | 全模型 0.3 | troublemaker 0.7 |
| 综合者 | Claude 主模型（自评偏见） | Gemini 独立 judge（可选） |
| 输出 | markdown only | markdown + 结构化 JSON |
| 早停 | 无 | R1 共识检测 |
| 反附和 | 无 | system prompt 强制 + 输出检测 |
| 成本守卫 | 无 | `--max-cost` |
| 默认成本 | $0.10-0.20 | $1.50-2.00 (premium) / $0.50 (balanced) |

---

## License

MIT © 2026 张拼拼 (Max Pin)

---

## 学术参考

- [Stop Overvaluing Multi-Agent Debate (arxiv 2502.08788)](https://arxiv.org/abs/2502.08788)
- [Peacemaker or Troublemaker (arxiv 2509.23055)](https://arxiv.org/abs/2509.23055)
- [Free-MAD (arxiv 2509.11035)](https://arxiv.org/abs/2509.11035)
- [Stay Focused: Problem Drift in MAD (arxiv 2502.19559)](https://arxiv.org/abs/2502.19559)
- [Self-Preference Bias in LLM-as-Judge (arxiv 2410.21819)](https://arxiv.org/abs/2410.21819)
- [Talk Isn't Always Cheap (ICML 2025, arxiv 2509.05396)](https://arxiv.org/abs/2509.05396)
- [Diversity of Thought (arxiv 2410.12853)](https://arxiv.org/abs/2410.12853)

---

## 贡献

欢迎 fork 修改 model 组合、角色定义、prompt 风格。如果你在实际项目中跑出有意思的 case，欢迎开 issue 分享。
