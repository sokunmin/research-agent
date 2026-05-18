'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import type { PaperCandidate, SearchParams } from '@/lib/types'

interface PaperSelectCardProps {
  candidates: PaperCandidate[]
  searchParams: SearchParams
  onGenerate: (selectedIds: string[]) => void
  onNewSearch: () => void
}

export function PaperSelectCard({
  candidates,
  searchParams,
  onGenerate,
  onNewSearch,
}: PaperSelectCardProps) {
  const [selected, setSelected] = useState<Set<string>>(
    new Set(candidates.map(c => c.entry_id))
  )

  const toggle = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  return (
    <div className="rounded-lg border bg-card p-4 space-y-3 max-w-sm">
      <div className="text-xs text-muted-foreground space-y-0.5">
        <p>topic: <span className="font-mono">{searchParams.clean_topic}</span></p>
        <p>last {searchParams.year_window} yrs · cited &gt; {searchParams.min_citations}</p>
      </div>

      <hr className="border-border" />

      <div className="space-y-2">
        {candidates.map(paper => (
          <div
            key={paper.entry_id}
            className="flex items-start gap-2 cursor-pointer"
            onClick={() => toggle(paper.entry_id)}
          >
            <Checkbox
              checked={selected.has(paper.entry_id)}
              onCheckedChange={() => toggle(paper.entry_id)}
              className="mt-0.5 shrink-0"
            />
            <span className="text-sm leading-snug line-clamp-2">{paper.title}</span>
          </div>
        ))}
      </div>

      <div className="space-y-2 pt-1">
        <Button
          className="w-full"
          disabled={selected.size === 0}
          onClick={() => onGenerate(Array.from(selected))}
        >
          ▶ Generate slides ({selected.size})
        </Button>
        <Button
          variant="outline"
          className="w-full"
          onClick={onNewSearch}
        >
          🔍 New search
        </Button>
      </div>
    </div>
  )
}
