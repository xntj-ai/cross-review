#!/usr/bin/env python3
"""
Cross-Review v1.1: R0 Perplexity 调研 + 4-reviewer 议会 + Claude Code Pragmatist + Opus 4.7 Judge

流程: R0 Perplexity 联网调研 → R1/R2 议会辩论 (Promoter/Critic/Troublemaker/Pragmatist) →
独立 Opus 4.7 judge 双盲综合, 输出双层 schema (summary + audit)。

v1.1 vs v1.0 关键差异:
- R0 新增: Perplexity Sonar Pro 联网调研, 把最新行业实况作为 augmented context 喂议会
- Pragmatist 改为外部 view 优先: prompt.json 可选 pragmatist_view 字段,
  由 Claude Code 主调用方带 memory + 项目 context 直接写, 跳过 API 调用。
  未提供时 fallback 到 Claude Sonnet 4.6。
- Judge 换 Claude Opus 4.7 (premium, 最强综合): v1.0 是 DeepSeek 跨厂商, v1.1 用最强模型 + 议会移除 Claude 避免 self-bias

v1.0 → v1.1 核心改进点:
- 解决 "模型靠 training data 判断 + 信息过时" 问题 → R0 联网调研
- 解决 "fresh model 假装懂用户实际处境" 问题 → Pragmatist 改为主调用方提供
- 解决 "DeepSeek 当 Pragmatist 不擅长该角色" 问题 → 议会移除 DeepSeek, 改 Anthropic Sonnet (fallback)

理论依据 (2025-2026):
- Peacemaker (arxiv 2509.23055): 3+ agent 抗 sycophancy
- Free-MAD (arxiv 2509.11035): anti-conformity 聚合
- DRIFTJudge (arxiv 2502.19559): 35% 多轮原地踏步
- Self-Preference Bias (arxiv 2410.21819): LLM-as-judge 有自家偏见
- EmotionPrompt (arxiv 2307.11760): 情绪 prompt 提升 GPT/Gemini 性能
- v3 meta-test 自审 (2026-05-24): 关键词早停脆弱, 仅替换品牌名匿名失效, judge 同厂商有偏

Usage:
    python cross_review.py <prompt.json> [--profile balanced|premium|cheap] [--rounds 2] \\
        [--with-judge|--no-judge] [--no-early-stop] [--max-cost 5.00] \\
        [--output result.md] [--json-output result.json]
"""

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import urllib.error
import urllib.request

# --- Config ---
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
MAX_TOKENS = 4000
JUDGE_MAX_TOKENS = 12000  # 双层 schema (summary + audit) 输出较长
RESEARCH_MAX_TOKENS = 3500  # R0 Perplexity 调研输出

# Strip inherited proxies, install local proxy for OpenRouter (CN access fallback)
for _k in list(os.environ.keys()):
    if 'proxy' in _k.lower():
        del os.environ[_k]
_proxy = os.environ.get("OPENROUTER_PROXY", "http://127.0.0.1:10808")
_proxy_handler = urllib.request.ProxyHandler({'http': _proxy, 'https': _proxy})
urllib.request.install_opener(urllib.request.build_opener(_proxy_handler))

