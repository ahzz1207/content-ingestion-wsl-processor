"""Visual summary card generation — produces a single insight card image.

Calls the Google GenAI SDK (via Zenmux Vertex AI endpoint) to generate a
visual summary of the analysis result. The card style adapts to the resolved
analysis mode (argument / guide / review).
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from content_ingestion.core.models import StructuredResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_visual_summary(
    *,
    client,
    model: str,
    structured_result: "StructuredResult",
    resolved_mode: str,
    asset_title: str,
    output_path: Path,
) -> dict[str, object]:
    """Generate an insight card image and write it to *output_path*.

    *client* must be a ``google.genai.Client`` instance configured with
    the Zenmux Vertex AI endpoint.

    Returns a pipeline step dict suitable for ``result.steps``.
    """
    from google.genai import types

    prompt = _build_visual_prompt(structured_result, resolved_mode, asset_title)

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )

    image_data = _extract_image_bytes(response)
    if image_data is None:
        return {
            "name": "visual_summary_card",
            "status": "skipped",
            "details": "model returned no image output",
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_data)

    return {
        "name": "visual_summary_card",
        "status": "success",
        "details": model,
        "image_size_bytes": len(image_data),
        "output_path": str(output_path),
    }


def _extract_image_bytes(response) -> bytes | None:
    """Walk the GenAI response parts looking for inline image data."""
    try:
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                data = part.inline_data.data
                if isinstance(data, bytes):
                    return data
                return base64.b64decode(data)
    except (AttributeError, IndexError):
        pass
    return None


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _build_visual_prompt(
    result: "StructuredResult",
    resolved_mode: str,
    asset_title: str,
) -> str:
    """Assemble the full prompt for image generation."""
    system = _system_prompt()
    content = _extract_content_brief(result, asset_title)
    style = _mode_style_directive(resolved_mode)
    return f"{system}\n\n---\n\n{style}\n\n---\n\n{content}"


def _system_prompt() -> str:
    return """你是一位顶尖的信息设计师。你的任务是将一篇文章的分析摘要转化为一张精美的信息卡片。

## 核心原则

1. **一眼可读**：读者应在 5 秒内抓住核心信息
2. **信息密度高**：每个视觉元素都承载信息，没有纯装饰
3. **排版精致**：专业杂志级别的视觉品质
4. **中文优先**：所有文字内容使用中文

## 图片规格

- 尺寸：1024×1536（竖版，适合手机阅读）
- 背景：使用深色或渐变背景，确保文字可读性
- 字体风格：现代无衬线，标题大而醒目
- 色彩：根据内容情绪选择主色调，保持克制（2-3 种主色）

## 排版结构

从上到下分为以下区域：

1. **标题区**（顶部 15%）：文章标题或核心论点，字号最大
2. **核心摘要区**（20%）：一句话总结 + 底线判断，用视觉分隔突出
3. **要点区**（50%）：3-5 个关键要点，每个配图标或编号，简洁有力
4. **底部落地区**（15%）：对读者的实际意义 / 行动建议

## 文字规范

- 标题：不超过 20 字
- 每个要点：不超过 30 字
- 总文字量：控制在 150 字以内
- 避免长句，用短语和关键词
- 可以使用 → ▸ ● ○ ■ 等符号增强层次感"""


def _mode_style_directive(resolved_mode: str) -> str:
    directives = {
        "argument": """## 视觉风格：分析简报

这是一篇深度分析内容。卡片应呈现"结论先行，证据支撑"的信息结构。

- 顶部用最醒目的方式展示核心判断/论点
- 中间用 2-3 个证据要点支撑，每个要点带编号
- 如有分歧或争议，用对比色标注
- 底部给出"这对我意味着什么"的落地判断
- 整体色调：冷静理性，深蓝/深灰为主，重点用亮色（橙/金）提亮
- 视觉隐喻：像一份精心排版的分析师简报""",

        "guide": """## 视觉风格：行动指南

这是一篇实用教程/指南内容。卡片应呈现"跟着做"的行动流程。

- 顶部展示目标（"你将学会 / 你能做到"）
- 中间用步骤流（Step 1 → Step 2 → Step 3）展示核心流程
- 可以用箭头、连接线表示步骤之间的关系
- 如有实用技巧，用 💡 或特殊区块突出
- 如有常见陷阱，用 ⚠️ 或警示色标注
- 底部给出"今天就可以开始做的一件事"
- 整体色调：明亮积极，绿色/青色为主色
- 视觉隐喻：像一张清晰的操作流程图""",

        "review": """## 视觉风格：评鉴推荐

