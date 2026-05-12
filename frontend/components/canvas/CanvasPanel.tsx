import type { CanvasPhase, FinalResult, HitlRequest, StepMessage } from '@/lib/types'
import { EmptyCanvas } from './EmptyCanvas'
import { ProcessingCanvas } from './ProcessingCanvas'
import { OutlineCanvas } from './OutlineCanvas'
import { ResultCanvas } from './ResultCanvas'

interface CanvasPanelProps {
  phase: CanvasPhase
  stepMessages: StepMessage[]
  hitlRequest: HitlRequest | null
  hitlCount: number
  paperTotal: number | null
  finalResult: FinalResult | null
}

// To add a new phase: extend CanvasPhase in types.ts, add a case here, create a new component
export function CanvasPanel({ phase, stepMessages, hitlRequest, hitlCount, paperTotal, finalResult }: CanvasPanelProps) {
  switch (phase) {
    case 'empty':      return <EmptyCanvas />
    case 'processing': return <ProcessingCanvas stepMessages={stepMessages} />
    case 'hitl':       return <OutlineCanvas outline={hitlRequest?.paper_outline} reviewIndex={hitlCount} paperTotal={paperTotal} />
    case 'complete':   return <ResultCanvas finalResult={finalResult!} />
  }
}
