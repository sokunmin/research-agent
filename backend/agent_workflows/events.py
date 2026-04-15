from pathlib import Path
from typing import List, Optional

from llama_index.core.workflow import Event

from agent_workflows.paper_scraping import Paper, PaperRelevanceResult
from agent_workflows.schemas import *


class PaperEvent(Event):
    paper: Paper


class FilteredPaperEvent(Event):
    paper: Paper
    relevance: PaperRelevanceResult   # is_relevant: bool, similarity_score: float


class Paper2SummaryDispatcherEvent(Event):
    papers_path: str


class Paper2SummaryEvent(Event):
    pdf_path: Path
    image_output_dir: Path
    summary_path: Path


class SummaryStoredEvent(Event):
    fpath: Path


class SummaryWfReadyEvent(Event):
    summary_dir: str


class SummaryEvent(Event):
    summary: str


class OutlineFeedbackEvent(Event):
    summary: str
    outline: SlideOutline
    feedback: str


class OutlineEvent(Event):
    summary: str
    outline: SlideOutline


class OutlineOkEvent(Event):
    summary: str
    outline: SlideOutline


class OutlinesWithLayoutEvent(Event):
    # outline_w_layout: List[SlideOutlineWithLayout]
    outlines_fpath: Path
    outline_example: SlideOutlineWithLayout


class ConsolidatedOutlineEvent(Event):
    outlines: List[SlideOutline]


class PythonCodeEvent(Event):
    code: str


class SlideGeneratedEvent(Event):
    pptx_fpath: str
    outlines_fpath: Optional[str] = None


class ContentFixEvent(Event):
    """LLM trims JSON content for content_too_long slides, then re-renders."""
    results: List[SlideNeedModifyResult]
    pptx_fpath: str
    outlines_fpath: str


class ContentMissingFixEvent(Event):
    """Re-render from JSON only — no LLM. JSON is correct, pptx was empty."""
    outlines_fpath: str


class VisualFixEvent(Event):
    """Python adjusts placeholder positions for visual_overlap slides."""
    results: List[SlideNeedModifyResult]
    pptx_fpath: str


class DummyEvent(Event):
    result: str
