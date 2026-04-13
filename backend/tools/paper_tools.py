from llama_index.core.tools import FunctionTool


class PaperSearchToolSpec:
    """Academic paper search tools using the OpenAlex API.

    The discover_candidate_papers step calls self.fetch_papers() directly.
    Re-enable to_tool_list() if a future ReActAgent needs to drive paper discovery itself.
    """

    def fetch_papers(self, query: str) -> list:
        """Search OpenAlex for recent open-access academic papers on a research topic.
        Returns Papers sorted by citation count."""
        from agent_workflows.paper_scraping import fetch_candidate_papers

        return fetch_candidate_papers(query)

    def to_tool_list(self) -> list[FunctionTool]:
        """Full list of paper search tools available from this spec."""
        return [
            FunctionTool.from_defaults(
                fn=self.fetch_papers,
                name="search_academic_papers",
                description=(
                    "Search OpenAlex for recent open-access academic papers on a research topic. "
                    "Returns Papers sorted by citation count."
                ),
            )
        ]