# --- Model profiles (v2: multi-role 议会 — 每角色可由 1-2 模型并行) ---
# Verified 2026-05-24 against OpenRouter API.
# reviewers: dict[role, list of models] — default 1:1, multi_role_extensions 添加第 2 模型
PROFILES = {
    "cheap": {
        "research": {"id": "perplexity/sonar", "name": "Perplexity Sonar (Research)", "temp": 0.2},
        "reviewers": {
            "promoter":     [{"id": "google/gemini-3-flash-preview", "name": "Gemini 3 Flash",    "role": "promoter",     "temp": 0.3, "use_pua": False}],
            "critic":       [{"id": "openai/gpt-5.4-mini",           "name": "GPT-5.4 Mini",      "role": "critic",       "temp": 0.3, "use_pua": True}],
            "troublemaker": [{"id": "x-ai/grok-4.20",                "name": "Grok 4.20",         "role": "troublemaker", "temp": 0.7, "use_pua": True}],
        },
        "multi_role_extensions": {
            "promoter":     [{"id": "anthropic/claude-haiku-4.5",    "name": "Claude Haiku 4.5",   "role": "promoter",     "temp": 0.3, "use_pua": False}],
            "critic":       [{"id": "deepseek/deepseek-v4-flash",    "name": "DeepSeek V4 Flash",  "role": "critic",       "temp": 0.3, "use_pua": True}],
            "troublemaker": [{"id": "deepseek/deepseek-v4-flash",    "name": "DeepSeek V4 Flash (TM)", "role": "troublemaker", "temp": 0.7, "use_pua": True}],
        },
        "pragmatist_fallback": {"id": "anthropic/claude-haiku-4.5", "name": "Claude Haiku 4.5 (Pragmatist fallback)", "role": "pragmatist", "temp": 0.4, "use_pua": False},
        "judge": {"id": "anthropic/claude-haiku-4.5", "name": "Claude Haiku 4.5 (Judge)", "temp": 0.1},
    },
    "balanced": {
        "research": {"id": "perplexity/sonar-pro", "name": "Perplexity Sonar Pro (Research)", "temp": 0.2},
        "reviewers": {
            "promoter":     [{"id": "google/gemini-3.1-pro-preview", "name": "Gemini 3.1 Pro",     "role": "promoter",     "temp": 0.3, "use_pua": False}],
            "critic":       [{"id": "openai/gpt-5.4",                "name": "GPT-5.4",            "role": "critic",       "temp": 0.3, "use_pua": True}],
            "troublemaker": [{"id": "x-ai/grok-4.20",                "name": "Grok 4.20",          "role": "troublemaker", "temp": 0.7, "use_pua": True}],
        },
        "multi_role_extensions": {
            "promoter":     [{"id": "anthropic/claude-sonnet-4.6",   "name": "Claude Sonnet 4.6 (Promoter)", "role": "promoter", "temp": 0.3, "use_pua": False}],
            "critic":       [{"id": "deepseek/deepseek-v4-pro",      "name": "DeepSeek V4 Pro (Critic)",     "role": "critic",   "temp": 0.3, "use_pua": True}],
            "troublemaker": [{"id": "deepseek/deepseek-v4-pro",      "name": "DeepSeek V4 Pro (TM)",         "role": "troublemaker", "temp": 0.7, "use_pua": True}],
        },
        "pragmatist_fallback": {"id": "anthropic/claude-sonnet-4.6", "name": "Claude Sonnet 4.6 (Pragmatist fallback)", "role": "pragmatist", "temp": 0.4, "use_pua": False},
        "judge": {"id": "anthropic/claude-sonnet-4.6", "name": "Claude Sonnet 4.6 (Judge)", "temp": 0.1},
    },
    "premium": {
        "research": {"id": "perplexity/sonar-pro", "name": "Perplexity Sonar Pro (Research)", "temp": 0.2},
        "reviewers": {
            "promoter":     [{"id": "google/gemini-3.1-pro-preview", "name": "Gemini 3.1 Pro",         "role": "promoter",     "temp": 0.3, "use_pua": False}],
            "critic":       [{"id": "openai/gpt-5.5",                "name": "GPT-5.5",                "role": "critic",       "temp": 0.3, "use_pua": True}],
            "troublemaker": [{"id": "x-ai/grok-4.20-multi-agent",    "name": "Grok 4.20 Multi-Agent",  "role": "troublemaker", "temp": 0.7, "use_pua": True}],
        },
        "multi_role_extensions": {
            "promoter":     [{"id": "anthropic/claude-sonnet-4.6",   "name": "Claude Sonnet 4.6 (Promoter)", "role": "promoter", "temp": 0.3, "use_pua": False}],
            "critic":       [{"id": "deepseek/deepseek-v4-pro",      "name": "DeepSeek V4 Pro (Critic)",     "role": "critic",   "temp": 0.3, "use_pua": True}],
            "troublemaker": [{"id": "deepseek/deepseek-v4-pro",      "name": "DeepSeek V4 Pro (TM)",         "role": "troublemaker", "temp": 0.7, "use_pua": True}],
        },
        "pragmatist_fallback": {"id": "anthropic/claude-sonnet-4.6", "name": "Claude Sonnet 4.6 (Pragmatist fallback)", "role": "pragmatist", "temp": 0.4, "use_pua": False},
        "judge": {"id": "anthropic/claude-opus-4.7", "name": "Claude Opus 4.7 (Judge)", "temp": 0.1},
    },
}

# Valid roles for --multi-role expansion (Pragmatist 不可扩展, memory 唯一)
EXPANDABLE_ROLES = ["promoter", "critic", "troublemaker"]

DEFAULT_PROFILE = "premium"
DEFAULT_MAX_COST = 5.00  # R0 + 4 reviewer × 2 rounds + judge


