import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable'

interface CanvasLayoutProps {
  left: React.ReactNode
  right: React.ReactNode
}

// 35% left (chat) / 65% right (canvas) — matches Gemini canvas pattern
export function CanvasLayout({ left, right }: CanvasLayoutProps) {
  return (
    <ResizablePanelGroup orientation="horizontal" className="flex-1 overflow-hidden">
      <ResizablePanel defaultSize={35} minSize={25}>
        <div className="flex flex-col h-full overflow-hidden">{left}</div>
      </ResizablePanel>
      <ResizableHandle withHandle />
      <ResizablePanel defaultSize={65} minSize={40}>
        <div className="h-full overflow-auto">{right}</div>
      </ResizablePanel>
    </ResizablePanelGroup>
  )
}
