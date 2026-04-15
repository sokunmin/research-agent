from typing import Optional, Any, Literal, Dict

from pydantic import BaseModel, Field

IssueType = Literal["content_too_long", "content_missing", "visual_overlap", "ok"]


class SlideOutline(BaseModel):
    """Slide outline for one page"""

    title: str = Field(..., description="Title of the slide")
    content: str = Field(..., description="Main text content of the slide")


class SlideOutlineWithLayout(BaseModel):
    """Slide outline with layout information for one page"""

    title: str = Field(..., description="Title of the slide")
    content: str = Field(..., description="Main text content of the slide")
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
