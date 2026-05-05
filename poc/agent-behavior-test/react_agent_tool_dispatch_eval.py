"""
Slide Gen ReAct Suffix Engineering Experiment
=============================================
Measures how different REACT_PROMPT_SUFFIX variants affect ReAct loop behavior
of the slide_gen agent, holding SLIDE_GEN_PMT (P2, validated) constant.

Method: Direct litellm.completion() loop simulating ReAct turns.
        MockSandbox returns realistic responses without Docker.
        Metrics: terminated_correctly, n_turns, n_tool_calls, loops_after_success,
                 first_code_correct, hallucinated_failure, format_violation.

Run from project root:
    micromamba run -n py3.12 python poc/agent-behavior-test/slide_gen_react_suffix_eng.py

Prerequisite: Ollama running locally, OLLAMA_API_BASE set in .env.
Results appended to slide_gen_react_suffix_eng_results.json (append-only).
"""

from __future__ import annotations

import ast
import json
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from dotenv import load_dotenv
load_dotenv('/Users/chunming/MyWorkSpace/agent_workspace/research-agent/dev/.env')

import litellm

# ══════════════════════════════════════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════════════════════════════════════

N_RUNS = 3
MAX_TURNS = 10
RUN_PROMPT_IDS: Optional[list[str]] = ["P5_stop_on_failure"]  # controls both main and error sub-experiment; None = run all

RESULTS_PATH = str(Path(__file__).parent / "slide_gen_react_suffix_eng_results.json")

MODELS = [
    {"name": "ollama/gemma3:4b",             "label": "gemma3:4b"},
    {"name": "ollama/ministral-3:14b-cloud", "label": "ministral-3:14b-cloud"},
]

# Error Behavior Sub-Experiment config
ERROR_N_RUNS: int = 3
ERROR_MAX_TURNS: int = 10
PERSISTENT_ERROR_MAX_ATTEMPTS: int = 3  # must match "N attempts" text in _P5_SUFFIX_TEMPLATE
ERROR_RESULTS_PATH = str(Path(__file__).parent / "slide_gen_react_suffix_eng_error_results.json")

# ══════════════════════════════════════════════════════════════════════════════
# Slide data (TC2 from Experiment 2 — includes FULL_PHOTO with null idx values)
# ══════════════════════════════════════════════════════════════════════════════

SLIDE_DATA: list[dict] = [
    {
        "title": "Attention Is All You Need",
        "content": "A Research Presentation\nPresented by: John Smith",
        "layout_name": "TITLE_SLIDE",
        "idx_title_placeholder": 0,
        "idx_content_placeholder": 1,
    },
    {
        "title": "Model Architecture",
        "content": "* Multi-head attention\n* Positional encoding\n* Feed-forward layers",
        "layout_name": "BULLET_LIST",
        "idx_title_placeholder": 0,
        "idx_content_placeholder": 1,
    },
    {
        "title": "",
        "content": "",
        "layout_name": "FULL_PHOTO",
        "idx_title_placeholder": None,
        "idx_content_placeholder": None,
    },
    {
        "title": "Results",
        "content": "* BLEU score: 41.0 on WMT 2014 En-De\n* Outperforms all previous SOTA",
        "layout_name": "TITLE_AND_BODY",
        "idx_title_placeholder": 0,
        "idx_content_placeholder": 1,
    },
    {
        "title": "Thank You",
        "content": "Q&A",
        "layout_name": "TITLE_SLIDE",
        "idx_title_placeholder": 0,
        "idx_content_placeholder": 1,
    },
]

INITIAL_USER_MESSAGE = (
    f"Slide data is available at /sandbox/slide_outlines.json. "
    f"An example item: {json.dumps(SLIDE_DATA[0])}. "
    f"Generate the slide deck."
)

# ══════════════════════════════════════════════════════════════════════════════
# Tool descriptions (for {tool_desc}/{tool_names} substitution in suffix templates)
# ══════════════════════════════════════════════════════════════════════════════

TOOL_NAMES = "run_code, list_files, upload_file"

TOOL_DESC = (
    "run_code(code: str) -> str: Execute Python code in the sandbox container and return stdout. "
    "python-pptx is pre-installed. Files persist at /sandbox/ between calls.\n"
    "list_files(remote_dir: str = '/sandbox') -> str: List files in the sandbox directory. "
    "Returns newline-separated file paths.\n"
    "upload_file(local_file_path: str) -> str: Upload a local file into the sandbox container "
    "at /sandbox/<filename>."
)

TOOL_DESC_NO_PPTX_CLAIM = TOOL_DESC.replace("python-pptx is pre-installed. ", "")

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE_GEN_PMT — P2 variant (validated in Experiment 2, held constant)
# ══════════════════════════════════════════════════════════════════════════════

SLIDE_GEN_PMT = """\
You are an AI code executor that generates a PowerPoint slide deck using python-pptx.

Your ONLY job is to write Python code and execute it using the `run_code` tool.
Do NOT explain, describe, or ask the user questions. Just write and execute the code.

Input files already available in the sandbox:
- Slide outlines JSON: `/sandbox/slide_outlines.json` (list of slide outline dicts)
- PPTX template: `/sandbox/pptx-template.pptx`

Steps you MUST follow in order:
1. Use `run_code` to execute python-pptx code that generates the slide deck.
2. Use `list_files` to confirm `paper_summaries.pptx` exists in /sandbox/.
3. If the file does not exist, fix and re-run the code.
4. When `paper_summaries.pptx` is confirmed present, output: "Done. paper_summaries.pptx has been saved."

Requirements for the generated code:
- Load the template from `/sandbox/pptx-template.pptx` using Presentation()
- Load slide data from `/sandbox/slide_outlines.json` using json.load()
- Loop over all items; create one slide per item
- python-pptx layout lookup (add_slide requires a SlideLayout object, NOT a string or int):
    layout = next((l for l in prs.slide_layouts if l.name == item['layout_name']), prs.slide_layouts[0])
    slide  = prs.slides.add_slide(layout)
- Placeholder fill with null guard (idx values may be None for visual-only layouts):
    if item['idx_title_placeholder'] is not None:
        slide.placeholders[item['idx_title_placeholder']].text = item['title']
    if item['idx_content_placeholder'] is not None:
        slide.placeholders[item['idx_content_placeholder']].text = item['content']
- If a placeholder has auto_size=TEXT_TO_FIT_SHAPE, use MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE and do NOT set font size
- If there is no front page or 'thank you' slide, add them using the appropriate layout
- Save the final file as `/sandbox/paper_summaries.pptx` using prs.save()

CRITICAL: You MUST use `run_code` to actually execute the code. Do not output code as text only.
CRITICAL: Task is complete only when `list_files` confirms `paper_summaries.pptx` exists.
"""

# ══════════════════════════════════════════════════════════════════════════════
# REACT_PROMPT_SUFFIX templates (contain {tool_desc} and {tool_names} placeholders)
# NOTE: Use single braces in JSON examples — this experiment uses .replace(), NOT str.format().
#       The production file uses double braces for str.format() compat; do NOT copy those here.
# ══════════════════════════════════════════════════════════════════════════════

