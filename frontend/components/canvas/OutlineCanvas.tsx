import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { PaperSlideOutline } from '@/lib/types'

interface OutlineCanvasProps {
  outline: PaperSlideOutline | undefined
  reviewIndex: number
  paperTotal: number | null
}

export function OutlineCanvas({ outline, reviewIndex, paperTotal }: OutlineCanvasProps) {
  if (!outline) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-base">
        Loading outline...
      </div>
    )
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-4">
        <div className="flex items-baseline gap-2 pb-2 border-b">
          <h2 className="text-lg font-semibold">
            Slide Outline Preview — Paper ({reviewIndex}/{paperTotal ?? '?'})
          </h2>
          <span className="text-base text-muted-foreground">— pending your review</span>
        </div>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-medium text-muted-foreground">Paper Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-base">
            <p className="font-semibold">{outline.paper_title}</p>
            <p className="text-muted-foreground">{outline.paper_authors}</p>
            <p className="text-muted-foreground">{outline.paper_year}</p>
          </CardContent>
        </Card>

        {outline.content_slides.map((slide, i) => (
          <Card key={i}>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">{slide.title}</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-1">
                {slide.content.map((item, j) => (
                  <li
                    key={j}
                    className="text-base text-muted-foreground"
                    style={{ paddingLeft: `${item.level * 12}px` }}
                  >
                    {item.level > 0 ? '· ' : '• '}{item.text}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        ))}
      </div>
    </ScrollArea>
  )
}
