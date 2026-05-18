'use client'

import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { PaperCandidate } from '@/lib/types'

interface PaperDetailCanvasProps {
  candidates: PaperCandidate[]
}

export function PaperDetailCanvas({ candidates }: PaperDetailCanvasProps) {
  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-4">
        {candidates.map((paper, i) => (
          <Card key={paper.entry_id}>
            <CardHeader className="pb-1 pt-3 px-4">
              <CardTitle className="text-base font-medium leading-snug">
                {i + 1}. {paper.title}
              </CardTitle>
              <div className="mt-1 space-y-1.5">
                <p className="text-base text-foreground">{paper.authors}</p>
                <div className="flex flex-wrap gap-1.5">
                  <span className="inline-flex items-center rounded-md border px-2 py-0.5 text-base text-foreground">
                    {paper.year}
                  </span>
                  {paper.cited_by_count != null && (
                    <span className="inline-flex items-center rounded-md border px-2 py-0.5 text-base text-foreground">
                      {paper.cited_by_count.toLocaleString()} citations
                    </span>
                  )}
                  <span className="inline-flex items-center rounded-md border px-2 py-0.5 text-base text-foreground">
                    similarity {paper.similarity_score.toFixed(2)}
                  </span>
                </div>
              </div>
            </CardHeader>
            <CardContent className="px-4 pb-3">
              <p className="text-base text-muted-foreground leading-relaxed">
                {paper.abstract_summary}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>
    </ScrollArea>
  )
}