_P0_SUFFIX_TEMPLATE = """\

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
Action Input: the input to the tool, in a JSON format representing the kwargs (e.g. {"input": "hello world", "num_beams": 5})
```

Please ALWAYS start with a Thought.

Please use a valid JSON format for the Action Input. Do NOT do this {'input': 'hello world', 'num_beams': 5}.

If this format is used, the user will respond in the following format:

```
Observation: tool response
```

You should keep repeating the above format until you have enough information
to answer the question without using any more tools. At that point, you MUST respond
in the one of the following two formats:

```
Thought: I can answer without using any more tools.
Answer: [your answer here]
```

```
Thought: I cannot answer the question with the provided tools.
Answer: Sorry, I cannot answer your query.
```

## Additional Rules
- The answer MUST contain a sequence of bullet points that explain how you arrived at the answer. This can include aspects of the previous conversation history.
- You MUST obey the function signature of each tool. Do NOT pass in no arguments if the function expects arguments.

## Current Conversation
Below is the current conversation consisting of interleaving human and assistant messages.
"""

_P1_SUFFIX_TEMPLATE = """\

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
Action Input: the input to the tool, in a JSON format representing the kwargs (e.g. {"input": "hello world", "num_beams": 5})
```

Please ALWAYS start with a Thought.

Please use a valid JSON format for the Action Input. Do NOT do this {'input': 'hello world', 'num_beams': 5}.

If this format is used, the user will respond in the following format:

```
Observation: tool response
```

You should keep repeating the above format until you have enough information
to answer the question without using any more tools. At that point, you MUST respond
in the one of the following two formats:

```
Thought: I can answer without using any more tools.
Answer: [your answer here]
```

```
Thought: I cannot answer the question with the provided tools.
Answer: Sorry, I cannot answer your query.
```

## Additional Rules
- The answer MUST contain a sequence of bullet points that explain how you arrived at the answer. This can include aspects of the previous conversation history.
- You MUST obey the function signature of each tool. Do NOT pass in no arguments if the function expects arguments.

## Critical Termination Rule
Once list_files confirms that `paper_summaries.pptx` exists in `/sandbox/`,
you MUST IMMEDIATELY output the following and STOP:
  Thought: The file has been confirmed. Task is complete.
  Answer: Done. paper_summaries.pptx has been saved.
Do NOT call any more tools after this confirmation.
Do NOT re-run the code. Do NOT call list_files again.
Trust the Observation. If it says the file exists, it exists.

## Current Conversation
Below is the current conversation consisting of interleaving human and assistant messages.
"""

_P2_SUFFIX_TEMPLATE = """\

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
Action Input: the input to the tool, in a JSON format representing the kwargs (e.g. {"input": "hello world", "num_beams": 5})
```

Please ALWAYS start with a Thought.

Please use a valid JSON format for the Action Input. Do NOT do this {'input': 'hello world', 'num_beams': 5}.

If this format is used, the user will respond in the following format:

```
Observation: tool response
```

Use the minimum number of tool calls needed. Stop as soon as the goal is achieved.
At that point, you MUST respond in the one of the following two formats:

```
Thought: I can answer without using any more tools.
Answer: [your answer here]
```

```
Thought: I cannot answer the question with the provided tools.
Answer: Sorry, I cannot answer your query.
```

## Current Conversation
Below is the current conversation consisting of interleaving human and assistant messages.
"""

_P4_SUFFIX_TEMPLATE = """\

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
Action Input: the input to the tool, in a JSON format representing the kwargs (e.g. {"code": "print('hello')"} for run_code, {"remote_dir": "/sandbox"} for list_files)
```

Please ALWAYS start with a Thought.

Please use a valid JSON format for the Action Input. Do NOT do this {'input': 'hello world', 'num_beams': 5}.

If this format is used, the user will respond in the following format:

```
Observation: tool response
```

Use the minimum number of tool calls needed. Stop as soon as the goal is achieved.
At that point, you MUST respond in the one of the following two formats:

```
Thought: I can answer without using any more tools.
Answer: [your answer here]
```

```
Thought: I cannot answer the question with the provided tools.
Answer: Sorry, I cannot answer your query.
```

## Current Conversation
Below is the current conversation consisting of interleaving human and assistant messages.
"""

_P5_SUFFIX_TEMPLATE = """\

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
Action Input: the input to the tool, in a JSON format representing the kwargs (e.g. {"code": "print('hello')"} for run_code, {"remote_dir": "/sandbox"} for list_files)
```

Please ALWAYS start with a Thought.

Please use a valid JSON format for the Action Input. Do NOT do this {'input': 'hello world', 'num_beams': 5}.

If this format is used, the user will respond in the following format:

```
Observation: tool response
```

Use the minimum number of tool calls needed. Stop as soon as the goal is achieved.
At that point, you MUST respond in the one of the following two formats:

```
Thought: I can answer without using any more tools.
Answer: [your answer here]
```

```
Thought: I cannot answer the question with the provided tools.
Answer: Sorry, I cannot answer your query.
```

## Critical Stop Rule
If you see "LIMIT REACHED" in any Observation, output IMMEDIATELY:
  Thought: Maximum attempts reached. Cannot complete the task.
  Answer: Task failed after 3 attempts. Error: [summarise the last error seen]
Do NOT call run_code again after seeing "LIMIT REACHED".

## Current Conversation
Below is the current conversation consisting of interleaving human and assistant messages.
"""

_P3_SUFFIX_TEMPLATE = """\

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
Action Input: the input to the tool, in a JSON format representing the kwargs (e.g. {"input": "hello world", "num_beams": 5})
```

Please ALWAYS start with a Thought.

Please use a valid JSON format for the Action Input. Do NOT do this {'input': 'hello world', 'num_beams': 5}.

If this format is used, the user will respond in the following format:

```
Observation: tool response
```

Use the minimum number of tool calls needed. Stop as soon as the goal is achieved.
At that point, you MUST respond in the one of the following two formats:

```
Thought: I can answer without using any more tools.
Answer: [your answer here]
```

```
Thought: I cannot answer the question with the provided tools.
Answer: Sorry, I cannot answer your query.
```

## Critical Termination Rule
Once list_files confirms that `paper_summaries.pptx` exists in `/sandbox/`,
you MUST IMMEDIATELY output the following and STOP:
  Thought: The file has been confirmed. Task is complete.
  Answer: Done. paper_summaries.pptx has been saved.
Do NOT call any more tools after this confirmation.
Do NOT re-run the code. Do NOT call list_files again.
Trust the Observation. If it says the file exists, it exists.

## Current Conversation
Below is the current conversation consisting of interleaving human and assistant messages.
"""

