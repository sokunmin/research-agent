'use client'

import { useEffect, useRef, useState } from 'react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { HitlRequest, ResearchUIMessage, StepMessage } from '@/lib/types'
import { MessageBubble } from './MessageBubble'
import { ProgressMessage } from './ProgressMessage'
import { ReasoningMessage } from './ReasoningMessage'
import { HitlForm } from './HitlForm'
import { PaperSelectCard } from './PaperSelectCard'
import type { PaperCandidate, SearchParams, NoResultsInfo } from '@/lib/types'

interface ChatThreadProps {
  messages: ResearchUIMessage[]
  stepMessages: StepMessage[]
  reasoningChunks: string
  hitlRequest: HitlRequest | null
  onHitlSubmit: (approved: boolean, feedback: string) => Promise<void>
  paperCandidates: PaperCandidate[] | null
  paperSearchParams: SearchParams | null
  paperQAHistory: Array<{question: string; answer: string}>
  noResultsInfo: NoResultsInfo | null
  onGenerate: (ids: string[]) => void
  onNewSearch: () => void
  supervisorMessage: string | null
  hasConversation: boolean
}

// ⚠️ All data-* parts are transient: true — they never appear in message.parts.
// The messages array from useChat only contains the user's text message.
// Step progress, reasoning, and HITL come from separate state in useWorkflow.
export function ChatThread({ messages, stepMessages, reasoningChunks, hitlRequest, onHitlSubmit, paperCandidates, paperSearchParams, paperQAHistory, noResultsInfo, onGenerate, onNewSearch, supervisorMessage, hasConversation }: ChatThreadProps) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const [stepsOpen, setStepsOpen] = useState(true)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [stepMessages, reasoningChunks, hitlRequest, paperCandidates, paperQAHistory, supervisorMessage])

  const userMessage = [...messages].reverse().find(m => m.role === 'user')
  const isRunning = stepMessages.some(m => m.status === 'running')
  const doneCount = stepMessages.filter(m => m.status === 'done').length
  const totalCount = stepMessages.length

  const stepsSummary = isRunning
    ? `Working... (${totalCount} steps)`
    : totalCount > 0
      ? `Completed (${totalCount} steps)`
      : ''

  return (
    <ScrollArea className="flex-1 min-h-0 px-3">
      <div className="py-3 space-y-1">
        {/* 1. User query bubble */}
        {userMessage && hasConversation && (
          <MessageBubble
            role="user"
            text={userMessage.parts?.find((p: { type: string }) => p.type === 'text') as { type: 'text'; text: string } | undefined
              ? (userMessage.parts.find((p: { type: string }) => p.type === 'text') as { type: 'text'; text: string }).text
              : ''}
          />
        )}

        {/* 2. Step progress — collapsible, default open */}
        {stepMessages.length > 0 && (
          <Collapsible open={stepsOpen} onOpenChange={setStepsOpen} className="mt-2">
            <CollapsibleTrigger className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors py-1">
              <span>{stepsOpen ? '▾' : '▸'}</span>
              {isRunning
                ? <span className="block h-2 w-2 rounded-full bg-white animate-pulse" />
                : <span className="text-green-400 text-xs">✓</span>}
              <span>{stepsSummary}</span>
            </CollapsibleTrigger>
            <CollapsibleContent className="pl-2 border-l border-border mt-1 space-y-0.5">
              {stepMessages.map(msg => (
                <ProgressMessage key={msg.id} stepMessage={msg} />
              ))}
            </CollapsibleContent>
          </Collapsible>
        )}

        {/* 3. Reasoning collapsible (from reasoningChunks state) */}
        {reasoningChunks && <ReasoningMessage text={reasoningChunks} />}

        {/* 4. HITL form inline — appears when hitlRequest is set */}
        {hitlRequest && <HitlForm request={hitlRequest} onSubmit={onHitlSubmit} />}

        {/* No-results error bubble */}
        {noResultsInfo && (
          <div className="flex justify-start">
            <div className="rounded-lg border bg-destructive/10 p-3 text-sm space-y-1 max-w-sm">
              <p className="font-medium text-destructive">{noResultsInfo.message}</p>
              <ul className="list-disc list-inside text-muted-foreground text-xs space-y-0.5">
                {noResultsInfo.suggestions.map((s, i) => <li key={i}>{s}</li>)}
              </ul>
            </div>
          </div>
        )}

        {/* Supervisor response bubble (greeting / ambiguous / out_of_scope) */}
        {supervisorMessage && (
          <div className="flex justify-start">
            <div className="rounded-lg bg-muted px-3 py-2 text-sm max-w-sm">
              {supervisorMessage}
            </div>
          </div>
        )}

        {/* Paper selection card */}
        {paperCandidates && paperSearchParams && (
          <div className="flex justify-start">
            <PaperSelectCard
              candidates={paperCandidates}
              searchParams={paperSearchParams}
              onGenerate={onGenerate}
              onNewSearch={onNewSearch}
            />
          </div>
        )}

        {/* Paper Q&A question + answer bubbles */}
        {paperQAHistory.map((qa, i) => (
          <div key={i} className="space-y-1">
            <MessageBubble role="user" text={qa.question} />
            <div className="flex justify-start">
              <div className="rounded-lg bg-muted px-3 py-2 text-sm max-w-sm">
                {qa.answer === ''
                  ? <span className="text-muted-foreground italic">Thinking...</span>
                  : qa.answer}
              </div>
            </div>
          </div>
        ))}

        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  )
}
