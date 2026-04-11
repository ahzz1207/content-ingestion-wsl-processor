"""Tests for visual summary card generation."""
from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from content_ingestion.pipeline.visual_summary import (
    _build_visual_prompt,
    _extract_content_brief,
    _extract_image_bytes,
    _mode_style_directive,
    _system_prompt,
    generate_visual_summary,
)


def _make_editorial_base(
    core_summary="核心摘要",
    bottom_line="底线判断",
    audience_fit="适合人群",
    save_worthy_points=None,
):
    return SimpleNamespace(
        core_summary=core_summary,
        bottom_line=bottom_line,
        audience_fit=audience_fit,
        save_worthy_points=save_worthy_points or ["要点1"],
    )


def _make_editorial(mode, mode_payload, base=None):
    return SimpleNamespace(
        resolved_mode=mode,
        base=base or _make_editorial_base(),
        mode_payload=mode_payload,
    )


def _make_result(editorial=None, product_view=None, summary=None, key_points=None):
    return SimpleNamespace(
        editorial=editorial,
        product_view=product_view,
        summary=summary,
        key_points=key_points or [],
    )


class TestBuildVisualPrompt:
    def test_argument_prompt_contains_thesis(self):
        editorial = _make_editorial("argument", {
            "author_thesis": "核心论点在这里",
            "evidence_backed_points": [
                {"title": "证据1", "details": "细节1"},
            ],
        })
        result = _make_result(editorial=editorial)
        prompt = _build_visual_prompt(result, "argument", "测试文章标题")

        assert "测试文章标题" in prompt
        assert "核心论点在这里" in prompt
        assert "证据1" in prompt
        assert "分析简报" in prompt

    def test_guide_prompt_contains_steps(self):
        editorial = _make_editorial("guide", {
            "guide_goal": "学会X技能",
            "recommended_steps": ["第一步", "第二步", "第三步"],
            "tips": ["技巧A"],
            "pitfalls": ["陷阱A"],
        })
        result = _make_result(editorial=editorial)
        prompt = _build_visual_prompt(result, "guide", "指南文章")

        assert "学会X技能" in prompt
        assert "第一步" in prompt
        assert "技巧A" in prompt
        assert "陷阱A" in prompt
        assert "行动指南" in prompt

    def test_review_prompt_contains_highlights(self):
        editorial = _make_editorial("review", {
            "overall_judgment": "非常推荐",
            "highlights": ["亮点1", "亮点2"],
            "reservation_points": ["保留意见1"],
            "who_it_is_for": "适合新手",
        })
        result = _make_result(editorial=editorial)
        prompt = _build_visual_prompt(result, "review", "评测文章")

        assert "非常推荐" in prompt
        assert "亮点1" in prompt
        assert "保留意见1" in prompt
        assert "适合新手" in prompt
        assert "评鉴推荐" in prompt

    def test_fallback_to_product_view(self):
        product_view = {
            "hero": {"title": "PV标题", "dek": "描述", "bottom_line": "底线"},
            "sections": [
                {
                    "kind": "question_block",
                    "title": "核心问题？",
                    "blocks": [{"type": "paragraph", "text": "段落内容"}],
                },
            ],
        }
        result = _make_result(product_view=product_view)
        prompt = _build_visual_prompt(result, "argument", "标题")

        assert "PV标题" in prompt
        assert "段落内容" in prompt


class TestExtractImageBytes:
    def test_extracts_base64_image(self):
        raw_bytes = b"PNG_IMAGE_DATA_HERE"
        b64 = base64.b64encode(raw_bytes).decode()
        item = SimpleNamespace(type="image_generation_call", result=b64)
        response = SimpleNamespace(output=[item])

        extracted = _extract_image_bytes(response)
        assert extracted == raw_bytes

    def test_returns_none_when_no_image(self):
        item = SimpleNamespace(type="message", content="text only")
        response = SimpleNamespace(output=[item])

        assert _extract_image_bytes(response) is None

    def test_returns_none_for_empty_output(self):
        response = SimpleNamespace(output=[])
        assert _extract_image_bytes(response) is None


class TestGenerateVisualSummary:
    def test_writes_png_on_success(self, tmp_path):
        raw_bytes = b"\x89PNG_TEST_DATA"
        b64 = base64.b64encode(raw_bytes).decode()
        image_item = SimpleNamespace(type="image_generation_call", result=b64)
        mock_response = SimpleNamespace(output=[image_item])

        client = MagicMock()
        client.responses.create.return_value = mock_response

        editorial = _make_editorial("argument", {"author_thesis": "论点"})
        result = _make_result(editorial=editorial)
        output = tmp_path / "analysis" / "insight_card.png"

        step = generate_visual_summary(
            client=client,
            model="test-model",
            structured_result=result,
            resolved_mode="argument",
            asset_title="测试标题",
            output_path=output,
        )

        assert step["status"] == "success"
        assert step["name"] == "visual_summary_card"
        assert output.exists()
        assert output.read_bytes() == raw_bytes
        client.responses.create.assert_called_once()

    def test_returns_skipped_when_no_image(self, tmp_path):
        text_item = SimpleNamespace(type="message", content="no image")
        mock_response = SimpleNamespace(output=[text_item])

        client = MagicMock()
        client.responses.create.return_value = mock_response

        result = _make_result(editorial=_make_editorial("argument", {}))
        output = tmp_path / "insight_card.png"

        step = generate_visual_summary(
            client=client,
            model="test-model",
            structured_result=result,
            resolved_mode="argument",
            asset_title="标题",
            output_path=output,
        )

        assert step["status"] == "skipped"
        assert not output.exists()


class TestModeStyleDirective:
    def test_argument_mode(self):
        directive = _mode_style_directive("argument")
        assert "分析简报" in directive

    def test_guide_mode(self):
        directive = _mode_style_directive("guide")
        assert "行动指南" in directive

    def test_review_mode(self):
        directive = _mode_style_directive("review")
        assert "评鉴推荐" in directive

    def test_unknown_mode_falls_back(self):
        directive = _mode_style_directive("unknown")
        assert "分析简报" in directive


class TestSystemPrompt:
    def test_contains_key_instructions(self):
        sp = _system_prompt()
        assert "信息设计师" in sp
        assert "1024×1536" in sp
        assert "中文" in sp