# ══════════════════════════════════════════════════════════════════════════════
# Data structures
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CodeEvalResult:
    """
    Result of evaluating a python-pptx code snippet for correctness.

    Attributes:
        layout_lookup_correct: Code uses slide_layouts name comparison and add_slide(variable).
        save_path_correct: Code calls prs.save() with /sandbox/ path or relative path.
        null_guard_correct: Code checks idx is not None before accessing slide.placeholders[...].
        import_correct: Code imports Presentation from pptx.
    """
    layout_lookup_correct: bool
    save_path_correct: bool
    null_guard_correct: bool
    import_correct: bool

    @property
    def overall_correct(self) -> bool:
        return (self.layout_lookup_correct and self.save_path_correct
                and self.null_guard_correct and self.import_correct)

    @property
    def score(self) -> int:
        return sum([self.layout_lookup_correct, self.save_path_correct,
                    self.null_guard_correct, self.import_correct])


@dataclass
class ReActRunResult:
    """
    All metrics for one (model, prompt_id, run_idx) combination.

    Attributes:
        model_label: Model identifier string (e.g., "gemma3:4b").
        prompt_id: Prompt variant identifier (e.g., "P0_baseline").
        run_idx: 0-indexed run number within (model, prompt_id).
        terminated_correctly: True iff agent emitted "Answer:" before MAX_TURNS exhausted.
        n_turns: Total LLM calls made. Capped at MAX_TURNS.
        n_tool_calls: Total tool dispatches (successful parse + call).
        loops_after_success: True iff any tool call occurred after list_files confirmed file.
        first_code_correct: CodeEvalResult.overall_correct for sandbox.run_code_calls[0].
        hallucinated_failure: True iff agent claimed error after a successful run_code Observation.
        format_violation: True iff agent produced a response parseable as neither Action nor Answer.
        error: Exception message if litellm.completion() raised. None if no exception.
    """
    model_label: str
    prompt_id: str
    run_idx: int
    terminated_correctly: bool
    n_turns: int
    n_tool_calls: int
    loops_after_success: bool
    first_code_correct: bool
    hallucinated_failure: bool
    format_violation: bool
    error: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PromptVariant:
    """
    One REACT_PROMPT_SUFFIX variant with tool placeholders already substituted.

    Attributes:
        id: Short identifier used in results JSON (e.g., "P0_baseline").
        label: Human-readable label for tables (e.g., "P0 (baseline)").
        suffix: The REACT_PROMPT_SUFFIX text with {tool_desc}/{tool_names} already filled.
        description: One-sentence description of what changed from P0.
    """
    id: str
    label: str
    suffix: str
    description: str


# ══════════════════════════════════════════════════════════════════════════════
# Shared ReAct parsing logic
# ══════════════════════════════════════════════════════════════════════════════

class ActionParserMixin:
    """Mixin providing shared ReAct response parsing. Used by all simulator classes."""

    @staticmethod
    def _parse_action(text: str) -> Optional[tuple[str, dict]]:
        """
        Extract (tool_name, kwargs_dict) from an assistant response text.
        Mirrors LlamaIndex extract_tool_use() regex behavior.
        Returns None if Action line or JSON block is missing or unparseable.
        """
        name_match = re.search(r"Action:\s*([^\n\(\) ]+)", text)
        if not name_match:
            return None
        tool_name = name_match.group(1).strip().lower()
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if not json_match:
            return None
        json_str = json_match.group(0)
        try:
            kwargs = json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            try:
                kwargs = ast.literal_eval(json_str)
            except Exception:
                return None
        if not isinstance(kwargs, dict):
            return None
        return tool_name, kwargs

    @staticmethod
    def _has_answer(text: str) -> bool:
        """Return True if text contains 'Answer:' (case-sensitive)."""
        return "Answer:" in text

    @staticmethod
    def _dispatch_tool(action_name: str, kwargs: dict, sandbox) -> str:
        """Dispatch a parsed action to the sandbox. Returns the observation string."""
        if action_name == "run_code":
            return sandbox.run_code(kwargs.get("code", ""))
        elif action_name == "list_files":
            return sandbox.list_files(kwargs.get("remote_dir", "/sandbox"))
        else:  # upload_file
            return sandbox.upload_file(kwargs.get("local_file_path", ""))


# ══════════════════════════════════════════════════════════════════════════════
# CodeEvaluator — methods copied verbatim from slide_gen_prompt_eng.py:294–350
# ══════════════════════════════════════════════════════════════════════════════

class CodeEvaluator:
    """
    Stateless evaluator: checks generated python-pptx code for four correctness criteria
    using regex / string matching. Does not execute the code.
    """

    def evaluate(self, code: str) -> CodeEvalResult:
        code = self._strip_fences(code)
        return CodeEvalResult(
            layout_lookup_correct=self._check_layout_lookup(code),
            save_path_correct=self._check_save_path(code),
            null_guard_correct=self._check_null_guard(code),
            import_correct=self._check_import(code),
        )

    @staticmethod
    def _strip_fences(code: str) -> str:
        """Remove markdown code fences from LLM output."""
        code = re.sub(r'^```[a-zA-Z]*\n?', '', code, flags=re.MULTILINE)
        code = re.sub(r'^```\s*$',         '', code, flags=re.MULTILINE)
        return code.strip()

    @staticmethod
    def _check_layout_lookup(code: str) -> bool:
        """Check 1: correct SlideLayout object lookup via name comparison.

        CORRECT:   code contains slide_layouts + add_slide(variable) + .name ==
        INCORRECT: add_slide("string") or add_slide(0)
        Note: inline add_slide(next(...)) will fail add_slide_var — intentional false negative.
        """
        has_layout_iter   = 'slide_layouts' in code
        add_slide_var     = bool(re.search(r'\.add_slide\(\s*[a-zA-Z_]\w*\s*\)', code))
        add_slide_str     = bool(re.search(r'\.add_slide\(\s*["\']',              code))
        add_slide_int_lit = bool(re.search(r'\.add_slide\(\s*\d+\s*\)',           code))
        has_name_lookup   = bool(re.search(r'\.name\s*==|==\s*\w+\.name',          code))
        return (has_layout_iter and add_slide_var and has_name_lookup
                and not add_slide_str and not add_slide_int_lit)

    @staticmethod
    def _check_save_path(code: str) -> bool:
        """Check 2: pptx saved inside /sandbox/ or relative path (not /app/, /root/, etc.).

        Handles:
        - String literal:  prs.save('/sandbox/file.pptx') or prs.save('file.pptx')
        - f-string:        prs.save(f'/sandbox/file.pptx') — extracted from f'...'
        - Variable-based:  prs.save(some_var) — conservatively treated as correct
        """
        save_literal = re.search(r'prs\.save\(\s*f?["\']([^"\']+)["\']', code)
        save_var     = bool(re.search(r'prs\.save\(\s*[a-zA-Z_]\w*\s*\)', code))

        if save_literal:
            path = save_literal.group(1)
            return path.startswith('/sandbox/') or not path.startswith('/')
        elif save_var:
            return True
        return False

    @staticmethod
    def _check_null_guard(code: str) -> bool:
        """Check 3: null guard present before placeholder access.

        Co-presence check only — does not verify structural wrapping.
        """
        has_none_check         = 'is not None' in code or '!= None' in code
        has_placeholder_access = 'placeholders[' in code
        return has_none_check and has_placeholder_access

    @staticmethod
    def _check_import(code: str) -> bool:
        """Check 4: Presentation class imported from pptx."""
        return 'from pptx import Presentation' in code or 'import pptx' in code


