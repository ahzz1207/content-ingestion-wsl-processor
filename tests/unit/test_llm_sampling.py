import pytest
from content_ingestion.core.models import ContentBlock, EvidenceSegment
from content_ingestion.pipeline.llm_contract import (
    _select_blocks_within_budget,
    _select_evidence_within_budget,
)


def _make_block(id: str, kind: str = "paragraph", text: str = "") -> ContentBlock:
    return ContentBlock(id=id, kind=kind, text=text or ("x" * 100))


def _make_segment(id: str, text: str = "") -> EvidenceSegment:
    return EvidenceSegment(id=id, kind="text_block", text=text or ("x" * 50), source="paragraph-1")


def test_select_blocks_no_truncation_when_under_budget() -> None:
    blocks = [_make_block(f"b{i}") for i in range(5)]
    selected, truncated, trimmed = _select_blocks_within_budget(blocks, max_chars=10_000)
    assert selected == blocks
    assert truncated is False
    assert trimmed == 0


def test_select_blocks_headings_always_kept() -> None:
    blocks = [_make_block("h1", kind="heading", text="h" * 100)] + [
        _make_block(f"p{i}", text="x" * 100) for i in range(50)
    ]
    # Budget only enough for a few blocks
    selected, truncated, _ = _select_blocks_within_budget(blocks, max_chars=500)
    assert truncated is True
    assert any(b.id == "h1" for b in selected)


def test_select_blocks_quotes_kept_over_paragraphs() -> None:
    # Mix of quotes and paragraphs, all same length (100 chars each).
    # Strict budget (600): hp_budget = 35% of 600 = 210, so 2 quotes fit (200 chars).
    # Quote coverage should be higher than same-sized paragraphs.
    blocks = [_make_block(f"q{i}", kind="quote", text="q" * 100) for i in range(3)]
    blocks += [_make_block(f"p{i}", text="p" * 100) for i in range(20)]
    selected, truncated, _ = _select_blocks_within_budget(blocks, max_chars=600)
    assert truncated is True
    selected_ids = {b.id for b in selected}
    # At least 2 of 3 quotes selected (higher priority than equal-sized paragraphs)
    quote_ids_selected = {"q0", "q1", "q2"} & selected_ids
    assert len(quote_ids_selected) >= 2
    # Total selected chars must not exceed max_chars (strict budget)
    total_selected_chars = sum(len(b.text) for b in selected)
    assert total_selected_chars <= 600

def test_select_blocks_strict_budget_with_many_headings() -> None:
    # Many headings that together approach the budget
    blocks = [_make_block(f"h{i}", kind="heading", text="h" * 50) for i in range(10)]
    blocks += [_make_block(f"p{i}", text="x" * 200) for i in range(20)]
    max_chars = 600
    selected, truncated, _ = _select_blocks_within_budget(blocks, max_chars=max_chars)
    assert truncated is True
    total = sum(len(b.text) for b in selected)
    # Strict budget check
    assert total <= max_chars
    # All headings (500 chars) fit within budget
    heading_ids = {b.id for b in selected if b.kind == "heading"}
    assert len(heading_ids) == 10


def test_select_blocks_includes_first_and_last_paragraph() -> None:
    blocks = [_make_block(f"p{i}", text="x" * 200) for i in range(20)]
    selected, truncated, _ = _select_blocks_within_budget(blocks, max_chars=1_000)
    assert truncated is True
    selected_ids = {b.id for b in selected}
    assert "p0" in selected_ids
    assert "p19" in selected_ids


def test_select_evidence_no_truncation_when_under_limit() -> None:
    segs = [_make_segment(f"s{i}") for i in range(10)]
    result = _select_evidence_within_budget(segs, max_count=100)
    assert result == segs


def test_select_evidence_covers_start_middle_end() -> None:
    segs = [_make_segment(f"s{i:03d}") for i in range(90)]
    result = _select_evidence_within_budget(segs, max_count=30)
    result_ids = [s.id for s in result]
    # Should have some from the start, middle, and end
    assert "s000" in result_ids  # first
    assert "s089" in result_ids  # last
    # At least one from the middle range (s030-s059)
    middle_ids = {f"s{i:03d}" for i in range(30, 60)}
    assert any(sid in middle_ids for sid in result_ids)

def test_select_blocks_strict_budget_not_exceeded_dense_headings_quotes() -> None:
    blocks = (
        [_make_block(f'h{i}', kind='heading', text='h' * 80) for i in range(5)]
        + [_make_block(f'q{i}', kind='quote', text='q' * 200) for i in range(10)]
        + [_make_block(f'p{i}', text='x' * 100) for i in range(20)]
    )
    max_chars = 1_000
    selected, truncated, _ = _select_blocks_within_budget(blocks, max_chars=max_chars)
    assert truncated is True
    total = sum(len(b.text) for b in selected)
    assert total <= max_chars, f'budget exceeded: {total} > {max_chars}'
    assert all(any(b.id == f'h{i}' for b in selected) for i in range(5))


def test_transcript_truncated_flag_in_reader_envelope(monkeypatch) -> None:
    from content_ingestion.core.config import load_settings
    from content_ingestion.core.models import ContentAsset
    from content_ingestion.pipeline.llm_contract import build_reader_envelope

    monkeypatch.setenv('OPENAI_API_KEY', 'sk-test')
    monkeypatch.setenv('CONTENT_INGESTION_LLM_MAX_CONTENT_CHARS', '100')
    settings = load_settings()

    short_asset = ContentAsset(
        source_platform='bilibili',
        source_url='https://example.com/v',
        title='T',
        transcript_text='short',
    )
    long_asset = ContentAsset(
        source_platform='bilibili',
        source_url='https://example.com/v',
        title='T',
        transcript_text='x' * 200,
    )

    short_env = build_reader_envelope(asset=short_asset, settings=settings, model='gpt-4.1-mini')
    long_env = build_reader_envelope(asset=long_asset, settings=settings, model='gpt-4.1-mini')

    assert short_env.document['transcript_truncated'] is False
    assert long_env.document['transcript_truncated'] is True
