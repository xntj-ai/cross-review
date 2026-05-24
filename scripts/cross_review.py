#!/usr/bin/env python3
"""
Cross-Review v2: 跨厂商对照审查 + 反附和设计 + 独立 judge

三个角色模型 (Promoter/Critic/Troublemaker) 通过 OpenRouter 并行审查，
跑 1-2 轮辩论 + 可选独立 judge 综合，输出结构化结果。

理论依据 (2025-2026 学术):
- Peacemaker (arxiv 2509.23055): 2-agent 易陷入 sycophancy collapse，3-agent 显著稳
- Free-MAD (arxiv 2509.11035): anti-conformity 单轮 + 综合，胜过共识 MAD
- DRIFTJudge (arxiv 2502.19559): 多轮辩论 35% 原地踏步，需要 early stop
- Self-Preference Bias (arxiv 2410.21819): 主模型自评有偏，需独立 judge

Usage:
    python cross_review.py <prompt.json> [--profile balanced|premium|cheap] [--rounds 2] \\
        [--with-judge|--no-judge] [--no-early-stop] [--max-cost 3.00] \\
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
JUDGE_MAX_TOKENS = 8000  # Judge schema (consensus/majority/individual/divergences/ledger/warnings/recommendation) 输出较长

# Strip inherited proxies, install local proxy for OpenRouter (CN access fallback)
for _k in list(os.environ.keys()):
    if 'proxy' in _k.lower():
        del os.environ[_k]
_proxy = os.environ.get("OPENROUTER_PROXY", "http://127.0.0.1:10808")
_proxy_handler = urllib.request.ProxyHandler({'http': _proxy, 'https': _proxy})
urllib.request.install_opener(urllib.request.build_opener(_proxy_handler))

# --- Model profiles ---
# Verified 2026-05-24 against OpenRouter API. See README for rationale.
PROFILES = {
    "cheap": [
        {"id": "google/gemini-3-flash-preview", "name": "Gemini 3 Flash", "role": "promoter", "temp": 0.3},
        {"id": "openai/gpt-5.4-mini",           "name": "GPT-5.4 Mini",    "role": "critic",       "temp": 0.3},
        {"id": "x-ai/grok-4.20",                "name": "Grok 4.20",       "role": "troublemaker", "temp": 0.7},
    ],
    "balanced": [
        {"id": "google/gemini-3.1-pro-preview", "name": "Gemini 3.1 Pro",  "role": "promoter",     "temp": 0.3},
        {"id": "openai/gpt-5.4",                "name": "GPT-5.4",         "role": "critic",       "temp": 0.3},
        {"id": "x-ai/grok-4.20",                "name": "Grok 4.20",       "role": "troublemaker", "temp": 0.7},
    ],
    "premium": [
        {"id": "google/gemini-3.1-pro-preview", "name": "Gemini 3.1 Pro",         "role": "promoter",     "temp": 0.3},
        {"id": "openai/gpt-5.5",                "name": "GPT-5.5",                "role": "critic",       "temp": 0.3},
        {"id": "x-ai/grok-4.20-multi-agent",    "name": "Grok 4.20 Multi-Agent",  "role": "troublemaker", "temp": 0.7},
    ],
}

JUDGE_MODEL = {
    "id": "google/gemini-3.1-pro-preview",
    "name": "Gemini 3.1 Pro (Judge)",
    "temp": 0.1,
}

DEFAULT_PROFILE = "premium"
DEFAULT_MAX_COST = 3.00


# --- Role-specific system prompts ---
def role_prompt(role: str) -> str:
    base = "你正在参与一场跨模型对照审查。用中文回复，直接专业，不客套。"

    if role == "promoter":
        return f"""{base}

你的角色: Promoter (建设性视角)
- 提出最优方案，给出可落地的建设性建议
- 评估方案优点、可行路径、实施步骤
- 引用上下文中具体片段说明你的依据
- 严禁: 故意找漏洞唱反调（那是 Troublemaker 的事）
- 必须: 给出具体可执行的建议，不只罗列原则
"""

    if role == "critic":
        return f"""{base}

