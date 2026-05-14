'use client'

import { useState } from 'react'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'

interface ReasoningMessageProps {
  text: string
}

export function ReasoningMessage({ text }: ReasoningMessageProps) {
  const [open, setOpen] = useState(false)
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="my-2">
      <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
        <span>{open ? '▾' : '▸'}</span>
        <span>Reasoning</span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <pre className="mt-1 text-xs text-muted-foreground bg-muted rounded p-2 whitespace-pre-wrap overflow-auto max-h-48">
          {text}
        </pre>
      </CollapsibleContent>
    </Collapsible>
  )
}
