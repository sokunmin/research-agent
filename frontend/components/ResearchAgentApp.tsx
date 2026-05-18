'use client'

import { useWorkflow } from '@/hooks/useWorkflow'
import { AppHeader } from '@/components/layout/AppHeader'
import { CanvasLayout } from '@/components/layout/CanvasLayout'
import { ChatThread } from '@/components/chat/ChatThread'
import { ChatInput } from '@/components/chat/ChatInput'
import { CanvasPanel } from '@/components/canvas/CanvasPanel'

// Root component: calls useWorkflow() and passes slices of state down.
// No prop drilling beyond one level — no global state library needed.
export function ResearchAgentApp() {
  const wf = useWorkflow()

  const handleSubmit = async (msg: { text: string }) => {
    if (wf.canvasPhase === 'paper-selection') {
      await wf.submitPaperQuestion(msg.text)
      return
    }
    await wf.sendMessage(msg)
  }

  return (
    <div className="flex flex-col h-screen">
      <AppHeader chatStatus={wf.chatStatus} canvasPhase={wf.canvasPhase} />
      <CanvasLayout
        left={
          <>
            <ChatThread
              messages={wf.messages}
              stepMessages={wf.stepMessages}
              reasoningChunks={wf.reasoningChunks}
              hitlRequest={wf.hitlRequest}
              onHitlSubmit={wf.submitHitlFeedback}
              paperCandidates={wf.paperCandidates}
              paperSearchParams={wf.paperSearchParams}
              paperQAHistory={wf.paperQAHistory}
              noResultsInfo={wf.noResultsInfo}
              supervisorMessage={wf.supervisorMessage}
              hasConversation={wf.hasConversation}
              onGenerate={(ids) => wf.submitPaperSelection('select', ids)}
              onNewSearch={() => wf.submitPaperSelection('abort')}
            />
            <ChatInput
              onSend={handleSubmit}
              disabled={wf.isInputDisabled}
              placeholder={
                wf.canvasPhase === 'paper-selection'
                  ? 'Ask about any paper...'
                  : wf.canvasPhase === 'complete'
                    ? 'Ask about the papers...'
                    : 'Enter your research topic...'
              }
            />
          </>
        }
        right={
          <CanvasPanel
            phase={wf.canvasPhase}
            stepMessages={wf.stepMessages}
            hitlRequest={wf.hitlRequest}
            hitlCount={wf.hitlCount}
            paperTotal={wf.paperTotal}
            finalResult={wf.finalResult}
            paperCandidates={wf.paperCandidates}
          />
        }
      />
    </div>
  )
}
