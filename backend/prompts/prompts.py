RELEVANCE_SURVEY_HEURISTIC_PMT = (
    "You are a research paper relevance classifier conducting a literature survey. "
    "Research query: '{topic}'. "
    "A paper is relevant only if its core contribution directly addresses the research "
    "query — the query topic must be the primary subject of study, not merely an "
    "application context or a tool used without deeper analysis. "
    "Heuristic: would this paper be cited in a survey specifically on '{topic}'? "
    "Respond with exactly one word: yes or no."
)
# Used by PaperRelevanceFilter Stage-2 LLM to resolve borderline embedding matches.

ACADEMIC_QUERY_REFORMULATION_PMT = (
    "You are an academic search specialist. "
    "Given a user's research interest, rewrite it as a concise academic keyword query "
    "suitable for OpenAlex full-text search (BM25). "
    "Rules: use domain-specific terminology, remove conversational phrasing, "
    "keep the scope faithful to the original interest — do not generalise. "
    "Respond with only the reformulated query — no explanation, no quotes."
)
# Used before calling fetch_candidate_papers to convert natural-language user
# queries into keyword-optimised academic search terms.

RESEARCH_TOPIC = """
Use Machine learning, NLP or GenAI technologies for automating powerpoint presentation slide generation, 
or use genAI for other layout design task.
"""

LLAMAPARSE_INSTRUCTION = """
This is a paper from arXiv that you need to parse. Make sure to parse it into proper markdown format.
"""

REACT_PROMPT_SUFFIX = """

## Tools
You have access to a wide variety of tools. You are responsible for using
the tools in any sequence you deem appropriate to complete the task at hand.
This may require breaking the task into subtasks and using different tools
to complete each subtask.

You have access to the following tools:
{tool_desc}

## Output Format
To answer the question, please use the following format.

```
Thought: I need to use a tool to help me answer the question.
Action: tool name (one of {tool_names}) if using a tool.
Action Input: the input to the tool, in a JSON format representing the kwargs
(e.g. {{"code": "print('hello')"}} for run_code, {{"remote_dir": "/sandbox"}} for list_files)
```

Please ALWAYS start with a Thought.

Please use a valid JSON format for the Action Input. Do NOT do this {{'input': 'hello world', 'num_beams': 5}}.

If this format is used, the user will respond in the following format:

```
Observation: tool response
```

Use the minimum number of tool calls needed. Stop as soon as the goal is achieved.
At that point, you MUST respond in one of the following two formats:

```
Thought: I can answer without using any more tools.
Answer: [your answer here]
```

```
Thought: I cannot answer the question with the provided tools.
Answer: Sorry, I cannot answer your query.
```

{sandbox_stop_rule}
## Current Conversation
Below is the current conversation consisting of interleaving human and assistant messages.

"""



SUMMARIZE_PAPER_PMT = """
You are an AI specialized in summarizing scientific papers.
 Your goal is to create concise and informative summaries, with each section preferably around 100 words and 
 limited to a maximum of 200 words, focusing on the core approach, methodology, datasets,
 evaluation details, and conclusions presented in the paper. After you summarize the paper,
 save the summary as a markdown file.
 
Instructions:
- Key Approach: Summarize the main approach or model proposed by the authors.
 Focus on the core idea behind their method, including any novel techniques, algorithms, or frameworks introduced.
- Key Components/Steps: Identify and describe the key components or steps in the model or approach.
 Break down the architecture, modules, or stages involved, and explain how each contributes to the overall method.
- Model Training/Finetuning: Explain how the authors trained or finetuned their model.
 Include details on the training process, loss functions, optimization techniques, 
 and any specific strategies used to improve the model’s performance.
- Dataset Details: Provide an overview of the datasets used in the study.
 Include information on the size, type and source. Mention whether the dataset is publicly available
 and if there are any benchmarks associated with it.
- Evaluation Methods and Metrics: Detail the evaluation process used to assess the model's performance.
 Include the methods, benchmarks, and metrics employed.
- Conclusion: Summarize the conclusions drawn by the authors. Include the significance of the findings,
any potential applications, limitations acknowledged by the authors, and suggested future work.
- Authors: List the authors as shown on the paper's title page. If more than 3 authors, use "First Author et al." format.
- Year: Publication year as a 4-digit number. Extract from the paper header or footer.

Ensure that the summary is clear and concise, avoiding unnecessary jargon or overly technical language.
 Aim to be understandable to someone with a general background in the field.
 Ensure that all details are accurate and faithfully represent the content of the original paper.
 Avoid introducing any bias or interpretation beyond what is presented by the authors. Do not add any
 information that is not explicitly stated in the paper. Stick to the content presented by the authors.

"""

summary2outline_requirements = """
Extract paper_title, paper_authors, paper_year, and generate exactly 4 content_slides.

paper_authors: as listed on the title page; if more than 3, use "First Author et al."
paper_year: 4-digit publication year

Each slide title answers one of these questions about the paper:
  1. What problem does this work address and what is the proposed solution?
  2. How was the approach designed and what resources or data were used?
  3. What evidence or experiments support the claims?
  4. What are the key contributions and open challenges?

Each slide:
  - title: concise academic heading (max 5 words) that answers the question
  - content: max 4 bullets, each ≤ 15 words, level=0

Plain text only: no **bold**, no *italic*, no backticks, no * or - prefix.
"""

SUMMARY2OUTLINE_PMT = (
    """
You are an AI that generates PowerPoint slide outlines from academic paper summaries.
Requirements:"""
    + summary2outline_requirements
    + """
Here is the paper summary: {summary}

Output the following fields:
- paper_title: the paper title
- paper_authors: authors (e.g. "Guo et al.")
- paper_year: publication year as integer
- content_slides: list of exactly 4 slides, each with title and content list
"""
)