# ══════════════════════════════════════════════════════════════════════════════
# MockSandbox
# ══════════════════════════════════════════════════════════════════════════════

class MockSandbox:
    """
    Simulates the Docker sandbox. Create one instance per ReAct run (do NOT reuse across runs).

    All state (_file_exists, call logs) resets on instantiation.
    run_code evaluates code via CodeEvaluator and returns realistic stdout/stderr.
    list_files returns file listing based on _file_exists.
    upload_file records the upload and returns a success string.
    """

    def __init__(self, slide_data: list[dict], evaluator: CodeEvaluator) -> None:
        self._slide_data = slide_data
        self._evaluator = evaluator
        self._file_exists = False
        self.run_code_calls: list[str] = []
        self.list_files_calls: int = 0
        self.upload_file_calls: list[str] = []

    def run_code(self, code: str) -> str:
        self.run_code_calls.append(code)
        result = self._evaluator.evaluate(code)
        if result.overall_correct:
            self._file_exists = True
            return "Successfully executed. /sandbox/paper_summaries.pptx created."
        if not result.layout_lookup_correct:
            return "ERROR (exit_code=1):\nAttributeError: 'str' object has no attribute 'part'"
        if not result.null_guard_correct:
            return "ERROR (exit_code=1):\nTypeError: '%d format: a real number is required, not NoneType'"
        if not result.save_path_correct:
            return "ERROR (exit_code=1):\nPermissionError: [Errno 13] Permission denied: '/app/assets/paper_summaries.pptx'"
        return "ERROR (exit_code=1):\nRuntimeError: code execution failed"

    def list_files(self, remote_dir: str = "/sandbox") -> str:
        self.list_files_calls += 1
        if self._file_exists:
            return "/sandbox/paper_summaries.pptx"
        return "(no files in /sandbox)"

    def upload_file(self, local_file_path: str) -> str:
        self.upload_file_calls.append(local_file_path)
        filename = Path(local_file_path).name
        return f"Uploaded {local_file_path} → /sandbox/{filename}"


# ══════════════════════════════════════════════════════════════════════════════
# Prompt variants
# ══════════════════════════════════════════════════════════════════════════════

def _build_prompt_variants() -> list[PromptVariant]:
    def fill(template: str) -> str:
        return template.replace("{tool_desc}", TOOL_DESC).replace("{tool_names}", TOOL_NAMES)

    return [
        PromptVariant(
            id="P0_baseline",
            label="P0 (baseline)",
            suffix=fill(_P0_SUFFIX_TEMPLATE),
            description="Verbatim production REACT_PROMPT_SUFFIX.",
        ),
        PromptVariant(
            id="P1_termination_guard",
            label="P1 (termination guard)",
            suffix=fill(_P1_SUFFIX_TEMPLATE),
            description="P0 + explicit stop rule after list_files confirms file.",
        ),
        PromptVariant(
            id="P2_simplified",
            label="P2 (simplified format)",
            suffix=fill(_P2_SUFFIX_TEMPLATE),
            description="P0 with 'keep repeating' replaced and Additional Rules removed.",
        ),
        PromptVariant(
            id="P3_combined",
            label="P3 (combined)",
            suffix=fill(_P3_SUFFIX_TEMPLATE),
            description="P2 simplifications + P1 termination guard.",
        ),
        PromptVariant(
            id="P4_example_fix",
            label="P4 (example key fix)",
            suffix=fill(_P4_SUFFIX_TEMPLATE),
            description="P2 with format example key fixed: {'input':...} -> {'code':...} for run_code.",
        ),
        PromptVariant(
            id="P5_stop_on_failure",
            label="P5 (stop on failure)",
            suffix=fill(_P5_SUFFIX_TEMPLATE),
            description="P4 with explicit stop rule after Attempt (3/3) or higher.",
        ),
    ]


PROMPT_VARIANTS: list[PromptVariant] = _build_prompt_variants()


# ══════════════════════════════════════════════════════════════════════════════
# ReActLoopSimulator
# ══════════════════════════════════════════════════════════════════════════════

class ReActLoopSimulator(ActionParserMixin):
    """
    Drives a ReAct conversation loop using litellm.completion() directly.
    Does NOT use LlamaIndex. One simulator instance can run multiple simulations.
    A new MockSandbox is created per simulate() call.
    """

    def __init__(self, evaluator: CodeEvaluator, slide_data: list[dict]) -> None:
        self._evaluator = evaluator
        self._slide_data = slide_data

    def simulate(
        self,
        model_cfg: dict,
        system_prompt: str,
        initial_user_message: str,
        prompt_id: str,
        run_idx: int,
        max_turns: int = 10,
    ) -> ReActRunResult:
        """
        Run one full ReAct simulation and return metrics.
        Initializes a fresh MockSandbox. Drives the conversation loop until:
          - Agent emits "Answer:" → terminated_correctly = True
          - Format violation → format_violation = True, break
          - Exception → error = str(e), break
          - max_turns exhausted → terminated_correctly = False
        """
        sandbox = MockSandbox(self._slide_data, self._evaluator)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": initial_user_message},
        ]

        n_turns = 0
        n_tool_calls = 0
        terminated_correctly = False
        loops_after_success = False
        hallucinated_failure = False
        format_violation = False
        file_confirmed = False
        last_run_code_success = False
        error = None

        for _ in range(max_turns):
            try:
                resp = litellm.completion(
                    model=model_cfg["name"],
                    messages=messages,
                    temperature=0,
                )
                assistant_text = resp.choices[0].message.content or ""
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                break

            # --- Hallucination check: at START of turn, before parsing current response ---
            if last_run_code_success and "Answer:" not in assistant_text:
                if self._is_hallucinated_failure(assistant_text):
                    hallucinated_failure = True
            last_run_code_success = False  # reset unconditionally

            messages.append({"role": "assistant", "content": assistant_text})
            n_turns += 1

            # Check for termination
            if self._has_answer(assistant_text):
                terminated_correctly = True
                break

            # Parse action
            parsed = self._parse_action(assistant_text)
            if parsed is None:
                format_violation = True
                break

            action_name, kwargs = parsed
            if action_name not in {"run_code", "list_files", "upload_file"}:
                format_violation = True
                break

            # Dispatch tool
            n_tool_calls += 1
            if action_name == "run_code":
                already_confirmed = file_confirmed
                code = kwargs.get("code", "")
                observation = self._dispatch_tool(action_name, kwargs, sandbox)
                last_run_code_success = "Successfully executed" in observation
                if already_confirmed:
                    loops_after_success = True
            elif action_name == "list_files":
                already_confirmed = file_confirmed
                observation = self._dispatch_tool(action_name, kwargs, sandbox)
                if "paper_summaries.pptx" in observation:
                    file_confirmed = True
                if already_confirmed:
                    loops_after_success = True
            else:  # upload_file
                already_confirmed = file_confirmed
                observation = self._dispatch_tool(action_name, kwargs, sandbox)
                if already_confirmed:
                    loops_after_success = True

            messages.append({"role": "user", "content": f"Observation: {observation}"})

        # first_code_correct
        if sandbox.run_code_calls:
            first_code_correct = self._evaluator.evaluate(sandbox.run_code_calls[0]).overall_correct
        else:
            first_code_correct = False

        return ReActRunResult(
            model_label=model_cfg["label"],
            prompt_id=prompt_id,
            run_idx=run_idx,
            terminated_correctly=terminated_correctly,
            n_turns=n_turns,
            n_tool_calls=n_tool_calls,
            loops_after_success=loops_after_success,
            first_code_correct=first_code_correct,
            hallucinated_failure=hallucinated_failure,
            format_violation=format_violation,
            error=error,
        )

    def _is_hallucinated_failure(self, text: str) -> bool:
        """Return True if text contains any hallucination keyword (case-insensitive)."""
        keywords = ["error", "fail", "not found", "invalid", "wrong"]
        text_lower = text.lower()
        return any(kw in text_lower for kw in keywords)