你的角色: Critic (深度推理视角)
- 用严格逻辑识别方案问题
- 关注边界情况、failure mode、隐藏假设
- 必须: 引用上下文中具体片段（"context 第 X 段提到 Y，但..."）
- 必须: 区分"已知风险"和"未识别盲区"
- 必须: 给出每个问题的严重度评估 (high/medium/low)
"""

    if role == "troublemaker":
        return f"""{base}

你的角色: Troublemaker (反共识视角)
唯一任务: 找漏洞、唱反调。

强制约束:
1. 禁止以"我同意"或"很好的建议"开头
2. 必须列出 Promoter/Critic 未提及的 >=2 个风险或盲区
3. 每条反对必须引用对方原文片段（"Promoter 说 X，但 Y 情况下会..."）
4. 如果真的找不到反对意见，写: "经分析无法找到反对意见，可能原因: (a) 方案稳健 (b) 我的视角受限"
5. 不要客套，不要展开赞美
6. 优先质疑那些"显然正确"的隐藏假设
"""

    return base


def judge_prompt() -> str:
    return """你是独立 Judge，正在综合三个模型 (Promoter/Critic/Troublemaker) 的辩论输出。
你的任务不是再次审查方案，而是分类整理三方观点并给出结构化结论。

严格输出 JSON 格式，schema (对齐 Mozilla.ai Star Chamber 业界共识命名):

{
  "consensus_issues": [
    {"point": "三方 (3/3) 一致标记的观点（一句话）", "details": "支持细节、引用谁说过"}
  ],
  "majority_issues": [
    {
      "point": "多数 (2/3) 标记的观点（一句话）",
      "supporters": ["promoter", "critic"],
      "dissenter": "troublemaker (或 null 如果未明确反对)",
      "details": "为什么 2/3 同意、dissenter 立场"
    }
  ],
  "individual_observations": [
    {
      "source": "promoter|critic|troublemaker",
      "point": "单方 (1/3) 独有观点（一句话）",
      "merit": "high|medium|low",
      "merit_reason": "评级理由 (high = 关键盲区, medium = 有价值, low = 噪声或附和)"
    }
  ],
  "divergences": [
    {
      "topic": "分歧主题",
      "promoter": "立场摘要 (null 如果未提及)",
      "critic": "立场摘要",
      "troublemaker": "立场摘要",
      "judge_recommendation": "你认为哪方论据最强且为什么"
    }
  ],
  "ledger": [
    {
      "claim": "具体观点（一句话）",
      "raised_by": "promoter|critic|troublemaker",
      "raised_at_round": 1,
      "stance_evolution": "stable | revised in R2: <修正了什么> | abandoned in R2 | sycophantic shift",
      "judge_note": "你的归因评价 (可选)"
    }
  ],
  "warnings": [
    "可能的 sycophancy / 偏离原题 / drift / unanimous-bias (全员一致反而可疑) 等"
  ],
  "final_recommendation": "综合三方后的最终建议 (2-4 句，直接告诉用户该怎么做)"
}

约束:
- 只输出 JSON，不加任何外层文字
- 不要 markdown 代码块包裹
- 中文内容
- 分类规则: 3/3 提到 → consensus_issues; 2/3 → majority_issues; 1/3 → individual_observations
- ledger 控制在 6-10 条最关键 claims，每条 claim 一句话(≤40字)，stance_evolution 一句话(≤40字)
- consensus_issues / majority_issues / individual_observations 各项 details 控制在 60 字以内
- final_recommendation 严格 2-4 句
- 整体 JSON 输出预算 ≤ 5500 字 (避免截断)
- 如果某 individual_observation 仅是噪声或附和性补充，merit 标 "low"
- 警惕"全员一致"反而可疑 (correlated-bias warning): 三方都用相同措辞 + 无 dissent → 在 warnings 里标记
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

            # credentials.{service} layout (preferred, per ~/.claude/rules/security.md)
            for service, fields in data.get("credentials", {}).items():
                if not isinstance(fields, dict):
                    continue
                for k, v in fields.items():
                    if "OPENROUTER" in k.upper() and v:
                        return v

            # mcpServers env fallback
            for server in data.get("mcpServers", {}).values():
                for k, v in server.get("env", {}).items():
                    if "OPENROUTER" in k.upper() and v:
                        return v
        except Exception:
            pass

    print("ERROR: No OpenRouter API key found.", file=sys.stderr)
    print("Set OPENROUTER_API_KEY env var, or add to ~/.claude/settings.local.json credentials.openrouter", file=sys.stderr)
    sys.exit(1)


