'use client'

import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import type { FinalResult } from '@/lib/types'

interface ResultCanvasProps {
  finalResult: FinalResult
}

export function ResultCanvas({ finalResult }: ResultCanvasProps) {
  const [pdfBlobUrl, setPdfBlobUrl] = useState<string | null>(null)
  const [pdfError, setPdfError] = useState<boolean>(false)

  useEffect(() => {
    let blobUrl: string
    fetch(finalResult.download_pdf_url)
      .then(r => r.blob())
      .then(blob => {
        blobUrl = URL.createObjectURL(blob)
        setPdfBlobUrl(blobUrl)
      })
      .catch(err => { console.error(err); setPdfError(true) })
    return () => {
      if (blobUrl) URL.revokeObjectURL(blobUrl)
    }
  }, [finalResult.download_pdf_url])

  const downloadFile = async (url: string, filename: string) => {
    const blob = await fetch(url).then(r => r.blob())
    const a = Object.assign(document.createElement('a'), {
      href: URL.createObjectURL(blob),
      download: filename,
    })
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="flex flex-col h-full p-4 gap-3">
      <div className="flex gap-2 shrink-0">
        <Button onClick={() => downloadFile(finalResult.download_pptx_url, 'slides.pptx')}>
          Download PPTX
        </Button>
        <Button variant="outline" onClick={() => downloadFile(finalResult.download_pdf_url, 'slides.pdf')}>
          Download PDF
        </Button>
      </div>
      {pdfBlobUrl
        ? <iframe src={pdfBlobUrl} className="flex-1 w-full rounded border min-h-0" title="slides preview" />
        : pdfError
          ? <p className="text-destructive text-sm p-4">Failed to load PDF preview. Use Download PDF to view.</p>
          : <Skeleton className="flex-1 w-full" />}
    </div>
  )
}