MODIFY_SUMMARY2OUTLINE_PMT = (
    """
You are an AI that modifies slide outlines based on user feedback.
Original summary: '''{summary_txt}'''
Current outline: '''{outline_txt}'''
Feedback: '''{feedback}'''
Apply the feedback while respecting the original requirements:"""
    + summary2outline_requirements
    + """
Output the same fields:
- paper_title: unchanged
- paper_authors: unchanged
- paper_year: unchanged
- content_slides: list of exactly 4 slides, each with title and content list
"""
)

AUGMENT_LAYOUT_PMT = """
You are an AI that selects the most appropriate slide layout for given slide content.
You will receive a slide with a title and body text.

LAYOUT DESCRIPTIONS — what each layout is for:

1. TITLE_SLIDE
   Use for: Opening cover slide of the presentation, OR closing thank-you/Q&A slide.
   Structure: Large title + subtitle area. NO body content area.
   Signals: author attribution ("Presented by:"), institution, "Thank You", "Q&A", "Conclusion".

2. TITLE_AND_BODY
   Use for: Standard academic or technical content slide with substantial text.
   Structure: Title + large body text area for paragraphs or bullets.
   Signals: multiple sentences or bullet points of academic/technical content.

3. QUOTE
   Use for: Displaying a quotation with attribution.
   Structure: Large quote text area + attribution line (— Author Name).
   Signals: text in quotes followed by "— Name" attribution format.

4. PHOTO_LANDSCAPE
   Use for: A slide whose main content is a single wide/horizontal image or diagram.
   Structure: Title + caption text + landscape (wide) photo placeholder.
   Signals: "[Wide image/diagram/chart]", horizontal layout, description of a wide visual.

5. SECTION_HEADER_CENTER
   Use for: Chapter or section divider slide — title only, centered.
   Structure: Title centered on slide. NO body content area.
   Signals: empty or near-empty body, "Chapter X", "Section X", "Part X".

6. PHOTO_PORTRAIT
   Use for: A slide whose main content is a single tall/vertical image or portrait photo.
   Structure: Title + caption text + portrait (tall) photo placeholder.
   Signals: "[Portrait photo]", headshot, tall/vertical image description.

7. SECTION_HEADER_TOP
   Use for: Chapter or section divider — title at top. Same role as SECTION_HEADER_CENTER.
   Structure: Title at top of slide. NO body content area.
   Signals: same as SECTION_HEADER_CENTER.

8. CONTENT_WITH_PHOTO
   Use for: A slide combining bullet-point text AND an image/figure side by side.
   Structure: Title + text content area + photo placeholder (split layout).
   Signals: slide body contains BOTH bullet points AND a "[Figure/Image: ...]" reference together.

9. BULLET_LIST
   Use for: Bullet-point content slide — similar to TITLE_AND_BODY but optimized for lists.
   Structure: Title + body text area.
   Signals: body is primarily a list of bullet points (* or -).

10. THREE_PHOTO
    Use for: Comparing or displaying three images side by side.
    Structure: Three photo placeholders. NO title, NO text content area.
    Signals: "[Image 1: ...] [Image 2: ...] [Image 3: ...]", three separate image references.

11. FULL_PHOTO
    Use for: A full-bleed image covering the entire slide with no text.
    Structure: Single full-page photo placeholder. NO title, NO text area.
    Signals: "[Full-page image/visualization]", entirely visual slide with no text content.

12. BLANK
    Use for: A completely empty slide with no content.
    Structure: No placeholders except footer.
    Signals: both title and content are empty strings.

The following layouts are available: {available_layout_names}
Layout details:
{available_layouts}

Slide content to classify:
{slide_content}

Output the following fields:
- title: the slide title text (copy verbatim from input)
- content: the content list (copy verbatim from input, do not modify the list)
- layout_name: the exact name string of the chosen layout (must match one of the available layout names exactly)
- idx_title_placeholder: the numeric index (integer) of the title placeholder in the chosen layout.
- idx_content_placeholder: the numeric index (integer) of the content placeholder in the chosen layout.
CRITICAL: For layouts THREE_PHOTO, FULL_PHOTO, and BLANK:
  - idx_title_placeholder MUST be null (not a number, not a string)
  - idx_content_placeholder MUST be null (not a number, not a string)
  These layouts have NO title or content placeholders. Outputting any number here is incorrect and will cause a runtime error.
"""


SLIDE_VALIDATION_PMT = """
You are an AI that validates a PowerPoint slide image.

Rules — a slide is invalid if:
- Text is cut off, overflows its text box, or is too small to read (font < ~10pt equivalent)
- Two elements visually overlap each other
- A placeholder that should have content appears empty

If the slide is invalid, you MUST set issue_type to exactly one of:
  "content_too_long"  — text is present but too small/clipped (LLM will trim the content)
  "content_missing"   — a placeholder appears empty (will re-render from source JSON)
  "visual_overlap"    — two visible elements overlap (Python will adjust position)
  "ok"               — slide is valid (use when is_valid=true)

Output the JSON fields: is_valid, issue_type, suggestion_to_fix.
"""

CONTENT_FIX_PMT = """
You are an AI that shortens slide content that is too long to display clearly.

The slide at index {slide_idx} has too many items. Current content list:
---
{current_content}
---

Reduce to approximately 60% of current items by removing less important points.
Requirements:
- Output a JSON list with the same structure: [{{"text": "...", "level": 0}}, ...]
- Keep the most important points; remove redundant detail
- Do not add new information
- Plain text only in text values: no **bold**, no *italic*, no backticks
- Output ONLY the JSON list, no explanation
"""
