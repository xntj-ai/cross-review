#!/usr/bin/env python3
"""
Cross-Review: Multi-model debate for design decisions.
Calls multiple LLMs via OpenRouter, runs multi-round discussion.

Usage:
    python cross_review.py <prompt_file> [--rounds 2] [--output <path>]

prompt_file: JSON with {"context": "...", "question": "..."}
Output: Markdown file with structured debate results.
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import urllib.request
import urllib.error

# --- Config ---
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

# Setup proxy: clear inherited env proxies, use local proxy if available
for _k in list(os.environ.keys()):
    if 'proxy' in _k.lower():
        del os.environ[_k]
_proxy = os.environ.get("OPENROUTER_PROXY", "http://127.0.0.1:10808")
_proxy_handler = urllib.request.ProxyHandler({'http': _proxy, 'https': _proxy})
_opener = urllib.request.build_opener(_proxy_handler)
urllib.request.install_opener(_opener)
DEFAULT_MODELS = [
    {"id": "google/gemini-3.1-pro-preview", "name": "Gemini 3.1 Pro"},
    {"id": "openai/gpt-5.2", "name": "GPT-5.2"},
]
MAX_TOKENS = 4000
TEMPERATURE = 0.3

def get_api_key():
    """Get OpenRouter API key from environment or known locations."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key

    # Try reading from local config
    settings_path = Path.home() / ".claude" / "settings.local.json"
    if settings_path.exists():
        try:
            with open(settings_path, encoding="utf-8") as f:
                data = json.load(f)
            for server in data.get("mcpServers", {}).values():
                for k, v in server.get("env", {}).items():
                    if "OPENROUTER" in k.upper():
                        return v
        except Exception:
            pass

    print("ERROR: No OpenRouter API key found.", file=sys.stderr)
    print("Set OPENROUTER_API_KEY env var or add to settings.local.json", file=sys.stderr)
    sys.exit(1)


def call_openrouter(api_key, model_id, messages):
    """Make a single API call to OpenRouter."""
    payload = json.dumps({
        "model": model_id,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
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
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if "choices" in data:
            content = data["choices"][0]["message"]["content"]
            cost = data.get("usage", {}).get("cost", 0)
            return {"ok": True, "content": content, "cost": cost}
        elif "error" in data:
            return {"ok": False, "error": json.dumps(data["error"], ensure_ascii=False)}
        else:
            return {"ok": False, "error": f"Unexpected response: {list(data.keys())}"}
    except urllib.error.URLError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def run_round(api_key, models, messages_per_model):
    """Run one round of parallel API calls."""
    results = {}
    with ThreadPoolExecutor(max_workers=len(models)) as executor:
        futures = {}
        for model in models:
            msgs = messages_per_model[model["id"]]
            future = executor.submit(call_openrouter, api_key, model["id"], msgs)
            futures[future] = model

        for future in as_completed(futures):
            model = futures[future]
            result = future.result()
            results[model["id"]] = {
                "name": model["name"],
                **result,
            }
    return results


def build_system_prompt():
    return (
        "你是一名资深系统架构师，正在参与一场多模型设计审查讨论。"
        "请直接指出问题、提出改进、补充盲区。不要客套。用中文回复。"
        "如果你看到了其他模型的观点，请明确表态：同意/反对/补充，并说明理由。"
    )


def main():
    parser = argparse.ArgumentParser(description="Multi-model cross-review via OpenRouter")
    parser.add_argument("prompt_file", help="JSON file with context and question")
    parser.add_argument("--rounds", type=int, default=2, help="Number of debate rounds (default: 2)")
    parser.add_argument("--output", default=None, help="Output markdown file path")
    parser.add_argument("--models", nargs="*", help="Model IDs to use (default: gemini + gpt)")
    args = parser.parse_args()

    # Load prompt
    with open(args.prompt_file, encoding="utf-8") as f:
        prompt_data = json.load(f)

    context = prompt_data.get("context", "")
    question = prompt_data.get("question", "")
    user_content = f"{context}\n\n---\n\n## 审查问题\n{question}"

    # Setup models
    if args.models:
        models = [{"id": m, "name": m.split("/")[-1]} for m in args.models]
    else:
        models = DEFAULT_MODELS

    api_key = get_api_key()
    system_msg = {"role": "system", "content": build_system_prompt()}
    total_cost = 0.0

    # Output buffer
    output_lines = [
        "# Cross-Review 多模型交叉审查报告",
        f"\n**模型**: {', '.join(m['name'] for m in models)}",
        f"**轮次**: {args.rounds}",
        f"**时间**: {time.strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    # Track conversation history per model
    histories = {m["id"]: [system_msg, {"role": "user", "content": user_content}] for m in models}

    for round_num in range(1, args.rounds + 1):
        print(f"\n=== Round {round_num}/{args.rounds} ===", file=sys.stderr)
        output_lines.append(f"\n---\n## Round {round_num}")

        # Run parallel calls
        results = run_round(api_key, models, histories)

        # Collect responses
        round_responses = {}
        for model in models:
            mid = model["id"]
            r = results[mid]
            if r["ok"]:
                round_responses[mid] = r["content"]
                total_cost += r.get("cost", 0)
                output_lines.append(f"\n### {r['name']} (${r.get('cost', 0):.4f})")
                output_lines.append(r["content"])
                print(f"  {r['name']}: OK ({len(r['content'])} chars, ${r.get('cost', 0):.4f})", file=sys.stderr)
            else:
                round_responses[mid] = f"[ERROR: {r['error']}]"
                output_lines.append(f"\n### {r['name']} (ERROR)")
                output_lines.append(f"Error: {r['error']}")
                print(f"  {r['name']}: ERROR - {r['error']}", file=sys.stderr)

        # Prepare next round: each model sees all other models' responses
        if round_num < args.rounds:
            for model in models:
                mid = model["id"]
                # Add this model's own response as assistant
                histories[mid].append({"role": "assistant", "content": round_responses.get(mid, "")})

                # Build summary of other models' responses
                others = []
                for other_model in models:
                    omid = other_model["id"]
                    if omid != mid:
                        others.append(f"**{results[omid]['name']}** 的观点：\n{round_responses.get(omid, '[无响应]')}")

                peer_summary = "\n\n---\n\n".join(others)
                next_prompt = (
                    f"以下是其他模型在 Round {round_num} 的审查意见：\n\n{peer_summary}\n\n"
                    f"请回应：你同意哪些？反对哪些？有什么补充？"
                    f"特别关注对方提到而你没提到的盲区。"
                )
                histories[mid].append({"role": "user", "content": next_prompt})

    # Summary
    output_lines.extend([
        "\n---",
        f"\n## 成本汇总",
        f"**总计**: ${total_cost:.4f}",
        "",
    ])

    output_text = "\n".join(output_lines)

    # Write output
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = Path.home() / "AppData" / "Local" / "Temp" / "cross_review_result.md"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output_text)

    print(f"\nResult written to: {out_path}", file=sys.stderr)
    print(f"Total cost: ${total_cost:.4f}", file=sys.stderr)

    # Also print to stdout for Claude to capture
    print(str(out_path))


if __name__ == "__main__":
    main()
