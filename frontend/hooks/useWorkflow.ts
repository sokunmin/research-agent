'use client'

import { useState } from 'react'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import type { CanvasPhase, FinalResult, HitlRequest, ResearchUIMessage, StepMessage } from '@/lib/types'
import { submitHitlFeedbackApi } from '@/lib/api'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:8000'

export function useWorkflow() {
  const [workflowId,      setWorkflowId]      = useState<string | null>(null)
  const [stepMessages,    setStepMessages]    = useState<StepMessage[]>([])
  const [reasoningChunks, setReasoningChunks] = useState<string>('')
  const [hitlRequest,     setHitlRequest]     = useState<HitlRequest | null>(null)
  const [hitlCount,       setHitlCount]       = useState(0)
  const [paperTotal,      setPaperTotal]      = useState<number | null>(null)
  const [finalResult,     setFinalResult]     = useState<FinalResult | null>(null)

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
          break
        case 'data-step-progress': {
          const data = part.data as { sender: string; message: string }
          // Mark ALL previous messages as done — pipeline is sequential, so any new
          // step starting means everything before it has completed
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
        case 'data-request-user-input':
          setHitlCount(prev => prev + 1)
          setHitlRequest(part.data as HitlRequest)
          break
        case 'data-final-result':
          setStepMessages(prev => prev.map(m => ({ ...m, status: 'done' as const })))
          setFinalResult(part.data as FinalResult)
          break
      }
    },
  })

  // Phase is derived from state — never set manually to avoid synchronization bugs
  const canvasPhase: CanvasPhase =
    finalResult  ? 'complete'   :
    hitlRequest  ? 'hitl'       :
    workflowId   ? 'processing' :
                   'empty'

  // Input disabled while workflow is actively running; enabled in empty + complete
  const isInputDisabled = canvasPhase === 'processing' || canvasPhase === 'hitl'

  // Clear hitlRequest after submit so canvasPhase returns to 'processing'
  const submitHitlFeedback = async (approved: boolean, feedback: string) => {
    if (!workflowId) return
    await submitHitlFeedbackApi(BACKEND_URL, workflowId, approved, feedback)
    setHitlRequest(null)
  }

  const reset = () => {
    setWorkflowId(null)
    setStepMessages([])
    setReasoningChunks('')
    setHitlRequest(null)
    setHitlCount(0)
    setPaperTotal(null)
    setFinalResult(null)
  }

  return {
    messages, sendMessage, chatStatus: status,
    workflowId, stepMessages, reasoningChunks, hitlRequest, hitlCount, paperTotal, finalResult,
    canvasPhase, isInputDisabled,
    submitHitlFeedback, reset,
  }
}