# ══════════════════════════════════════════════════════════════════════════════
# Model availability check
# ══════════════════════════════════════════════════════════════════════════════

def _check_model_available(model_cfg: dict) -> bool:
    """
    Ping the model with a minimal prompt to verify it is reachable before running.
    Returns True if the model responds with non-empty content within 30 seconds.
    """
    try:
        resp = litellm.completion(
            model=model_cfg["name"],
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=10,
            timeout=30,
        )
        return bool((resp.choices[0].message.content or "").strip())
    except Exception:
        return False


class BaseRunner:
    """Base class providing shared append logic for all runner classes."""

    def _append_result(self, result, path: str) -> None:
        """Append one result to a NDJSON file (one JSON object per line, crash-safe)."""
        with open(path, "a") as f:
            f.write(json.dumps(result.to_dict()) + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# ExperimentRunner
# ══════════════════════════════════════════════════════════════════════════════

class ExperimentRunner(BaseRunner):
    """
    Orchestrates all (model × prompt_variant × n_runs) combinations.
    Skips variants not in RUN_PROMPT_IDS if that config is set.
    Appends each result to RESULTS_PATH immediately after each run (crash-safe).
    """

    def __init__(
        self,
        models: list[dict],
        prompt_variants: list[PromptVariant],
        simulator: ReActLoopSimulator,
        initial_user_message: str,
        n_runs: int,
        max_turns: int,
        results_path: str,
    ) -> None:
        self._models = models
        self._prompt_variants = prompt_variants
        self._simulator = simulator
        self._initial_user_message = initial_user_message
        self._n_runs = n_runs
        self._max_turns = max_turns
        self._results_path = results_path

    def run_all(self) -> list[ReActRunResult]:
        all_results: list[ReActRunResult] = []

        for model_cfg in self._models:
            print(f"\n{'='*60}")
            print(f"Checking model: {model_cfg['label']} ({model_cfg['name']})")
            if not _check_model_available(model_cfg):
                print(f"  WARNING: model {model_cfg['label']} is not available — skipping.")
                continue
            print(f"  Model available.")

            for variant in self._prompt_variants:
                if RUN_PROMPT_IDS is not None and variant.id not in RUN_PROMPT_IDS:
                    continue

                system_prompt = SLIDE_GEN_PMT + variant.suffix

                for run_idx in range(self._n_runs):
                    print(f"  [{model_cfg['label']} / {variant.id} / run {run_idx}] running...",
                          end=" ", flush=True)
                    t0 = time.time()

                    result = self._simulator.simulate(
                        model_cfg=model_cfg,
                        system_prompt=system_prompt,
                        initial_user_message=self._initial_user_message,
                        prompt_id=variant.id,
                        run_idx=run_idx,
                        max_turns=self._max_turns,
                    )

                    elapsed = time.time() - t0
                    status = "OK" if result.terminated_correctly else (
                        "ERR" if result.error else (
                            "FMT" if result.format_violation else "TIMEOUT"
                        )
                    )
                    print(f"{status} | turns={result.n_turns} tools={result.n_tool_calls} "
                          f"loops={result.loops_after_success} "
                          f"halluc={result.hallucinated_failure} "
                          f"({elapsed:.1f}s)")

                    self._append_result(result, self._results_path)
                    all_results.append(result)

        return all_results


# ══════════════════════════════════════════════════════════════════════════════
# ResultReporter
# ══════════════════════════════════════════════════════════════════════════════

class ResultReporter:
    """
    Formats and prints experiment results as ASCII tables.
    One table per model, rows = prompt variants, columns = aggregated metrics.
    """

    def __init__(self, results: list[ReActRunResult]) -> None:
        self._results = results

    def _aggregate(self) -> dict:
        """
        Returns nested dict: {model_label: {prompt_id: {metric: value}}}.
        """
        grouped: dict = defaultdict(lambda: defaultdict(list))
        for r in self._results:
            grouped[r.model_label][r.prompt_id].append(r)

        agg = {}
        for model, variants in grouped.items():
            agg[model] = {}
            for pid, runs in variants.items():
                n = len(runs)
                agg[model][pid] = {
                    "terminated%":    round(sum(r.terminated_correctly for r in runs) / n * 100, 1),
                    "avg_turns":      round(sum(r.n_turns for r in runs) / n, 1),
                    "avg_tool_calls": round(sum(r.n_tool_calls for r in runs) / n, 1),
                    "loops%":         round(sum(r.loops_after_success for r in runs) / n * 100, 1),
                    "first_correct%": round(sum(r.first_code_correct for r in runs) / n * 100, 1),
                    "hallucinated%":  round(sum(r.hallucinated_failure for r in runs) / n * 100, 1),
                    "format_viol%":   round(sum(r.format_violation for r in runs) / n * 100, 1),
                    "n": n,
                }
        return agg

    def print_summary(self) -> None:
        agg = self._aggregate()
        cols = ["terminated%", "avg_turns", "avg_tool_calls", "loops%",
                "first_correct%", "hallucinated%", "format_viol%"]
        header = f"{'Variant':<28}" + "".join(f"{c:>16}" for c in cols)
        sep = "─" * len(header)

        for model, variants in agg.items():
            print(f"\nMODEL: {model}")
            print(sep)
            print(header)
            print(sep)
            for pid in variants.keys():
                if pid not in variants:
                    continue
                d = variants[pid]
                row = f"{pid:<28}" + "".join(
                    f"{d.get(c, 'N/A'):>16}" for c in cols
                )
                print(row)
            print(sep)



# ══════════════════════════════════════════════════════════════════════════════
# Error Behavior Sub-Experiment — Data structures
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ErrorBehaviorRunResult:
    """
    Metrics for one run of the error behavior sub-experiment.

    Attributes:
        model_label: Model identifier string.
        prompt_id: Prompt variant id (e.g., "P4_example_fix").
        scenario: "persistent_error" or "module_not_found".
        run_idx: 0-indexed run number.
        terminated_correctly: Agent emitted "Answer:" before MAX_TURNS.
        n_turns: Total LLM calls made.
        n_tool_calls: Total tool dispatches.
        error: Exception message if litellm raised. None otherwise.

        # Scenario A (persistent_error) specific
        reached_max_turns: True if MAX_TURNS exhausted without Answer:.
        gave_up_correctly: Answer: emitted + file not confirmed + answer text
            contains failure keywords (fail/error/unable/cannot/could not).
        hallucinated_success: Answer: emitted + file not confirmed + answer text
            contains success keywords (done/success/saved/created/generated).

        # Scenario B (module_not_found) specific
        generated_correct_pip: Code containing pip install python-pptx (or pptx)
            WITHOUT a leading ! was submitted at any point.
        generated_jupyter_pip: Code containing !pip install was submitted at any point.
        turn_of_pip_install: Turn index (1-based) of first correct pip install.
            -1 if never generated.
        task_completed: list_files confirmed paper_summaries.pptx exists.
    """
    model_label: str
    prompt_id: str
    scenario: str
    run_idx: int
    terminated_correctly: bool
    n_turns: int
    n_tool_calls: int
    error: Optional[str]
    # Scenario A
    reached_max_turns: bool
    gave_up_correctly: bool
    hallucinated_success: bool
    format_violation: bool
    # Scenario B
    generated_correct_pip: bool
    generated_jupyter_pip: bool
    turn_of_pip_install: int
    task_completed: bool
    # Evidence fields (for report verification)
    answer_text: Optional[str]    # full Answer: response text (Scenario A classification evidence)
    pip_code_sample: Optional[str]  # first correct pip install code string (Scenario B evidence)

    def to_dict(self) -> dict:
        return asdict(self)


# ══════════════════════════════════════════════════════════════════════════════
# Error Behavior Sub-Experiment — Sandboxes
# ══════════════════════════════════════════════════════════════════════════════

class PersistentErrorSandbox:
    """
    Scenario A sandbox: always returns AttributeError regardless of code.
    Observation includes attempt counter (N/max_attempts).
    Counter increments beyond max_attempts (e.g., (4/3)) — this is intentional,
    showing the model it has exceeded the limit.

    Create one instance per run. Do NOT reuse across runs.
    """

    def __init__(self, max_attempts: int = 3) -> None:
        self._max_attempts = max_attempts
        self._attempt = 0
        self.run_code_calls: list[str] = []
        self.list_files_calls: int = 0

    def run_code(self, code: str) -> str:
        self.run_code_calls.append(code)
        self._attempt += 1
        limit_reached = self._attempt >= self._max_attempts
        label = f"Attempt ({self._attempt}/{self._max_attempts}) failed."
        limit_tag = " LIMIT REACHED." if limit_reached else ""
        return (
            f"{label}{limit_tag}\n"
            f"ERROR (exit_code=1):\n"
            f"AttributeError: 'str' object has no attribute 'part'"
        )

    def list_files(self, remote_dir: str = "/sandbox") -> str:
        self.list_files_calls += 1
        return "(no files in /sandbox)"

    def upload_file(self, local_file_path: str) -> str:
        filename = Path(local_file_path).name
        return f"Uploaded {local_file_path} → /sandbox/{filename}"


class ModuleNotFoundSandbox:
    """
    Scenario B sandbox: returns ModuleNotFoundError until pptx is installed.

    Behaviour:
    - Code containing !pip → SyntaxError (Jupyter syntax not valid here).
    - Code containing pip install python-pptx (or pptx) without ! → install success,
      sets _pptx_installed = True.
    - Code without pip install and _pptx_installed=False → ModuleNotFoundError.
    - Code without pip install and _pptx_installed=True → unconditional success
      (sets _file_exists=True; keeps Scenario B focused on install diagnosis only).

    Create one instance per run. Do NOT reuse across runs.
    """

    def __init__(self) -> None:
        self._pptx_installed = False
        self._file_exists = False
        self.run_code_calls: list[str] = []
        self.list_files_calls: int = 0

    def run_code(self, code: str) -> str:
        self.run_code_calls.append(code)

        # !pip — Jupyter syntax, SyntaxError in a Python script
        if re.search(r'!pip\s+install', code):
            return (
                "ERROR (exit_code=1):\n"
                "SyntaxError: invalid syntax "
                "(!pip is Jupyter notebook syntax, not valid in a Python script)"
            )

        # correct pip install (no leading !) — matches both:
        #   subprocess.run(['pip', 'install', 'python-pptx'])
        #   pip install python-pptx  (direct shell-style in code string)
        if re.search(r"""(?<!!)pip['",\s]+install['",\s]+(python-pptx|pptx)""", code):
            self._pptx_installed = True
            return "Successfully installed python-pptx-1.0.2"

        # pptx not installed yet
        if not self._pptx_installed:
            return (
                "ERROR (exit_code=1):\n"
                "ModuleNotFoundError: No module named 'pptx'"
            )

        # pptx installed — unconditional success (scope: only test install diagnosis)
        self._file_exists = True
        return "Successfully executed. /sandbox/paper_summaries.pptx created."

    def list_files(self, remote_dir: str = "/sandbox") -> str:
        self.list_files_calls += 1
        if self._file_exists:
            return "/sandbox/paper_summaries.pptx"
        return "(no files in /sandbox)"

    def upload_file(self, local_file_path: str) -> str:
        filename = Path(local_file_path).name
        return f"Uploaded {local_file_path} → /sandbox/{filename}"


# ══════════════════════════════════════════════════════════════════════════════
# Error Behavior Sub-Experiment — Simulator
# ══════════════════════════════════════════════════════════════════════════════

class ErrorBehaviorSimulator(ActionParserMixin):
    """
    Drives a ReAct loop for error behavior sub-experiments.
    Uses PersistentErrorSandbox (Scenario A) or ModuleNotFoundSandbox (Scenario B).
    Does NOT use LlamaIndex. Direct litellm.completion() loop.
    """

    def simulate(
        self,
        model_cfg: dict,
        system_prompt: str,
        initial_user_message: str,
        prompt_id: str,
        scenario: str,              # "persistent_error" or "module_not_found"
        run_idx: int,
        max_turns: int = 10,
    ) -> ErrorBehaviorRunResult:
        """
        Run one full simulation and return metrics.

        For Scenario A: uses PersistentErrorSandbox(max_attempts=3).
        For Scenario B: uses ModuleNotFoundSandbox().

        Action parsing: identical logic to ReActLoopSimulator._parse_action.
        Tool dispatch: run_code, list_files, upload_file.
        Valid tools: same as main experiment.

        Hallucination keywords for gave_up_correctly:
            "fail", "error", "unable", "cannot", "could not"  (case-insensitive)
        Hallucination keywords for hallucinated_success:
            "done", "success", "saved", "created", "generated"  (case-insensitive)
        Both checks only applied when Answer: is present AND file not confirmed.

        pip detection for Scenario B:
            generated_correct_pip: matches pip install python-pptx/pptx without leading !
            generated_jupyter_pip: matches !pip install
            turn_of_pip_install: 1-based turn index of first correct pip install (-1 if never)
        """
        if scenario == "persistent_error":
            sandbox = PersistentErrorSandbox(max_attempts=PERSISTENT_ERROR_MAX_ATTEMPTS)
        else:
            sandbox = ModuleNotFoundSandbox()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": initial_user_message},
        ]

        n_turns = 0
        n_tool_calls = 0
        terminated_correctly = False
        file_confirmed = False
        error = None
        # Scenario A
        reached_max_turns = False
        gave_up_correctly = False
        hallucinated_success = False
        format_violation = False
        answer_text: Optional[str] = None
        # Scenario B
        generated_correct_pip = False
        generated_jupyter_pip = False
        turn_of_pip_install = -1
        pip_code_sample: Optional[str] = None

        for _ in range(max_turns):
            try:
                resp = litellm.completion(
                    model=model_cfg["name"],
                    messages=messages,
                    temperature=0,
                )
                assistant_text = resp.choices[0].message.content or ""
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                break

            messages.append({"role": "assistant", "content": assistant_text})
            n_turns += 1

            if "Answer:" in assistant_text:
                terminated_correctly = True
                answer_text = assistant_text  # store for report verification
                # classify the answer
                if not file_confirmed:
                    ans_lower = assistant_text.lower()
                    if any(kw in ans_lower for kw in ["fail", "error", "unable", "cannot", "could not"]):
                        gave_up_correctly = True
                    elif any(kw in ans_lower for kw in ["done", "success", "saved", "created", "generated"]):
                        hallucinated_success = True
                break

            parsed = self._parse_action(assistant_text)
            if parsed is None:
                format_violation = True
                break

            action_name, kwargs = parsed
            if action_name not in {"run_code", "list_files", "upload_file"}:
                format_violation = True
                break

            n_tool_calls += 1

            if action_name == "run_code":
                code = kwargs.get("code", "")
                # Scenario B pip detection
                if re.search(r"""(?<!!)pip['",\s]+install['",\s]+(python-pptx|pptx)""", code):
                    if not generated_correct_pip:
                        generated_correct_pip = True
                        turn_of_pip_install = n_turns
                        pip_code_sample = code  # store first correct pip code for report verification
                if re.search(r'!pip\s+install', code):
                    generated_jupyter_pip = True
                observation = self._dispatch_tool(action_name, kwargs, sandbox)

            elif action_name == "list_files":
                observation = self._dispatch_tool(action_name, kwargs, sandbox)
                if "paper_summaries.pptx" in observation:
                    file_confirmed = True

            else:
                observation = self._dispatch_tool(action_name, kwargs, sandbox)

            messages.append({"role": "user", "content": f"Observation: {observation}"})

        else:
            # loop exhausted without break
            reached_max_turns = True

        task_completed = file_confirmed

        return ErrorBehaviorRunResult(
            model_label=model_cfg["label"],
            prompt_id=prompt_id,
            scenario=scenario,
            run_idx=run_idx,
            terminated_correctly=terminated_correctly,
            n_turns=n_turns,
            n_tool_calls=n_tool_calls,
            error=error,
            reached_max_turns=reached_max_turns,
            gave_up_correctly=gave_up_correctly,
            hallucinated_success=hallucinated_success,
            format_violation=format_violation,
            generated_correct_pip=generated_correct_pip,
            generated_jupyter_pip=generated_jupyter_pip,
            turn_of_pip_install=turn_of_pip_install,
            task_completed=task_completed,
            answer_text=answer_text,
            pip_code_sample=pip_code_sample,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Error Behavior Sub-Experiment — Runner
# ══════════════════════════════════════════════════════════════════════════════

class ErrorBehaviorRunner(BaseRunner):
    """
    Orchestrates all (model × scenario × prompt_variant × n_runs) combinations
    for the error behavior sub-experiment.

    Scenario A: P4 + P5, persistent error sandbox.
    Scenario B: P4 only, module-not-found sandbox.

    Appends each result to ERROR_RESULTS_PATH immediately (crash-safe NDJSON).
    """

    # scenario → which prompt_ids to run
    SCENARIO_PROMPTS = {
        "persistent_error":  ["P4_example_fix", "P5_stop_on_failure"],
        "module_not_found":  ["P4_example_fix"],
    }

    def __init__(
        self,
        models: list[dict],
        prompt_variants: list[PromptVariant],
        simulator: ErrorBehaviorSimulator,
        n_runs: int,
        max_turns: int,
        results_path: str,
        initial_user_message: str,
        scenario_b_user_message: str,
        scenario_prompt_overrides: Optional[dict[str, str]] = None,
    ) -> None:
        self._models = models
        self._prompt_variants = {v.id: v for v in prompt_variants}
        self._simulator = simulator
        self._n_runs = n_runs
        self._max_turns = max_turns
        self._results_path = results_path
        self._scenario_messages = {
            "persistent_error": initial_user_message,
            "module_not_found": scenario_b_user_message,
        }
        self._scenario_prompt_overrides = scenario_prompt_overrides or {}

    def run_all(self) -> list[ErrorBehaviorRunResult]:
        all_results: list[ErrorBehaviorRunResult] = []

        for model_cfg in self._models:
            print(f"\n{'='*60}")
            print(f"Checking model: {model_cfg['label']}")
            if not _check_model_available(model_cfg):
                print(f"  WARNING: {model_cfg['label']} not available — skipping.")
                continue
            print(f"  Model available.")

            for scenario, prompt_ids in self.SCENARIO_PROMPTS.items():
                for pid in prompt_ids:
                    if pid not in self._prompt_variants:
                        print(f"  WARNING: prompt {pid} not found — skipping.")
                        continue
                    variant = self._prompt_variants[pid]
                    system_prompt = self._scenario_prompt_overrides.get(scenario) or (SLIDE_GEN_PMT + variant.suffix)
                    user_msg = self._scenario_messages[scenario]

                    for run_idx in range(self._n_runs):
                        print(
                            f"  [error/{scenario[:4]} / {pid} / {model_cfg['label']} / run {run_idx}]"
                            f" running...",
                            end=" ", flush=True,
                        )
                        t0 = time.time()
                        result = self._simulator.simulate(
                            model_cfg=model_cfg,
                            system_prompt=system_prompt,
                            initial_user_message=user_msg,
                            prompt_id=pid,
                            scenario=scenario,
                            run_idx=run_idx,
                            max_turns=self._max_turns,
                        )
                        elapsed = time.time() - t0

                        if scenario == "persistent_error":
                            status = (
                                "STOP" if result.gave_up_correctly else
                                "HALLUC" if result.hallucinated_success else
                                "LOOP" if result.reached_max_turns else
                                "OK"
                            )
                            extra = f"turns={result.n_turns} reached_max={result.reached_max_turns}"
                        else:
                            status = "PIP✓" if result.generated_correct_pip else (
                                "!PIP" if result.generated_jupyter_pip else "NO_PIP"
                            )
                            extra = (
                                f"pip_turn={result.turn_of_pip_install} "
                                f"done={result.task_completed}"
                            )

                        print(f"{status} | {extra} ({elapsed:.1f}s)")
                        self._append_result(result, self._results_path)
                        all_results.append(result)

        return all_results


# ══════════════════════════════════════════════════════════════════════════════
# Error Behavior Sub-Experiment — Reporter
# ══════════════════════════════════════════════════════════════════════════════

class ErrorBehaviorReporter:
    """
    Formats error behavior experiment results as ASCII and Markdown tables.
    One table per scenario, rows = (model × prompt_id), columns = aggregated metrics.
    """

    def __init__(self, results: list[ErrorBehaviorRunResult]) -> None:
        self._results = results

    def _aggregate(self) -> dict:
        # group by (scenario, model_label, prompt_id)
        grouped: dict = defaultdict(list)
        for r in self._results:
            grouped[(r.scenario, r.model_label, r.prompt_id)].append(r)
        return grouped

    def print_summary(self) -> None:
        grouped = self._aggregate()

        for scenario in ["persistent_error", "module_not_found"]:
            keys = [k for k in grouped if k[0] == scenario]
            if not keys:
                continue

            print(f"\nSCENARIO: {scenario}")
            if scenario == "persistent_error":
                cols = ["terminated%", "reached_max%", "gave_up%", "hallucinated%", "format_viol%", "avg_turns"]
                header = f"{'Model/Prompt':<40}" + "".join(f"{c:>16}" for c in cols)
            else:
                cols = ["correct_pip%", "jupyter_pip%", "avg_pip_turn", "task_done%"]
                header = f"{'Model/Prompt':<40}" + "".join(f"{c:>16}" for c in cols)

            sep = "─" * len(header)
            print(sep)
            print(header)
            print(sep)

            for (sc, model, pid) in sorted(keys):
                runs = grouped[(sc, model, pid)]
                n = len(runs)
                label = f"{model} / {pid}"
                if scenario == "persistent_error":
                    vals = [
                        round(sum(r.terminated_correctly for r in runs) / n * 100, 1),
                        round(sum(r.reached_max_turns for r in runs) / n * 100, 1),
                        round(sum(r.gave_up_correctly for r in runs) / n * 100, 1),
                        round(sum(r.hallucinated_success for r in runs) / n * 100, 1),
                        round(sum(r.format_violation for r in runs) / n * 100, 1),
                        round(sum(r.n_turns for r in runs) / n, 1),
                    ]
                else:
                    pip_turns = [r.turn_of_pip_install for r in runs if r.turn_of_pip_install != -1]
                    avg_pip = round(sum(pip_turns) / len(pip_turns), 1) if pip_turns else -1
                    vals = [
                        round(sum(r.generated_correct_pip for r in runs) / n * 100, 1),
                        round(sum(r.generated_jupyter_pip for r in runs) / n * 100, 1),
                        avg_pip,
                        round(sum(r.task_completed for r in runs) / n * 100, 1),
                    ]
                row = f"{label:<40}" + "".join(f"{v:>16}" for v in vals)
                print(row)
            print(sep)



# ══════════════════════════════════════════════════════════════════════════════
# Error Behavior Sub-Experiment — Entrypoint function
# ══════════════════════════════════════════════════════════════════════════════

def run_error_behavior_experiment() -> None:
    """Run the error behavior sub-experiment (Scenario A + B)."""
    simulator = ErrorBehaviorSimulator()
    _scenario_b_suffix = _P4_SUFFIX_TEMPLATE.replace("{tool_desc}", TOOL_DESC_NO_PPTX_CLAIM).replace("{tool_names}", TOOL_NAMES)
    _scenario_b_system_prompt = SLIDE_GEN_PMT + _scenario_b_suffix
    runner = ErrorBehaviorRunner(
        models=MODELS,
        prompt_variants=PROMPT_VARIANTS,
        simulator=simulator,
        n_runs=ERROR_N_RUNS,
        max_turns=ERROR_MAX_TURNS,
        results_path=ERROR_RESULTS_PATH,
        initial_user_message=INITIAL_USER_MESSAGE,
        scenario_b_user_message=INITIAL_USER_MESSAGE,
        scenario_prompt_overrides={"module_not_found": _scenario_b_system_prompt},
    )

    print("\n" + "=" * 60)
    print("ERROR BEHAVIOR SUB-EXPERIMENT")
    print(f"N_RUNS={ERROR_N_RUNS}  MAX_TURNS={ERROR_MAX_TURNS}")
    print(f"Scenario A prompts: {ErrorBehaviorRunner.SCENARIO_PROMPTS['persistent_error']}")
    print(f"Scenario B prompts: {ErrorBehaviorRunner.SCENARIO_PROMPTS['module_not_found']}")
    print(f"Models: {[m['label'] for m in MODELS]}")
    print("=" * 60)

    results = runner.run_all()

    if not results:
        print("\nNo error behavior results collected.")
        return

    reporter = ErrorBehaviorReporter(results)
    reporter.print_summary()
    print(f"\nError behavior results appended to: {ERROR_RESULTS_PATH}")


# ══════════════════════════════════════════════════════════════════════════════
# Entrypoint
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    evaluator = CodeEvaluator()
    simulator = ReActLoopSimulator(evaluator=evaluator, slide_data=SLIDE_DATA)

    active_variants = PROMPT_VARIANTS
    if RUN_PROMPT_IDS is not None:
        active_variants = [v for v in PROMPT_VARIANTS if v.id in RUN_PROMPT_IDS]

    runner = ExperimentRunner(
        models=MODELS,
        prompt_variants=active_variants,
        simulator=simulator,
        initial_user_message=INITIAL_USER_MESSAGE,
        n_runs=N_RUNS,
        max_turns=MAX_TURNS,
        results_path=RESULTS_PATH,
    )

    print("=" * 60)
    print("SLIDE GEN REACT SUFFIX ENGINEERING EXPERIMENT")
    print(f"N_RUNS={N_RUNS}  MAX_TURNS={MAX_TURNS}")
    print(f"Variants: {[v.id for v in active_variants]}")
    print(f"Models:   {[m['label'] for m in MODELS]}")
    print("=" * 60)

    results = runner.run_all()

    if results:
        reporter = ResultReporter(results)
        reporter.print_summary()
        print(f"\nResults appended to: {RESULTS_PATH}")
    else:
        print("\nNo main experiment results collected.")

    error_exp_ids = {
        pid
        for pids in ErrorBehaviorRunner.SCENARIO_PROMPTS.values()
        for pid in pids
    }
    active_ids = {v.id for v in active_variants} if RUN_PROMPT_IDS is not None else error_exp_ids
    if active_ids & error_exp_ids:
        run_error_behavior_experiment()


if __name__ == "__main__":
    main()
