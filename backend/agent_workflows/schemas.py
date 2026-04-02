from typing import Optional, Any, Literal, Dict

from pydantic import BaseModel, Field, field_validator


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
    idx_title_placeholder: Optional[str] = Field(
        default=None,
        description="Index of the title placeholder in the page layout. None if the layout has no title placeholder (e.g. THREE_PHOTO, FULL_PHOTO, BLANK)."
    )
    idx_content_placeholder: Optional[str] = Field(
        default=None,
        description="Index of the content placeholder in the page layout. None if the layout has no content placeholder (e.g. THREE_PHOTO, FULL_PHOTO, BLANK, SECTION_HEADER_CENTER, SECTION_HEADER_TOP)."
    )

    @field_validator('idx_title_placeholder', 'idx_content_placeholder', mode='before')
    @classmethod
    def coerce_int_to_str(cls, v):
        if isinstance(v, int):
            return str(v)
        return v


class SlideValidationResult(BaseModel):
    is_valid: bool
    suggestion_to_fix: str


class SlideNeedModifyResult(BaseModel):
    slide_idx: int
    suggestion_to_fix: str


class WorkflowStreamingEvent(BaseModel):
    event_type: Literal["server_message", "request_user_input"] = Field(
        ..., description="Type of the event"
    )
    event_sender: str = Field(
        ..., description="Sender (workflow step name) of the event"
    )
    event_content: Dict[str, Any] = Field(..., description="Content of the event")
