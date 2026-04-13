from pathlib import Path
from typing import Optional

from pptx import Presentation
from pptx.util import Inches
from pptx.enum.shapes import PP_PLACEHOLDER
from llama_index.core.tools import FunctionTool


class PptxLayoutToolSpec:
    """Slide layout tools sourced from the PPTX template file.

    Provides layout metadata for the slide generation ReActAgent.
    Currently disabled in SlideGenerationWorkflow.to_tool_list() because
    the P2 prompt pattern reads layout_name directly from the JSON outline.
    Re-enable by adding self.pptx_spec.to_tool_list() in the workflow's
    to_tool_list() when the agent needs to query layouts at runtime.
    """

    def __init__(self, template_path: str) -> None:
        self._all_layout = self._load_layouts(template_path)

    def _load_layouts(self, template_path: str) -> list:
        """Read layout names and placeholder indices from the PPTX template file.
        Moved from utils/tools.py get_all_layouts_info — only used by this class."""
        prs = Presentation(template_path)
        layouts_info = []
        for layout in prs.slide_layouts:
            layout_info = {}
            layout_info["layout_name"] = layout.name
            placeholders_info = []
            for placeholder in layout.placeholders:
                text_frame = placeholder.text_frame
                font_size = None
                if (
                    text_frame
                    and text_frame.paragraphs
                    and text_frame.paragraphs[0].font.size
                ):
                    font_size = text_frame.paragraphs[0].font.size.pt
                auto_size = text_frame.auto_size.name if text_frame.auto_size else None
                placeholder_info = {
                    "index": placeholder.placeholder_format.idx,
                    "placeholder_type": placeholder.placeholder_format.type,
                    "name": placeholder.name,
                    "shape_type": placeholder.shape_type,
                    "left": Inches(placeholder.left.inches),
                    "top": Inches(placeholder.top.inches),
                    "width": Inches(placeholder.width.inches),
                    "height": Inches(placeholder.height.inches),
                    "font_size": font_size,
                    "auto_size": auto_size,
                }
                placeholders_info.append(placeholder_info)
            layout_info["placeholders"] = placeholders_info
            layout_info["number_of_shapes"] = len(layout.shapes)
            layout_info["has_background"] = layout.background is not None
            layout_info["slide_master_name"] = layout.slide_master.name
            layouts_info.append(layout_info)
        return layouts_info

    def get_placeholder_indices(
        self, layout_name: str
    ) -> tuple[Optional[int], Optional[int]]:
        """Return (idx_title, idx_content) for the given layout.

        Filters by PP_PLACEHOLDER.TITLE and PP_PLACEHOLDER.BODY types.
        Works across all PPTX templates regardless of placeholder name conventions.
        Returns None for each index if the placeholder type is not found in the layout.

        Raises ValueError if layout_name is not found in the template.
        """
        layout = next(
            (l for l in self._all_layout if l["layout_name"] == layout_name), None
        )
        if layout is None:
            raise ValueError(f"Layout '{layout_name}' not found in template")
        idx_title = next(
            (p["index"] for p in layout["placeholders"]
             if p["placeholder_type"] == PP_PLACEHOLDER.TITLE),
            None,
        )
        idx_content = next(
            (p["index"] for p in layout["placeholders"]
             if p["placeholder_type"] == PP_PLACEHOLDER.BODY),
            None,
        )
        return idx_title, idx_content

    @property
    def all_layout(self) -> list:
        """Layout metadata for direct workflow use (not an agent tool).
        Used by the outlines_with_layout step to populate AUGMENT_LAYOUT_PMT."""
        return self._all_layout

    def get_all_layout(self) -> list:
        """Return all available slide layout names and placeholder indices
        from the PPTX template. Use when the agent needs to verify which
        layouts are available or look up placeholder indices at runtime."""
        return self._all_layout

    def to_tool_list(self) -> list[FunctionTool]:
        """Full list of PPTX layout tools available from this spec."""
        return [
            FunctionTool.from_defaults(
                fn=self.get_all_layout,
                description=(
                    "Return all available slide layout names and placeholder indices "
                    "from the PPTX template. Use to verify available layouts or find "
                    "correct placeholder indices before generating or modifying slides."
                ),
            )
        ]


class PptxConversionToolSpec:
    """PPTX file conversion tools (e.g. slides → images for VLM validation).

    The validate_slides step calls self.pptx2images() directly as a workflow
    utility. Re-enable to_tool_list() if the agent needs to trigger conversion itself.
    """

    # No __init__ needed — this class holds no state.
    # Instantiate with PptxConversionToolSpec() and call methods directly.

    def pptx2images(
        self, pptx_path: Path, output_folder: Optional[Path] = None, dpi: int = 200
    ) -> str:
        """Convert each slide of a PPTX file to PNG images.
        Returns the output folder path containing the slide images.
        Use before passing slides to a vision model for validation."""
        from utils.file_processing import pptx2images as _pptx2images

        return _pptx2images(pptx_path, output_folder, dpi)

    def to_tool_list(self) -> list[FunctionTool]:
        """Full list of PPTX conversion tools available from this spec."""
        return [
            FunctionTool.from_defaults(
                fn=self.pptx2images,
                description=(
                    "Convert each slide of a PPTX file to PNG images. "
                    "Returns the output folder path containing the slide images. "
                    "Use before passing slides to a vision model for validation."
                ),
            )
        ]
