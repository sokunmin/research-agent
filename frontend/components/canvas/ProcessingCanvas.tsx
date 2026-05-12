import type { StepMessage } from '@/lib/types'

interface ProcessingCanvasProps {
  stepMessages: StepMessage[]
}

export function ProcessingCanvas({ stepMessages }: ProcessingCanvasProps) {
  const current = [...stepMessages].reverse().find(m => m.status === 'running')
  const doneCount = stepMessages.filter(m => m.status === 'done').length

  return (
    <div className="flex flex-col items-center justify-center h-full gap-6 p-8 text-center">
      {/* Spinner */}
      <div className="h-12 w-12 rounded-full border-4 border-muted border-t-white animate-spin" />

      {/* Current step */}
      <div className="space-y-2 max-w-md">
        <p className="text-sm font-mono text-muted-foreground uppercase tracking-widest">
          {current ? current.sender : 'Starting...'}
        </p>
        <p className="text-lg text-foreground/90 leading-relaxed">
          {current ? current.message : 'Initializing workflow...'}
        </p>
      </div>

      {/* Completed count */}
      {doneCount > 0 && (
        <p className="text-base text-muted-foreground">
          {doneCount} step{doneCount > 1 ? 's' : ''} completed
        </p>
      )}
    </div>
  )
}
