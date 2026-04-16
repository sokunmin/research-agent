from typing import Optional, Any, Literal, Dict, List

from pydantic import BaseModel, Field

IssueType = Literal["content_too_long", "content_missing", "visual_overlap", "ok"]

SLIDES_PER_PAPER = 4  # number of content slides generated per paper


class ParagraphItem(BaseModel):
    """One paragraph in a slide's content area."""
    text: str = Field(..., description="Plain text only — no markdown, no * or - prefix")
    level: int = Field(default=0, description="Indent level: 0=main bullet, 1=sub-bullet")


class SlideOutline(BaseModel):
    """Slide outline for one page"""

    title: str = Field(..., description="Title of the slide")
    content: List[ParagraphItem] = Field(..., description="Slide body as a list of paragraphs")


class SlideOutlineWithLayout(BaseModel):
    """Slide outline with layout information for one page"""

    title: str = Field(..., description="Title of the slide")
    content: List[ParagraphItem] = Field(..., description="Slide body as a list of paragraphs")
    layout_name: str = Field(
        ..., description="Name of the page layout to be used for the slide"
    )
    idx_title_placeholder: Optional[int] = Field(
        default=None,
        description="Index of the title placeholder in the page layout. None if the layout has no title placeholder (e.g. THREE_PHOTO, FULL_PHOTO, BLANK)."
    )
    idx_content_placeholder: Optional[int] = Field(
        default=None,
        description="Index of the content placeholder in the page layout. None if the layout has no content placeholder (e.g. THREE_PHOTO, FULL_PHOTO, BLANK, SECTION_HEADER_CENTER, SECTION_HEADER_TOP)."
    )


class PaperSlideOutline(BaseModel):
    """Slide outlines for one paper: a section title slide plus content slides."""
    paper_title: str = Field(..., description="Paper title shown on the section title slide")
    paper_authors: str = Field(..., description="Authors as shown on the paper, e.g. 'Guo et al.'")
    paper_year: int = Field(..., description="Publication year as a 4-digit integer, e.g. 2021")
    content_slides: List[SlideOutline] = Field(
        ..., description=f"Exactly {SLIDES_PER_PAPER} content slides for this paper"
    )


class SlideValidationResult(BaseModel):
    is_valid: bool
    issue_type: IssueType = Field(
        default="ok",
        description=(
            "content_too_long: text too small/clipped, LLM must trim JSON content. "
            "content_missing: slide appears empty but JSON has content, re-render. "
            "visual_overlap: elements overlap, adjust placeholder position. "
            "ok: no issues."
        ),
    )
    suggestion_to_fix: str = Field(default="")


class SlideNeedModifyResult(BaseModel):
    slide_idx: int
    issue_type: IssueType = Field(default="content_missing")
    suggestion_to_fix: str = Field(default="")
    target_placeholder_name: Optional[str] = Field(default=None)
    delta_top_pt: Optional[float] = Field(default=None)


class WorkflowStreamingEvent(BaseModel):
    event_type: Literal["server_message", "request_user_input"] = Field(
        ..., description="Type of the event"
    )
    event_sender: str = Field(
        ..., description="Sender (workflow step name) of the event"
    )
    event_content: Dict[str, Any] = Field(..., description="Content of the event")
