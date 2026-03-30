import asyncio
import json
import random
import string
from pathlib import Path

import click
from llama_index.core import Settings, SimpleDirectoryReader
from llama_index.core.agent.workflow import ReActAgent
from llama_index.core.output_parsers import PydanticOutputParser
from llama_index.core.tools import FunctionTool

from config import settings
from prompts.prompts import (
    SLIDE_GEN_PMT,
    REACT_PROMPT_SUFFIX,
    SUMMARY2OUTLINE_PMT,
    AUGMENT_LAYOUT_PMT,
    SLIDE_VALIDATION_PMT,
    SLIDE_MODIFICATION_PMT,
    MODIFY_SUMMARY2OUTLINE_PMT,
)
from services.llms import llm, new_llm, new_fast_llm, vlm
from services.embeddings import embedder
import logging
import sys
from llama_index.core import PromptTemplate
from llama_index.core.workflow import (
    Context,
    StartEvent,
    StopEvent,
    Workflow,
    step,
)

from utils.tools import get_all_layouts_info
import inspect
from utils.file_processing import pptx2images
from agent_workflows.events import *

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

Settings.llm = llm
Settings.embed_model = embedder


class ResearchAgentWorkflow(Workflow):
    summary_gen_workflow = None
    slide_gen_workflow = None