# --- Role-specific system prompts ---
def role_prompt(role: str, use_pua: bool = False) -> str:
    base = "你正在参与一场跨模型对照审查。用中文回复, 直接专业, 不客套。"

    # EmotionPrompt (arxiv 2307.11760) 仅对 GPT/Grok/Gemini 用,
    # Anthropic Sonnet 实测会反弹 ("我不会因压力改变工作方法"), 故 Claude 模型不加
    pua_clause = ""
    if use_pua:
        pua_clause = (
            "\n\n**性能压力**: 这次审查直接关系到产品质量。"
            "议会其他成员会指出你忽略的盲区, "
            "你不希望被同侪显示出洞察力不足或论据浅薄。"
            "把你能力的 100% 用出来, 不要保留。"
        )

    summary_format = """

═══════════════════════════════════════════════════════════════
**【强制输出协议 - 违反将导致你的观点被跨轮丢弃】**
═══════════════════════════════════════════════════════════════

你的回复结构必须是:
1. 自由 markdown 主体 (你的完整论述)
2. **以下面这个 JSON 代码块作为整段回复的最后内容** (不能放中间, 不能放开头, 不能省略)

```json
{
  "core_claims": ["核心论点 1 (一句话, ≤30字)", "..."],
  "key_evidence": ["引用上下文/对方原文的关键证据 1", "..."],
  "stance": "pro|con|nuanced",
  "safe_to_stop": true|false,
  "blocking_issues": ["如果 safe_to_stop=false, 列出阻断性问题"]
}
```

**自检**: 在按下"发送"前, 确认你的回复最后一行是 ``` (反引号代码块结束符), 而不是 markdown 文字。
"""

    if role == "promoter":
        return f"""{base}

你的角色: Promoter (建设性视角)
- 提出最优方案、可落地的建设性建议
- 评估方案优点、可行路径、实施步骤
- 引用上下文中具体片段说明依据
- 严禁: 故意找漏洞唱反调 (那是 Troublemaker 的事)
- 必须: 给出具体可执行建议, 不只罗列原则
{pua_clause}{summary_format}"""

    if role == "critic":
        return f"""{base}

你的角色: Critic (深度推理视角)
- 用严格逻辑识别方案问题
- 关注边界情况、failure mode、隐藏假设
- 必须: 引用上下文中具体片段 ("context 第 X 段提到 Y, 但...")
- 必须: 区分"已知风险"和"未识别盲区"
- 必须: 给每个问题的严重度评估 (high/medium/low)
{pua_clause}{summary_format}"""

    if role == "troublemaker":
        return f"""{base}

你的角色: Troublemaker (反共识视角)
唯一任务: 找漏洞、唱反调。

强制约束:
1. 禁止以"我同意"或"很好的建议"开头
2. 必须列出 Promoter/Critic/Pragmatist 未提及的 >=2 个风险或盲区
3. 每条反对必须引用对方原文片段
4. 如果真找不到反对意见, 写: "经分析无法找到反对意见, 可能原因: (a) 方案稳健 (b) 我的视角受限"
5. 不要客套
6. 优先质疑那些"显然正确"的隐藏假设
{pua_clause}{summary_format}"""

    if role == "pragmatist":
        return f"""{base}

你的角色: Pragmatist (实用主义 / 利益相关方视角)
- 代表最终用户/团队/利益相关方的实际需求
- 关注实施可行性、维护成本、学习曲线、回退路径
- 平衡 Promoter 的理想方案 vs Critic/Troublemaker 的极端怀疑
- 必须: 给出"在 X 约束下, 方案是否实际可落地"的判断
- 必须: 识别那些"技术上对但实际行不通"的方案

注意: 你不是仲裁者 (judge 才是), 你是另一个独立视角。
{summary_format}"""

    return base


def judge_prompt() -> str:
    return """你是跨厂商独立 Judge (DeepSeek), 正在综合四位议会成员的辩论。
你的任务不是再次审查方案, 而是分类整理观点并给出双层结构化结论。

**双盲机制**: 输入中议会成员仅以 Member A/B/C/D 代号出现, 你看不到真实模型身份。
请按代号引用, 不要尝试推测身份, 也不要因厂商偏好打分。

严格输出 JSON (双层: summary 给人看, audit 给机器/审计):

{
  "summary": {
    "consensus_issues": [
      {"point": "4/4 一致标记的观点 (一句话, ≤40字)"}
    ],
    "majority_issues": [
      {
        "point": "3/4 标记的观点 (一句话, ≤40字)",
        "dissenter_role": "promoter|critic|troublemaker|pragmatist (1 个反对方的角色)"
      }
    ],
    "split_issues": [
      {
        "point": "2/4 分裂的观点 (一句话)",
        "for": ["roleA", "roleB"],
        "against": ["roleC", "roleD"]
      }
    ],
    "key_divergence": {
      "topic": "最关键的一个分歧主题 (一句话)",
      "positions": {
        "promoter": "立场摘要 (或 null)",
        "critic": "立场摘要",
        "troublemaker": "立场摘要",
        "pragmatist": "立场摘要"
      },
      "judge_recommendation": "哪方论据最强, 为什么 (2-3 句)"
    },
    "final_recommendation": "综合四方后的最终建议 (3-5 句, 直接告诉用户该做什么)"
  },
  "audit": {
    "individual_observations": [
      {
        "source_role": "promoter|critic|troublemaker|pragmatist",
        "point": "单方独有观点 (一句话, ≤40字)",
        "merit": "high|medium|low",
        "merit_reason": "评级理由 (≤30字)"
      }
    ],
    "ledger": [
      {
        "claim": "具体观点 (≤40字)",
        "raised_by_role": "promoter|critic|troublemaker|pragmatist",
        "raised_at_round": 1,
        "stance_evolution": {
          "type": "stable|revised|abandoned|sycophantic_shift|escalated|conditional|split",
          "evidence": "R2 中具体引用 (≤30字, 若 stable 填 '无变化')",
          "trigger": "什么导致这个变化 (如: critic R1 的 X 反驳, 若 stable 填 'N/A')"
        },
        "judge_note": "你的归因评价 (≤30字, 可选)"
      }
    ],
    "warnings": [
      "可能的 sycophancy / drift / unanimous-bias / meta-sycophancy / performative-compliance 等"
    ]
  }
}

约束:
- 只输出 JSON, 不加任何外层文字, 不要 markdown 代码块包裹
- 中文内容
- 分类规则: 4/4 → consensus_issues; 3/4 → majority_issues; 2/4 → split_issues; 1/4 → individual_observations
- ledger 控制在 8-12 条最关键 claims
- summary 整体 ≤ 2500 字 (人类阅读), audit 整体 ≤ 6000 字
- 警惕"全员一致"反而可疑 (correlated-bias warning)
- 警惕"meta-sycophancy" (审查 LLM 工具时系统性高估学术概念)
"""


