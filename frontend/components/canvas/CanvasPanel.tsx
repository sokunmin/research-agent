import type { CanvasPhase, FinalResult, HitlRequest, PaperCandidate, StepMessage } from '@/lib/types'
import { EmptyCanvas } from './EmptyCanvas'
import { ProcessingCanvas } from './ProcessingCanvas'
import { OutlineCanvas } from './OutlineCanvas'
import { ResultCanvas } from './ResultCanvas'
import { PaperDetailCanvas } from './PaperDetailCanvas'

interface CanvasPanelProps {
  phase: CanvasPhase
  stepMessages: StepMessage[]
  hitlRequest: HitlRequest | null
  hitlCount: number
  paperTotal: number | null
  finalResult: FinalResult | null
  paperCandidates: PaperCandidate[] | null
}

// To add a new phase: extend CanvasPhase in types.ts, add a case here, create a new component
export function CanvasPanel({ phase, stepMessages, hitlRequest, hitlCount, paperTotal, finalResult, paperCandidates }: CanvasPanelProps) {
  switch (phase) {
    case 'empty':      return <EmptyCanvas />
    case 'processing': return <ProcessingCanvas stepMessages={stepMessages} />
    case 'paper-selection': return <PaperDetailCanvas candidates={paperCandidates!} />
    case 'hitl':       return <OutlineCanvas outline={hitlRequest?.paper_outline} reviewIndex={hitlCount} paperTotal={paperTotal} />
    case 'complete':   return <ResultCanvas finalResult={finalResult!} />
  }
}
