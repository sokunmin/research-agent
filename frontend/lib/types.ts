import type { UIMessage } from 'ai'

export type CanvasPhase = 'empty' | 'processing' | 'paper-selection' | 'hitl' | 'complete'

export type WorkflowPhase =
  | 'idle'
  | 'running'
  | 'awaiting-paper-selection'
  | 'awaiting-hitl'
  | 'complete'

// Keys must match the "data-{key}" type strings emitted by FastAPI _sse()
export type ResearchUIMessage = UIMessage<
  never,
  {
    'workflow-id':        { workflow_id: string }
    'step-progress':      { sender: string; message: string }
    'reasoning':          { sender: string; message: string }
    'request-user-input': {
      eid: string
      summary: string
      paper_outline: PaperSlideOutline
      message: string
    }
    'paper-total': { total: number }
    'paper-candidates':   { candidates: PaperCandidate[]; search_params: SearchParams }
    'no-results':         { message: string; suggestions: string[] }
    'paper-answer':       { answer: string }
    'supervisor-response': { message: string }
    'final-result': {
      download_pptx_url: string
      download_pdf_url: string
    }
  }
>

export interface StepMessage {
  id: string
  sender: string
  message: string
  timestamp: Date
  status: 'running' | 'done'
}

export interface HitlRequest {
  eid: string
  summary: string
  paper_outline: PaperSlideOutline
  message: string
}

export interface FinalResult {
  download_pptx_url: string
  download_pdf_url: string
}

export interface PaperCandidate {
  entry_id: string
  title: string
  authors: string
  year: number
  abstract_summary: string
  similarity_score: number
  cited_by_count: number | null
}

export interface SearchParams {
  clean_topic: string
  year_window: number
  min_citations: number
}

export interface NoResultsInfo {
  message: string
  suggestions: string[]
}

export interface PaperSlideOutline {
  paper_title: string
  paper_authors: string
  paper_year: number
  content_slides: Array<{
    title: string
    content: Array<{ text: string; level: number }>
  }>
}
