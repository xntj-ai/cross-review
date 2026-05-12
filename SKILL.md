---
name: cross-review
description: >
  多模型交叉审查：通过 OpenRouter 调用 Gemini 和 GPT 进行多轮辩论式设计审查。
  Use when: 用户要求多模型审查、跨模型讨论、设计决策校验、或"拉其他模型一起看"。
  适合架构决策、方案选型、设计审查等需要不同视角的场景。
  不适合：纯编码实现、简单事实查询、紧急 hotfix。
---

# /cross-review [topic]

多模型辩论式设计审查。通过 OpenRouter 调用其他模型族（Gemini、GPT），进行 2 轮讨论后综合决策。

## 核心原则

**对话 > 独白**：不是让每个模型单独出意见然后你来综合，而是让它们看到彼此的观点后进行回应和辩论。

## 执行流程

### Step 1: 准备上下文包

创建 JSON 文件 `~/AppData/Local/Temp/cross_review_prompt.json`：

```json
{
  "context": "完整上下文（现有系统、方法论、文件示例、调研发现、约束条件）",
  "question": "具体的审查问题（多个问题用编号列出）"
}
```

**上下文必须包含**（第一轮教训：缺上下文导致审查浮于表面）：

1. 现有系统/方法论（审查者需要知道什么已经在用）
2. 真实文件示例（不是抽象描述，是实际内容片段）
3. 行业调研发现（给审查者参照系，避免从零开始）
4. 约束条件（技术限制 + 用户偏好 + 运行环境）
5. 前轮审查共识（如果有，避免重复讨论已解决的问题）

### Step 2: 获取 OpenRouter API Key

查找顺序：

1. 环境变量 `OPENROUTER_API_KEY`
2. `~/.claude/settings.local.json` 的 mcpServers 的 env
3. 用户自己的密钥管理位置

### Step 3: 运行脚本

```bash
OPENROUTER_API_KEY="<key>" python ~/.claude/skills/cross-review/scripts/cross_review.py \
  ~/AppData/Local/Temp/cross_review_prompt.json \
  --rounds 2 \
  --output ~/AppData/Local/Temp/cross_review_result.md
```

参数：

- `--rounds N`：辩论轮次（默认 2，推荐 2，超过 3 边际收益极低）
- `--output <path>`：输出文件路径
- `--models <id1> <id2>`：自定义模型（默认 gemini-3.1-pro + gpt-5.2）

### Step 4: 读取结果并综合

用 Read 工具读取输出的 markdown 文件，然后：

1. 提取 **三方共识**（你 + 两个模型都同意 = 高置信度决策）
2. 标记 **分歧项**（需要用户判断）
3. 识别 **独特观点**（只有一个模型提出 = 可能是盲区也可能是噪声）
4. 给出 **最终建议**（结合共识 + 你自己的判断）

向用户呈现时用结构化表格，区分共识/分歧/独特观点。

## 模型选择指南

| 场景 | 推荐模型 |
|------|---------|
| 架构/系统设计 | gemini-3.1-pro + gpt-5.2（默认） |
| 前端/UI 设计 | gemini-3.1-pro + gpt-5.2 |
| 安全审查 | gpt-5.2 + o3（推理更强） |
| 成本敏感 | gemini-3-flash + gpt-5-mini |

## 注意事项

- **Windows 路径**：用 `~/AppData/Local/Temp/` 而非 `/tmp/`
- **编码**：脚本已处理 UTF-8，无需额外配置
- **成本**：典型 2 轮审查约 $0.10-0.20
- **时间**：2 轮约 2-3 分钟（受 API 延迟影响）
- **不要用于事实验证**：LLM 审查适合设计判断，不适合验证事实准确性（用 cross-reference 检查代替）