def call_openrouter(api_key, model_id, messages, temperature=0.3, timeout=240, max_tokens=None):
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


def run_round_parallel(api_key, models, messages_per_model):
    results = {}
    with ThreadPoolExecutor(max_workers=len(models)) as executor:
        futures = {}
        for model in models:
            msgs = messages_per_model[model["id"]]
            future = executor.submit(
                call_openrouter,
                api_key, model["id"], msgs, model.get("temp", 0.3),
            )
            futures[future] = model

        for future in as_completed(futures):
            model = futures[future]
            r = future.result()
            results[model["id"]] = {**r, "name": model["name"], "role": model.get("role", "")}
    return results


# --- Heuristics ---
def detect_r1_consensus(round_responses):
    """三方 R1 都倾向"无重大问题" 时触发 early stop。"""
    positive = [
        "无重大问题", "方案稳健", "整体合理", "无显著风险",
        "方案可行", "没有明显问题", "建议采纳", "支持当前方案",
        "no major issues", "looks solid", "reasonable approach",
    ]
    negative = [
        "重大风险", "严重问题", "强烈反对", "不建议",
        "重新设计", "存在缺陷", "不可行",
        "critical issue", "major concern", "strong objection",
    ]

    signals = []
    for mid, content in round_responses.items():
        if not content or content.startswith("[ERROR"):
            return False, [{"model": mid, "reason": "error"}]
        text = content.lower()[:2000]
        pos = sum(1 for s in positive if s.lower() in text)
        neg = sum(1 for s in negative if s.lower() in text)
        signals.append({"model": mid, "pos": pos, "neg": neg, "score": pos - neg})

    is_consensus = (
        all(s["score"] >= 1 for s in signals)
        and all(s["neg"] <= s["pos"] for s in signals)
    )
    return is_consensus, signals


def detect_sycophancy(text: str) -> bool:
    """R2 输出以纯附和开头算 sycophancy。"""
    starts = [
        "我同意", "完全同意", "很好的建议", "我赞同", "其他模型说得对",
        "i agree", "great point", "i fully agree",
    ]
    head = text.lower().strip()[:200]
    return any(head.startswith(s.lower()) for s in starts)


# --- Prompts builders ---
def build_user_prompt(context: str, question: str) -> str:
    return f"""## 审查上下文

{context}

---

## 审查问题

{question}
"""


def build_round2_prompt(round_num, other_models_responses, role, anon_map):
    """
    anon_map: {model_id: "Council Member X"} 用于在 R2 隐藏其他模型的品牌身份，
    防止"Gemini 偏向 Gemini 风格 / GPT 偏向 GPT 风格"的同源偏见 (LLM Council pattern).
    """
    others = []
    for omid, resp in other_models_responses.items():
        anon_name = anon_map.get(omid, "Council Member ?")
        others.append(f"### {anon_name} ({resp['role']}) Round {round_num} 观点\n\n{resp['content']}")
    peer = "\n\n---\n\n".join(others)

    if role == "troublemaker":
        role_clause = "\n\n**作为 Troublemaker, 禁止以附和开头。必须找出至少 2 个对方未识别的盲区，引用对方原文说明分歧。**"
    elif role == "critic":
        role_clause = "\n\n**作为 Critic, 用严格推理回应。如果对方论据有逻辑漏洞，明确指出。**"
    elif role == "promoter":
        role_clause = "\n\n**作为 Promoter, 承认 Troublemaker 找到的合理风险，但坚持给出可落地建设性方案。不要被批评带偏。**"
    else:
        role_clause = ""

    # 早期 agree 反向施压 (adversarial-spec pattern): 如果你想纯附和，禁止
    anti_rubber_stamp = (
        "\n\n**反 rubber-stamp 约束**: 如果你倾向于完全同意对方所有观点 (rubber-stamp), "
        "请在回答中明确: (a) 你阅读了对方的哪些具体段落 (b) 你的同意基于什么推理 "
        "(c) 你是否真的没有任何残留 concern (注意: '没有'本身需要解释为什么没有)。"
    )

    return f"""以下是 Council 其他成员在 Round {round_num} 的审查意见 (模型身份已匿名化以减少同源偏见):

{peer}

---

请回应:
1. 你同意对方哪些观点？引用具体片段
2. 你反对对方哪些观点？给出理由
3. 对方提到了什么是你 Round 1 未提及的？这些盲区你怎么看？
4. 你 Round 1 的立场需要修正吗？如果是，明确说明修正了什么、为什么
{role_clause}{anti_rubber_stamp}
"""