这是一篇评测/推荐内容。卡片应呈现"值不值得"的判断。

- 顶部展示总体评价（一句判断）
- 中间分为"亮点"和"保留意见"两个区块，视觉上形成对比
- 亮点用积极色（绿/金），保留意见用中性色（灰/淡橙）
- 如有"适合什么人"的信息，用特殊排版突出
- 底部是推荐判断
- 整体色调：温暖有品味，暗金/酒红为主色
- 视觉隐喻：像一张精致的编辑推荐卡""",
    }
    return directives.get(resolved_mode, directives["argument"])


def _extract_content_brief(result: "StructuredResult", asset_title: str) -> str:
    """Extract a concise text brief from the structured result for the image prompt."""
    lines: list[str] = []

    lines.append(f"## 文章标题\n{asset_title or '（无标题）'}")

    if result.editorial is not None:
        base = result.editorial.base
        lines.append(f"\n## 核心摘要\n{base.core_summary}")
        lines.append(f"\n## 底线判断\n{base.bottom_line}")
        if base.audience_fit:
            lines.append(f"\n## 适合人群\n{base.audience_fit}")
        if base.save_worthy_points:
            points = "\n".join(f"- {p}" for p in base.save_worthy_points[:5])
            lines.append(f"\n## 值得记住的要点\n{points}")

        mp = result.editorial.mode_payload
        mode = result.editorial.resolved_mode

        if mode == "argument":
            if mp.get("author_thesis"):
                lines.append(f"\n## 作者论点\n{mp['author_thesis']}")
            ebp = mp.get("evidence_backed_points", [])
            if ebp:
                items = "\n".join(
                    f"- {p['title']}：{p.get('details', '')}"
                    for p in ebp[:3] if isinstance(p, dict) and p.get("title")
                )
                lines.append(f"\n## 证据支撑\n{items}")

        elif mode == "guide":
            if mp.get("guide_goal"):
                lines.append(f"\n## 目标\n{mp['guide_goal']}")
            steps = mp.get("recommended_steps", [])
            if steps:
                items = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps[:5]))
                lines.append(f"\n## 推荐步骤\n{items}")
            tips = mp.get("tips", [])
            if tips:
                items = "\n".join(f"- {t}" for t in tips[:3])
                lines.append(f"\n## 实用技巧\n{items}")
            pitfalls = mp.get("pitfalls", [])
            if pitfalls:
                items = "\n".join(f"- {p}" for p in pitfalls[:3])
                lines.append(f"\n## 常见陷阱\n{items}")

        elif mode == "review":
            if mp.get("overall_judgment"):
                lines.append(f"\n## 总体评价\n{mp['overall_judgment']}")
            highlights = mp.get("highlights", [])
            if highlights:
                items = "\n".join(f"- {h}" for h in highlights[:3])
                lines.append(f"\n## 亮点\n{items}")
            reservations = mp.get("reservation_points", [])
            if reservations:
                items = "\n".join(f"- {r}" for r in reservations[:3])
                lines.append(f"\n## 保留意见\n{items}")
            if mp.get("who_it_is_for"):
                lines.append(f"\n## 适合人群\n{mp['who_it_is_for']}")

    elif result.product_view is not None:
        pv = result.product_view
        hero = pv.get("hero", {})
        lines.append(f"\n## 核心摘要\n{hero.get('title', '')}")
        lines.append(f"\n## 底线判断\n{hero.get('bottom_line', '')}")
        for section in pv.get("sections", [])[:5]:
            title = section.get("title", "")
            blocks = section.get("blocks", [])
            text_parts = []
            for block in blocks:
                if block.get("type") == "paragraph":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") in ("bullet_list", "step_list"):
                    text_parts.extend(block.get("items", [])[:3])
            if text_parts:
                lines.append(f"\n## {title}\n" + "\n".join(f"- {t}" for t in text_parts))

    else:
        if result.summary and result.summary.short_text:
            lines.append(f"\n## 摘要\n{result.summary.short_text}")
        if result.key_points:
            items = "\n".join(f"- {kp.title}" for kp in result.key_points[:5])
            lines.append(f"\n## 关键要点\n{items}")

    lines.append("\n---\n请根据以上内容生成一张信息卡片。")
    return "\n".join(lines)