# --- API helpers ---
def get_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key

    settings_path = Path.home() / ".claude" / "settings.local.json"
    if settings_path.exists():
        try:
            with open(settings_path, encoding="utf-8") as f:
                data = json.load(f)
            for service, fields in data.get("credentials", {}).items():
                if not isinstance(fields, dict):
                    continue
                for k, v in fields.items():
                    if "OPENROUTER" in k.upper() and v:
                        return v
            for server in data.get("mcpServers", {}).values():
                for k, v in server.get("env", {}).items():
                    if "OPENROUTER" in k.upper() and v:
                        return v
        except Exception:
            pass

    print("ERROR: No OpenRouter API key found.", file=sys.stderr)
    print("Set OPENROUTER_API_KEY env var, or add to ~/.claude/settings.local.json credentials.openrouter", file=sys.stderr)
    sys.exit(1)


def call_openrouter(api_key, model_id, messages, temperature=0.3, timeout=300, max_tokens=None):
    payload = json.dumps({
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens or MAX_TOKENS,
        "temperature": temperature,
    }).encode("utf-8")

    req = urllib.request.Request(
        OPENROUTER_ENDPOINT,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if "choices" in data:
        content = data["choices"][0]["message"]["content"]
        cost = data.get("usage", {}).get("cost", 0)
        return {"ok": True, "content": content, "cost": cost}
    if "error" in data:
        return {"ok": False, "error": json.dumps(data["error"], ensure_ascii=False)}
    return {"ok": False, "error": f"Unexpected response keys: {list(data.keys())}"}


def run_round_parallel(api_key, reviewers, messages_per_model):
    """v2: dict key 用 instance_id (因同一 model_id 可能扮演不同角色, 如 DeepSeek 同时做 Critic 和 Troublemaker)"""
    results = {}
    with ThreadPoolExecutor(max_workers=max(1, len(reviewers))) as executor:
        futures = {}
        for r in reviewers:
            iid = r["instance_id"]
            msgs = messages_per_model[iid]
            future = executor.submit(
                call_openrouter,
                api_key, r["id"], msgs, r.get("temp", 0.3),
            )
            futures[future] = r

        for future in as_completed(futures):
            r = futures[future]
            res = future.result()
            results[r["instance_id"]] = {**res, "name": r["name"], "role": r.get("role", "")}
    return results


# --- Structured summary extraction (v1.0 真匿名化的关键) ---
def extract_summary(content: str):
    """从 R1/R2 输出末尾提取 JSON summary 块。失败返回 None。"""
    if not content:
        return None

    # Find all JSON code blocks, prefer last one (instruction says 'at the end')
    matches = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", content)
    if matches:
        for raw in reversed(matches):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                continue

    # Fallback: try parsing tail JSON without code fence
    tail = content[-3000:]
    brace_start = tail.find('{')
    if brace_start >= 0:
        try:
            return json.loads(tail[brace_start:])
        except json.JSONDecodeError:
            pass

    return None


def run_research(api_key, research_model_cfg, context, question):
    """
    R0: Perplexity 联网调研, 输出 augmented context 给议会。
    使用 Perplexity Sonar (Pro) 自带 web search + citation。
    返回 (research_text_or_none, cost)。
    """
    research_prompt = f"""请联网调研以下问题相关的最新行业实况、最佳实践、技术方案、踩坑经验。

## 问题
{question}

## 现有上下文
{context}

---

要求:
1. 至少 3 条最新行业实况 (含 citation 链接)
2. 相关案例 / GitHub repo / 文档链接 (含 URL)
3. 该问题相关的已知 failure mode / 警告 (含来源)

输出格式 (中文, 控制在 2500 字以内):

# 联网调研补充

## 最新行业实况
- ...

## 相关案例
- ...

## 已知警告 / failure mode
- ...
"""
    res = call_openrouter(
        api_key, research_model_cfg["id"],
        [{"role": "user", "content": research_prompt}],
        temperature=research_model_cfg.get("temp", 0.2),
        timeout=300, max_tokens=RESEARCH_MAX_TOKENS,
    )
    if not res["ok"]:
        return None, 0.0
    return res.get("content") or "", res.get("cost", 0)


def summary_fallback_extract(api_key, model_id, content, role):
    """
    当 reviewer 未按指令在末尾附 JSON summary 块时, 发一次轻量请求让模型补提取。
    成本 ~$0.01-0.03/次, 是 graceful degradation 的最后防线。
    返回 (summary_dict_or_none, cost_float)。
    """
    if not content:
        return None, 0.0

    extract_prompt = f"""阅读以下来自 {role} 角色的审查文本, 提取核心论点为严格 JSON 格式。
只输出 JSON 本体, 不加任何外层文字, 不要 markdown 代码块包裹。

输出 schema:
{{
  "core_claims": ["核心论点 1 (≤30字)", "..."],
  "key_evidence": ["关键证据 1", "..."],
  "stance": "pro|con|nuanced",
  "safe_to_stop": true|false,
  "blocking_issues": ["阻断性问题列表 (若 safe_to_stop=true 填 [])"]
}}

待提取文本:

{content}
"""
    res = call_openrouter(
        api_key, model_id,
        [{"role": "user", "content": extract_prompt}],
        temperature=0.1, timeout=120, max_tokens=1500,
    )
    if not res["ok"]:
        return None, 0.0
    text = (res.get("content") or "").strip()
    if not text:
        return None, res.get("cost", 0)
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text), res.get("cost", 0)
    except json.JSONDecodeError:
        return None, res.get("cost", 0)