# --- Main pipeline ---
def main():
    parser = argparse.ArgumentParser(
        description="Cross-Review v2: 跨厂商对照审查 + 反附和 + 独立 judge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("prompt_file", help="JSON with {context, question}")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, choices=list(PROFILES.keys()),
                        help=f"Model combination profile (default: {DEFAULT_PROFILE})")
    parser.add_argument("--rounds", type=int, default=2,
                        help="Number of debate rounds (default: 2, max: 3)")
    parser.add_argument("--with-judge", action="store_true", default=True,
                        help="Add independent judge round (default: on)")
    parser.add_argument("--no-judge", dest="with_judge", action="store_false",
                        help="Skip judge round (rely on caller to synthesize)")
    parser.add_argument("--no-early-stop", action="store_true",
                        help="Disable R1 consensus early stop")
    parser.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST,
                        help=f"Max cost in USD before abort (default: {DEFAULT_MAX_COST})")
    parser.add_argument("--output", default=None, help="Markdown output path")
    parser.add_argument("--json-output", default=None, help="JSON output path (judge result)")
    parser.add_argument("--models", nargs="*",
                        help="Override profile with 3 custom model IDs (promoter/critic/troublemaker order)")
    args = parser.parse_args()

    # Load prompt
    with open(args.prompt_file, encoding="utf-8") as f:
        prompt_data = json.load(f)

    context = prompt_data.get("context", "")
    question = prompt_data.get("question", "")
    user_content = build_user_prompt(context, question)

    # Resolve models
    if args.models:
        roles = ["promoter", "critic", "troublemaker"]
        temps = [0.3, 0.3, 0.7]
        models = []
        for i, m in enumerate(args.models[:3]):
            models.append({
                "id": m, "name": m.split("/")[-1],
                "role": roles[i] if i < 3 else "critic",
                "temp": temps[i] if i < 3 else 0.3,
            })
    else:
        models = PROFILES[args.profile]

    api_key = get_api_key()
    total_cost = 0.0

    # Anonymization map for R2 (LLM Council pattern): hide brand identity to reduce same-vendor bias
    anon_letters = ["A", "B", "C", "D", "E"]
    anon_map = {m["id"]: f"Council Member {anon_letters[i]}" for i, m in enumerate(models)}

    output_lines = [
        "# Cross-Review v3 报告",
        f"\n**Profile**: {'custom' if args.models else args.profile}",
        f"**模型 (R2 匿名映射)**: " + ", ".join(
            f"{m['name']} ({m['role']}) = {anon_map[m['id']]}" for m in models
        ),
        f"**配置**: rounds={args.rounds}, judge={'on' if args.with_judge else 'off'}, "
        f"early_stop={'off' if args.no_early_stop else 'on'}, max_cost=${args.max_cost:.2f}",
        f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    # Init histories per model (role-specific system prompt)
    histories = {
        m["id"]: [
            {"role": "system", "content": role_prompt(m["role"])},
            {"role": "user", "content": user_content},
        ]
        for m in models
    }

    all_round_responses = []
    early_stopped = False
    cost_aborted = False

    for round_num in range(1, args.rounds + 1):
        print(f"\n=== Round {round_num}/{args.rounds} ===", file=sys.stderr)
        output_lines.append(f"\n---\n## Round {round_num}")

        results = run_round_parallel(api_key, models, histories)

        round_responses = {}
        for model in models:
            mid = model["id"]
            r = results[mid]
            if r["ok"]:
                round_responses[mid] = {
                    "name": r["name"], "role": r["role"],
                    "content": r["content"], "cost": r.get("cost", 0),
                }
                total_cost += r.get("cost", 0)
                output_lines.append(f"\n### {r['name']} | {r['role']} (${r.get('cost', 0):.4f})")
                if round_num >= 2 and detect_sycophancy(r["content"]):
                    output_lines.append("_WARNING: sycophancy detected (output starts with agreement)_")
                output_lines.append(r["content"])
                print(f"  {r['name']}: OK ({len(r['content'])} chars, ${r.get('cost', 0):.4f})", file=sys.stderr)
            else:
                round_responses[mid] = {
                    "name": r["name"], "role": r["role"],
                    "content": f"[ERROR: {r['error']}]", "cost": 0,
                }
                output_lines.append(f"\n### {r['name']} | {r['role']} (ERROR)")
                output_lines.append(f"Error: {r['error']}")
                print(f"  {r['name']}: ERROR - {r['error']}", file=sys.stderr)

        all_round_responses.append((round_num, round_responses))

        if total_cost > args.max_cost:
            output_lines.append(f"\n**COST GUARD**: ${total_cost:.4f} > ${args.max_cost:.2f}, aborting")
            print(f"Cost guard triggered, aborting", file=sys.stderr)
            cost_aborted = True
            break

        # R1 consensus early stop
        if round_num == 1 and not args.no_early_stop and args.rounds >= 2:
            simple = {mid: r["content"] for mid, r in round_responses.items()}
            is_consensus, signals = detect_r1_consensus(simple)
            if is_consensus:
                output_lines.append(
                    f"\n_EARLY STOP: R1 consensus detected (signals: {json.dumps(signals, ensure_ascii=False)})_"
                )
                print(f"Early stop triggered (R1 consensus)", file=sys.stderr)
                early_stopped = True
                break

        # Prepare next round history
        if round_num < args.rounds:
            for model in models:
                mid = model["id"]
                own = round_responses[mid]["content"]
                histories[mid].append({"role": "assistant", "content": own})
                others = {omid: r for omid, r in round_responses.items() if omid != mid}
                histories[mid].append({
                    "role": "user",
                    "content": build_round2_prompt(round_num, others, model["role"], anon_map),
                })

    # Judge round
    judge_json = None
    if args.with_judge and not cost_aborted and total_cost < args.max_cost:
        print(f"\n=== Judge Round ===", file=sys.stderr)
        output_lines.append(f"\n---\n## Judge Round (独立综合)")

        transcript_parts = []
        for round_num, resps in all_round_responses:
            for mid, r in resps.items():
                transcript_parts.append(f"### Round {round_num} | {r['name']} ({r['role']})\n\n{r['content']}")
        transcript = "\n\n---\n\n".join(transcript_parts)

        judge_messages = [
            {"role": "system", "content": judge_prompt()},
            {"role": "user", "content":
                f"## 原始审查上下文\n\n{user_content}\n\n---\n\n"
                f"## 三方辩论记录\n\n{transcript}\n\n---\n\n"
                f"请按 JSON schema 输出综合结果，只输出 JSON 本体。"},
        ]

        judge_result = call_openrouter(
            api_key, JUDGE_MODEL["id"], judge_messages,
            temperature=JUDGE_MODEL.get("temp", 0.1), timeout=300,
            max_tokens=JUDGE_MAX_TOKENS,
        )

        if judge_result["ok"]:
            total_cost += judge_result.get("cost", 0)
            output_lines.append(f"\n### {JUDGE_MODEL['name']} (${judge_result.get('cost', 0):.4f})")
            content = judge_result["content"].strip()
            # Strip code fences in case judge ignored instruction
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
