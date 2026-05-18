'use client'

import { useState } from 'react'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import type { CanvasPhase, FinalResult, HitlRequest, NoResultsInfo, PaperCandidate, ResearchUIMessage, SearchParams, StepMessage, WorkflowPhase } from '@/lib/types'
import { submitHitlFeedbackApi, submitPaperQuestionApi, submitPaperSelectionApi } from '@/lib/api'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:8000'

const CANVAS_PHASE: Record<WorkflowPhase, CanvasPhase> = {
  idle:                       'empty',
  running:                    'processing',
  'awaiting-paper-selection': 'paper-selection',
  'awaiting-hitl':            'hitl',
  complete:                   'complete',
}

const INPUT_LOCKED = new Set<WorkflowPhase>(['running', 'awaiting-hitl'])

export function useWorkflow() {
  const [workflowId,        setWorkflowId]        = useState<string | null>(null)
  const [workflowPhase,     setWorkflowPhase]     = useState<WorkflowPhase>('idle')
  const [hasConversation,   setHasConversation]   = useState(false)
  const [stepMessages,    setStepMessages]    = useState<StepMessage[]>([])
  const [reasoningChunks, setReasoningChunks] = useState<string>('')
  const [hitlRequest,     setHitlRequest]     = useState<HitlRequest | null>(null)
  const [hitlCount,       setHitlCount]       = useState(0)
  const [paperTotal,      setPaperTotal]      = useState<number | null>(null)
  const [finalResult,     setFinalResult]     = useState<FinalResult | null>(null)
  const [paperCandidates,    setPaperCandidates]    = useState<PaperCandidate[] | null>(null)
  const [paperSearchParams,  setPaperSearchParams]  = useState<SearchParams | null>(null)
  const [noResultsInfo,      setNoResultsInfo]      = useState<NoResultsInfo | null>(null)
  const [paperQAHistory,     setPaperQAHistory]      = useState<Array<{question: string; answer: string}>>([])
  const [supervisorMessage,  setSupervisorMessage]   = useState<string | null>(null)

  // AI SDK v5 status: 'submitted' | 'streaming' | 'ready' | 'error' (NO 'idle')
  const { messages, sendMessage, status } = useChat<ResearchUIMessage>({
    transport: new DefaultChatTransport({
      api: `${BACKEND_URL}/run-slide-gen`,
      // FastAPI expects {"query":"..."} — not the default AI SDK messages array payload
      // In AI SDK v5 the user message text lives in parts[0].text, not .content
      prepareSendMessagesRequest: ({ messages }) => {
        const lastMsg = messages[messages.length - 1]
        const query = lastMsg.parts?.find((p: { type: string }) => p.type === 'text') as { type: 'text'; text: string } | undefined
        return { body: { query: query?.text ?? '' } }
      },
    }),
    onData: (part) => {
      switch (part.type) {
        case 'data-workflow-id':
          setWorkflowId((part.data as { workflow_id: string }).workflow_id)
          setWorkflowPhase('running')
          setHasConversation(true)
          setSupervisorMessage(null)
          setNoResultsInfo(null)
          setStepMessages([])
          setReasoningChunks('')
          setPaperQAHistory([])
          break
        case 'data-step-progress': {
          const data = part.data as { sender: string; message: string }
          setStepMessages(prev => [
            ...prev.map(m => ({ ...m, status: 'done' as const })),
            {
              id: crypto.randomUUID(),
              sender: data.sender,
              message: data.message,
              timestamp: new Date(),
              status: 'running' as const,
            },
          ])
          break
        }
        case 'data-reasoning': {
          const data = part.data as { message: string }
          setReasoningChunks(prev => prev + data.message + '\n')
          break
        }
        case 'data-paper-total':
          setPaperTotal((part.data as { total: number }).total)
          break

        case 'data-paper-candidates':
          setPaperCandidates(part.data.candidates)
          setPaperSearchParams(part.data.search_params)
          setNoResultsInfo(null)
          setWorkflowPhase('awaiting-paper-selection')
          break

        case 'data-no-results':
          setNoResultsInfo({ message: part.data.message, suggestions: part.data.suggestions })
          setPaperCandidates(null)
          setWorkflowId(null)
          setWorkflowPhase('idle')
          break

        case 'data-supervisor-response':
          setSupervisorMessage(part.data.message)
          setWorkflowId(null)
          setWorkflowPhase('idle')
          break

        case 'data-request-user-input':
          setHitlCount(prev => prev + 1)
          setHitlRequest(part.data as HitlRequest)
          setWorkflowPhase('awaiting-hitl')
          break

        case 'data-final-result':
          setStepMessages(prev => prev.map(m => ({ ...m, status: 'done' as const })))
          setFinalResult(part.data as FinalResult)
          setWorkflowPhase('complete')
          break
      }
    },
  })

  const canvasPhase    = CANVAS_PHASE[workflowPhase]
  const isInputDisabled = INPUT_LOCKED.has(workflowPhase)

  // Clear hitlRequest after submit so canvasPhase returns to 'processing'
  const submitHitlFeedback = async (approved: boolean, feedback: string) => {
    if (!workflowId) return
    await submitHitlFeedbackApi(BACKEND_URL, workflowId, approved, feedback)
    setHitlRequest(null)
    setWorkflowPhase('running')
  }

  const submitPaperSelection = async (action: 'select' | 'abort', selectedIds: string[] = []) => {
    if (!workflowId) return
    try {
      await submitPaperSelectionApi(BACKEND_URL, workflowId, action, selectedIds)
    } catch {
      reset()
      return
    }
    if (action === 'abort') {
      reset()
    } else {
      setPaperCandidates(null)
      setWorkflowPhase('running')
    }
  }

  const submitPaperQuestion = async (message: string): Promise<void> => {
    if (!workflowId) return
    setPaperQAHistory(prev => [...prev, { question: message, answer: '' }])
    const answer = await submitPaperQuestionApi(BACKEND_URL, workflowId, message)
    setPaperQAHistory(prev => {
      const next = [...prev]
      next[next.length - 1] = { question: message, answer }
      return next
    })
  }

  const reset = () => {
    setWorkflowId(null)
    setWorkflowPhase('idle')
    setHasConversation(false)
    setStepMessages([])
    setReasoningChunks('')
    setHitlRequest(null)
    setHitlCount(0)
    setPaperTotal(null)
    setFinalResult(null)
    setPaperCandidates(null)
    setPaperSearchParams(null)
    setNoResultsInfo(null)
    setPaperQAHistory([])
    setSupervisorMessage(null)
  }

  return {
    messages, sendMessage, chatStatus: status,
    workflowId, stepMessages, reasoningChunks, hitlRequest, hitlCount, paperTotal, finalResult,
    canvasPhase, isInputDisabled,
    submitHitlFeedback, reset,
    paperCandidates, paperSearchParams, noResultsInfo, paperQAHistory,
    submitPaperSelection, submitPaperQuestion,
    supervisorMessage, hasConversation,
  }
}