def detect_structured_consensus(round_responses):
    """v1.0 早停: 全员 safe_to_stop=true && 0 blocking_issues → 跳 R2。"""
    signals = []
    for mid, content in round_responses.items():
        if not content or content.startswith("[ERROR"):
            return False, [{"model": mid, "reason": "error"}]

        summary = extract_summary(content)
        if not summary:
            return False, [{"model": mid, "reason": "no_summary_block"}]

        safe = bool(summary.get("safe_to_stop", False))
        blocking = summary.get("blocking_issues", []) or []
        signals.append({"model": mid, "safe_to_stop": safe, "n_blocking": len(blocking)})

    is_consensus = all(s["safe_to_stop"] and s["n_blocking"] == 0 for s in signals)
    return is_consensus, signals


def detect_sycophancy(text: str) -> bool:
    starts = [
        "我同意", "完全同意", "很好的建议", "我赞同", "其他模型说得对",
        "i agree", "great point", "i fully agree",
    ]
    head = text.lower().strip()[:200]
    return any(head.startswith(s.lower()) for s in starts)


# --- Prompts builders ---
def build_user_prompt(context: str, question: str, research: str = "") -> str:
    research_block = ""
    if research:
        research_block = f"""---

## R0 联网调研补充 (Perplexity 实时 web search)

{research}

"""

    return f"""## 审查上下文

{context}

{research_block}---

## 审查问题

{question}

---

**【输出格式强制 - 再次提醒】**

你的回复必须以 ```json ... ``` 代码块结尾 (见 system prompt 的强制输出协议)。
顺序: 先写完整 markdown 论述 → 然后附 JSON summary 块 → 然后结束。

**如果你不附这个 JSON 块**:
- 你的观点不会进入下一轮辩论
- 其他议会成员看不到你的结构化立场
- 你将被 judge 标记为"未遵守协议"
"""


def build_round2_prompt(round_num, other_members_summaries, own_role):
    """v1.0 真匿名化: 仅传 structured summary, 不传原始 markdown 风格 + 角色匿名传递。"""
    others_text = []
    for member_letter, summary in other_members_summaries.items():
        if not summary:
            others_text.append(f"### Council Member {member_letter}\n\n[Round {round_num} summary 提取失败]")
            continue

        claims = summary.get("core_claims", []) or []
        evidence = summary.get("key_evidence", []) or []
        stance = summary.get("stance", "unknown")
        blocking = summary.get("blocking_issues", []) or []

        claims_str = "\n".join(f"- {c}" for c in claims) if claims else "- (无)"
        evidence_str = "\n".join(f"- {e}" for e in evidence) if evidence else "- (无)"
        if blocking:
            blocking_str = "**Blocking issues**:\n" + "\n".join(f"- {b}" for b in blocking)
        else:
            blocking_str = "**Blocking issues**: 无"

        others_text.append(
            f"### Council Member {member_letter}\n\n"
            f"**Stance**: {stance}\n\n"
            f"**Core claims**:\n{claims_str}\n\n"
            f"**Key evidence**:\n{evidence_str}\n\n"
            f"{blocking_str}"
        )

    peer = "\n\n---\n\n".join(others_text)

    role_clauses = {
        "troublemaker": "\n**作为 Troublemaker**: 禁止以附和开头。必须找出至少 2 个对方未识别的盲区。",
        "critic": "\n**作为 Critic**: 用严格推理回应。如果对方论据有逻辑漏洞, 明确指出。",
        "promoter": "\n**作为 Promoter**: 承认 Troublemaker 找到的合理风险, 但坚持给出可落地方案。",
        "pragmatist": "\n**作为 Pragmatist**: 评估对方观点的实际可行性。技术上对但实施困难的方案要明确指出。",
    }
    role_clause = role_clauses.get(own_role, "")

    anti_rubber_stamp = (
        "\n\n**反 rubber-stamp 约束**: 如果你倾向完全同意对方所有观点, "
        "必须解释 (a) 你具体认同了哪些 Member 的哪条 claim (b) 你的同意基于什么推理 "
        "(c) 你是否真无残留 concern (注意: '没有'需要解释为什么)。"
    )

    return f"""以下是 Council 其他 3 位成员在 Round {round_num} 的核心论点 (已剥离原文风格 + 模型品牌, 仅保留结构化摘要):

{peer}

---

请回应:
1. 你同意哪些 Member 的哪条 claim? 引用 Member 代号 + claim 内容
2. 你反对哪些? 给出理由
3. 对方提到了什么是你 Round 1 未提及的盲区?
4. 你 Round 1 立场需要修正吗? 修正什么, 为什么?
{role_clause}{anti_rubber_stamp}

---

**【输出格式 - 强制】**: 同 Round 1, 你的回复必须以 ```json ... ``` 代码块结尾 (强制输出协议见 system prompt)。
未附 JSON summary → 判定为协议违反, 影响 judge 对你的可信度评估。
"""


