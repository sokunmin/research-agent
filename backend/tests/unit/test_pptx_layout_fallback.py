"""Unit tests for PptxLayoutToolSpec.find_default_content_layout_name and layout fallback."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from pptx.enum.shapes import PP_PLACEHOLDER

from agent_workflows.events import OutlineOkEvent
from agent_workflows.schemas import (
    PaperSlideOutline,
    ParagraphItem,
    SlideOutline,
    SlideOutlineWithLayout,
)
from agent_workflows.slide_gen import SlideGenerationWorkflow
from tools.pptx_tools import PptxLayoutToolSpec, PptxRenderer


REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_PATH = REPO_ROOT / "assets" / "template.pptx"


def test_find_default_content_layout_name_against_template():
    spec = PptxLayoutToolSpec(str(TEMPLATE_PATH))
    cover = spec.find_cover_layout_name()
    default_content = spec.find_default_content_layout_name()

    all_names = [layout["layout_name"] for layout in spec.all_layout]
    assert default_content in all_names
    assert default_content != cover

    idx_title, idx_content = spec.get_placeholder_indices(default_content)
    assert idx_title is not None
    assert idx_content is not None


def test_find_default_content_layout_name_fallback_to_first():
    spec = PptxLayoutToolSpec.__new__(PptxLayoutToolSpec)
    spec._all_layout = [
        {
            "layout_name": "TITLE",
            "placeholders": [
                {"index": 0, "placeholder_type": PP_PLACEHOLDER.TITLE},
                {"index": 1, "placeholder_type": PP_PLACEHOLDER.SUBTITLE},
            ],
        },
        {
            "layout_name": "BLANK",
            "placeholders": [],
        },
    ]

    assert spec.find_cover_layout_name() == "TITLE"
    assert spec.find_default_content_layout_name() == "TITLE"


def test_renderer_succeeds_with_fallback_layout(tmp_path):
    spec = PptxLayoutToolSpec(str(TEMPLATE_PATH))
    fallback_layout = spec.find_default_content_layout_name()
    fb_t, fb_c = spec.get_placeholder_indices(fallback_layout)

    renderer = PptxRenderer(str(TEMPLATE_PATH), tmp_path, spec)
    outlines = [
        {
            "title": "Fallback Slide",
            "content": [{"text": "Recovered from invalid layout_name", "level": 0}],
            "layout_name": fallback_layout,
            "idx_title_placeholder": fb_t,
            "idx_content_placeholder": fb_c,
        }
    ]
    out_path = renderer.generate_pptx(outlines, "fallback_test.pptx")
    assert out_path.exists()
    assert renderer.content_integrity_check(out_path, outlines) == []


def test_photo_only_layout_triggers_fallback_for_content_slide(tmp_path):
    spec = PptxLayoutToolSpec(str(TEMPLATE_PATH))
    all_names = [layout["layout_name"] for layout in spec.all_layout]
    assert "THREE_PHOTO" in all_names

    # Photo-only layout has no content placeholder
    _, photo_idx_c = spec.get_placeholder_indices("THREE_PHOTO")
    assert photo_idx_c is None

    expected_fallback = spec.find_default_content_layout_name()
    fb_t, fb_c = spec.get_placeholder_indices(expected_fallback)
    assert fb_c is not None

    # Exercise SlideGenerationWorkflow.outlines_with_layout with LLM returning THREE_PHOTO
    wf = SlideGenerationWorkflow.__new__(SlideGenerationWorkflow)
    wf.pptx_spec = spec
    wf.workflow_artifacts_path = tmp_path
    wf.slide_outlines_fname = "slide_outlines.json"
    wf._emit_message = MagicMock()
    wf._generate_title = AsyncMock(return_value="Test Deck Title")
    wf._generate_subtitle = AsyncMock(return_value="Test Subtitle")

    slide = SlideOutline(
        title="Methodology Overview",
        content=[ParagraphItem(text="Key architectural detail", level=0)],
    )
    paper_outline = PaperSlideOutline(
        paper_title="Sample Paper",
        paper_authors="Author A",
        paper_year="2025",
        content_slides=[slide],
    )
    ev = OutlineOkEvent(summary="summary", paper_outline=paper_outline)

    fake_program = MagicMock()
    fake_program.acall = AsyncMock(
        return_value=SlideOutlineWithLayout(
            title=slide.title,
            content=slide.content,
            layout_name="THREE_PHOTO",
            idx_title_placeholder=0,
            idx_content_placeholder=1,
        )
    )
    wf._text_program = MagicMock(return_value=fake_program)

    ctx = MagicMock()
    ctx.store.get = AsyncMock(return_value=1)
    ctx.collect_events = MagicMock(return_value=[ev])

    result_ev = asyncio.run(wf.outlines_with_layout(ctx, ev))

    saved = json.loads(Path(result_ev.outlines_fpath).read_text())
    # Index 0: front slide, Index 1: section title slide, Index 2: content slide, Index 3: thank-you
    content_slide_out = saved[2]
    assert content_slide_out["layout_name"] == expected_fallback
    assert content_slide_out["idx_title_placeholder"] == fb_t
    assert content_slide_out["idx_content_placeholder"] == fb_c

    renderer = PptxRenderer(str(TEMPLATE_PATH), tmp_path, spec)
    out_path = renderer.generate_pptx(saved, "photo_fallback_test.pptx")
    assert renderer.content_integrity_check(out_path, saved) == []
