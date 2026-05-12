import type { UIMessage } from 'ai'

export type CanvasPhase = 'empty' | 'processing' | 'hitl' | 'complete'

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

export interface PaperSlideOutline {
  paper_title: string
  paper_authors: string
  paper_year: number
  content_slides: Array<{
    title: string
    content: Array<{ text: string; level: number }>
  }>
}