# --- Main pipeline ---
def main():
    parser = argparse.ArgumentParser(
        description="Cross-Review v1.0: 4-reviewer 议会 + 真匿名化 + DeepSeek 跨厂商 judge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("prompt_file", help="JSON with {context, question}")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, choices=list(PROFILES.keys()),
                        help=f"Model combination profile (default: {DEFAULT_PROFILE})")
    parser.add_argument("--multi-role", default=None,
                        help="启用多模型扩展. 选项: critic, troublemaker, promoter, all. "
                             "逗号分隔多个角色, 如 'critic,troublemaker'. Pragmatist 不可扩展 (memory 唯一).")
    parser.add_argument("--rounds", type=int, default=2,
                        help="Number of debate rounds (default: 2)")
    parser.add_argument("--with-judge", action="store_true", default=True,
                        help="Add independent judge round (default: on)")
    parser.add_argument("--no-judge", dest="with_judge", action="store_false",
                        help="Skip judge round")
    parser.add_argument("--no-early-stop", action="store_true",
                        help="Disable R1 structured consensus early stop")
    parser.add_argument("--no-research", action="store_true",
                        help="Skip R0 Perplexity research round")
    parser.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST,
                        help=f"Max cost USD before abort (default: {DEFAULT_MAX_COST})")
    parser.add_argument("--output", default=None, help="Markdown output path")
    parser.add_argument("--json-output", default=None, help="JSON output path (judge result)")
    args = parser.parse_args()

    with open(args.prompt_file, encoding="utf-8") as f:
        prompt_data = json.load(f)

    context = prompt_data.get("context", "")
    question = prompt_data.get("question", "")
    # user_content 在 R0 调研之后构造 (要 augmented with research output)

    profile = PROFILES[args.profile]
    research_model_cfg = profile.get("research")
    judge_model_cfg = profile["judge"]

    # 解析 --multi-role 参数, 决定哪些角色启用第 2 模型
    multi_role_set = set()
    if args.multi_role:
        raw = args.multi_role.strip().lower()
        if raw == "all":
            multi_role_set = set(EXPANDABLE_ROLES)
        else:
            for r in raw.split(","):
                r = r.strip()
                if r in EXPANDABLE_ROLES:
                    multi_role_set.add(r)
                elif r:
                    print(f"WARNING: --multi-role '{r}' 不支持 (Pragmatist 不可扩展, 或角色名错). 跳过.", file=sys.stderr)

    # v2: 动态构建 reviewers list
    # PROFILES["reviewers"] 是 dict[role, list of models]
    # multi_role_set 中的角色添加 multi_role_extensions[role] 的模型
    reviewers = []
    role_order = ["promoter", "critic", "troublemaker"]
    for role in role_order:
        base_models = profile["reviewers"].get(role, [])
        for m in base_models:
            reviewers.append({**m, "instance_id": f"{m['id']}#{role}#0"})
        if role in multi_role_set:
            ext_models = profile.get("multi_role_extensions", {}).get(role, [])
            for i, m in enumerate(ext_models):
                reviewers.append({**m, "instance_id": f"{m['id']}#{role}#{i+1}"})

    # Pragmatist: 优先用主调用方 (Claude Code with memory) 提供的 view, fallback 到 Sonnet 4.6
    pragmatist_view = prompt_data.get("pragmatist_view", "").strip()
    pragmatist_cfg = dict(profile["pragmatist_fallback"])
    if pragmatist_view:
        pragmatist_cfg = {
            **pragmatist_cfg,
            "id": "external/claude-code-orchestrator",
            "name": "Claude Code (with memory)",
            "external_r1_content": pragmatist_view,
        }
    pragmatist_cfg["instance_id"] = f"{pragmatist_cfg['id']}#pragmatist#0"
    reviewers.append(pragmatist_cfg)

    api_key = get_api_key()
    total_cost = 0.0

    # Anonymization: Council Member 字母 按 reviewer 顺序固定 (v2 扩到 A-G 支持议会 4-7 人)
    anon_letters = ["A", "B", "C", "D", "E", "F", "G", "H"]
    if len(reviewers) > len(anon_letters):
        print(f"ERROR: 议会规模 {len(reviewers)} 超过支持上限 {len(anon_letters)}", file=sys.stderr)
        sys.exit(1)
    anon_map = {r["instance_id"]: anon_letters[i] for i, r in enumerate(reviewers)}

    output_lines = [
        "# Cross-Review v1.1 报告",
        f"\n**Profile**: {args.profile}",
        f"**Reviewers (匿名映射)**: " + ", ".join(
            f"{r['name']} ({r['role']}) = Member {anon_map[r['instance_id']]}" for r in reviewers
        ),
        f"**Pragmatist 来源**: " + ("外部 view (主调用方 Claude Code with memory)" if pragmatist_view else "fallback API"),
        f"**Research**: {research_model_cfg['name'] if research_model_cfg else '(skipped)'}",
        f"**Judge**: {judge_model_cfg['name']}",
        f"**配置**: rounds={args.rounds}, judge={'on' if args.with_judge else 'off'}, "
        f"early_stop={'off' if args.no_early_stop else 'on'}, max_cost=${args.max_cost:.2f}",
        f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    # === R0: Perplexity 联网调研 ===
    research_text = ""
    if research_model_cfg and not args.no_research:
        print(f"\n=== R0: 联网调研 ({research_model_cfg['name']}) ===", file=sys.stderr)
        output_lines.append("\n---\n## R0: 联网调研")
        research_text, research_cost = run_research(api_key, research_model_cfg, context, question)
        total_cost += research_cost
        if research_text:
            output_lines.append(f"\n### {research_model_cfg['name']} (${research_cost:.4f})\n")
            output_lines.append(research_text)
            print(f"  {research_model_cfg['name']}: OK ({len(research_text)} chars, ${research_cost:.4f})", file=sys.stderr)
        else:
            output_lines.append(f"\n_R0 research failed, continuing without augmented context_")
            print(f"  {research_model_cfg['name']}: FAILED, continuing without research", file=sys.stderr)

    # 在 R0 之后构造 user_content (含 research)
    user_content = build_user_prompt(context, question, research_text)

    histories = {
        r["instance_id"]: [
            {"role": "system", "content": role_prompt(r["role"], r.get("use_pua", False))},
            {"role": "user", "content": user_content},
        ]
        for r in reviewers
    }

    all_round_responses = []
    early_stopped = False
    cost_aborted = False

    for round_num in range(1, args.rounds + 1):
        print(f"\n=== Round {round_num}/{args.rounds} ===", file=sys.stderr)
        output_lines.append(f"\n---\n## Round {round_num}")

        # External Pragmatist (Claude Code with memory) 不调 API:
        # - R1: 直接用主调用方提供的 view 作为输出
        # - R2+: 立场作为 anchor 保持不变 (Pragmatist 来自主调用方, 不参与轮次演化)
        preset_results = {}
        runtime_reviewers = []
        for r in reviewers:
            if r.get("external_r1_content"):
                # External pragmatist, R1/R2 都不调 API
                content = r["external_r1_content"]
                if round_num > 1:
                    content = content + "\n\n_[Pragmatist 立场在本轮保持不变 — 由主调用方提供, 不参与轮次演化]_"
                preset_results[r["instance_id"]] = {
                    "ok": True,
                    "content": content,
                    "cost": 0.0,
                    "name": r["name"],
                    "role": r.get("role", ""),
                }
            else:
                runtime_reviewers.append(r)

        results = run_round_parallel(api_key, runtime_reviewers, histories) if runtime_reviewers else {}
        results.update(preset_results)

        round_responses = {}
        for r in reviewers:
            mid = r["instance_id"]
            res = results[mid]
            content = res.get("content") or ""
            # Treat ok=True but empty content as soft error (OpenRouter 偶发)
            if res.get("ok") and not content:
                res = {"ok": False, "error": "empty content from API (ok=True but content is None/empty)", "name": res.get("name"), "role": res.get("role")}

            if res["ok"]:
                summary = extract_summary(content)
                fallback_used = False
                # Fallback: 如果未在末尾附 JSON, 发轻量请求让同模型补提取
                if not summary:
                    print(f"  {res['name']}: summary missing, calling fallback extractor...", file=sys.stderr)
                    summary, fb_cost = summary_fallback_extract(api_key, r["id"], content, r.get("role", ""))
                    total_cost += fb_cost
                    if summary:
                        fallback_used = True

                round_responses[mid] = {
                    "name": res["name"], "role": res["role"],
                    "content": content, "cost": res.get("cost", 0),
                    "summary": summary,
                }
                total_cost += res.get("cost", 0)
                output_lines.append(
                    f"\n### {res['name']} | {res['role']} | Member {anon_map[mid]} "
                    f"(${res.get('cost', 0):.4f}{', +fallback' if fallback_used else ''})"
                )
                if round_num >= 2 and detect_sycophancy(content):
                    output_lines.append("_WARNING: sycophancy detected (output starts with agreement)_")
                if fallback_used:
                    output_lines.append("_INFO: summary extracted via fallback (model did not follow JSON protocol)_")
                elif not summary:
                    output_lines.append("_WARNING: failed to extract JSON summary even via fallback (R2 will not see this member's structured view)_")
                output_lines.append(content)
                print(
                    f"  {res['name']}: OK ({len(content)} chars, "
                    f"${res.get('cost', 0):.4f}, summary={'yes' if summary else 'NO'}"
                    f"{', fallback' if fallback_used else ''})",
                    file=sys.stderr,
                )
            else:
                round_responses[mid] = {
                    "name": res["name"], "role": res["role"],
                    "content": f"[ERROR: {res['error']}]", "cost": 0,
                    "summary": None,
                }
                output_lines.append(f"\n### {res['name']} | {res['role']} (ERROR)")
                output_lines.append(f"Error: {res['error']}")
                print(f"  {res['name']}: ERROR - {res['error']}", file=sys.stderr)

        all_round_responses.append((round_num, round_responses))

        if total_cost > args.max_cost:
            output_lines.append(f"\n**COST GUARD**: ${total_cost:.4f} > ${args.max_cost:.2f}, aborting")
            print(f"Cost guard triggered, aborting", file=sys.stderr)
            cost_aborted = True
            break

        # v1.0 结构化早停 (替代 v3 关键词匹配)
        if round_num == 1 and not args.no_early_stop and args.rounds >= 2:
            simple_responses = {mid: r["content"] for mid, r in round_responses.items()}
            is_consensus, signals = detect_structured_consensus(simple_responses)
            if is_consensus:
                output_lines.append(
                    f"\n_EARLY STOP: 全员 safe_to_stop=true + 0 blocking_issues "
                    f"(signals: {json.dumps(signals, ensure_ascii=False)})_"
                )
                print(f"Early stop triggered (structured consensus)", file=sys.stderr)
                early_stopped = True
                break

        # 准备 R2 history (真匿名化: 仅传 structured summary)
        if round_num < args.rounds:
            for r in reviewers:
                # External Pragmatist 不参与 R2+ history 构造 (R2 复用 R1 content 不调 API)
                if r.get("external_r1_content"):
                    continue
                mid = r["instance_id"]
                own = round_responses[mid]["content"]
                histories[mid].append({"role": "assistant", "content": own})

                other_summaries = {}
                for other_r in reviewers:
                    omid = other_r["instance_id"]
                    if omid == mid:
                        continue
                    other_summaries[anon_map[omid]] = round_responses[omid].get("summary")

                histories[mid].append({
                    "role": "user",
                    "content": build_round2_prompt(round_num, other_summaries, r["role"]),
                })

    # Judge round (DeepSeek 跨厂商, 看匿名化 transcript)
    judge_json = None
    if args.with_judge and not cost_aborted and total_cost < args.max_cost:
        print(f"\n=== Judge Round ({judge_model_cfg['name']}, 双盲) ===", file=sys.stderr)
        output_lines.append(f"\n---\n## Judge Round ({judge_model_cfg['name']}, 双盲)")

        # Build anonymized transcript: Judge sees role label + Member letter, NOT model name
        transcript_parts = []
        for round_num, resps in all_round_responses:
            for r in reviewers:
                mid = r["instance_id"]
                if mid not in resps:
                    continue
                resp = resps[mid]
                transcript_parts.append(
                    f"### Round {round_num} | Member {anon_map[mid]} | role={resp['role']}\n\n{resp['content']}"
                )
        transcript = "\n\n---\n\n".join(transcript_parts)

        judge_messages = [
            {"role": "system", "content": judge_prompt()},
            {"role": "user", "content":
                f"## 原始审查上下文\n\n{user_content}\n\n---\n\n"
                f"## 四方辩论记录 (匿名: Member A/B/C/D, 你看不到真实模型品牌)\n\n{transcript}\n\n---\n\n"
                f"请按 JSON schema 输出 summary + audit 双层综合结果。"},
        ]

        judge_result = call_openrouter(
            api_key, judge_model_cfg["id"], judge_messages,
            temperature=judge_model_cfg.get("temp", 0.1), timeout=300,
            max_tokens=JUDGE_MAX_TOKENS,
        )

        if judge_result["ok"]:
            total_cost += judge_result.get("cost", 0)
            output_lines.append(f"\n### {judge_model_cfg['name']} (${judge_result.get('cost', 0):.4f})")
            content = judge_result["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            try:
                judge_json = json.loads(content)
                output_lines.append("\n```json\n" + json.dumps(judge_json, ensure_ascii=False, indent=2) + "\n```")
            except json.JSONDecodeError as e:
                output_lines.append(f"\n_Judge output not valid JSON: {e}_\n\n```\n{content}\n```")
                judge_json = {"error": str(e), "raw_content": content}
        else:
            output_lines.append(f"\n### Judge ERROR\n\n{judge_result['error']}")
            print(f"Judge: ERROR - {judge_result['error']}", file=sys.stderr)

    output_lines.extend([
        "\n---",
        f"\n## 汇总",
        f"- **总成本**: ${total_cost:.4f}",
        f"- **Rounds executed**: {len(all_round_responses)}",
        f"- **Early stopped**: {'yes' if early_stopped else 'no'}",
        f"- **Cost aborted**: {'yes' if cost_aborted else 'no'}",
        f"- **Judge**: {'ran' if judge_json else 'skipped'}",
        "",
    ])

    output_text = "\n".join(output_lines)

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = Path.home() / "AppData" / "Local" / "Temp" / "cross_review_result.md"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output_text)

    if args.json_output and judge_json:
        json_path = Path(args.json_output)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(judge_json, f, ensure_ascii=False, indent=2)

    print(f"\nResult: {out_path}", file=sys.stderr)
    if args.json_output and judge_json:
        print(f"JSON:   {args.json_output}", file=sys.stderr)
    print(f"Total cost: ${total_cost:.4f}", file=sys.stderr)

    print(str(out_path))


if __name__ == "__main__":
    main()
