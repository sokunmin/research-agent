import { Badge } from '@/components/ui/badge'
import type { CanvasPhase } from '@/lib/types'

interface AppHeaderProps {
  chatStatus: string
  canvasPhase: CanvasPhase
}

const PHASE_BADGE: Record<CanvasPhase, { label: string; variant: 'default' | 'secondary' | 'outline' | 'destructive' }> = {
  empty:      { label: 'Ready',       variant: 'outline' },
  processing: { label: 'Processing',  variant: 'default' },
  hitl:       { label: 'Review',      variant: 'secondary' },
  complete:   { label: 'Complete',    variant: 'outline' },
}

export function AppHeader({ chatStatus, canvasPhase }: AppHeaderProps) {
  const badge = PHASE_BADGE[canvasPhase]
  return (
    <header className="flex items-center justify-between px-4 py-3 border-b shrink-0">
      <h1 className="text-lg font-semibold">Research Agent by Chu-Ming Su <span className="text-base font-normal text-muted-foreground">(forked from lz-chen)</span></h1>
      <div className="flex items-center gap-2">
        {chatStatus === 'error' && (
          <Badge variant="destructive">Error</Badge>
        )}
        <Badge variant={badge.variant}>{badge.label}</Badge>
      </div>
    </header>
  )
}
