'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { HitlRequest } from '@/lib/types'

interface HitlFormProps {
  request: HitlRequest
  onSubmit: (approved: boolean, feedback: string) => Promise<void>
}

// Renders inline in the chat thread — right canvas simultaneously shows the outline
export function HitlForm({ request, onSubmit }: HitlFormProps) {
  // base-ui ToggleGroup uses string[] for value; multiple=false (default) = single select
  const [selection, setSelection] = useState<string[]>([])
  const [feedback, setFeedback]   = useState('')
  const [loading, setLoading]     = useState(false)

  const approval = selection[0] ?? ''

  const handleSubmit = async () => {
    if (!approval) return
    setLoading(true)
    await onSubmit(approval === 'approve', feedback)
    setLoading(false)
  }

  return (
    <div className="my-3 p-4 border rounded-lg bg-muted/50 space-y-3">
      <p className="text-base">{request.message}</p>
      {/* multiple={false} (default) enforces mutual exclusion between Approve / Reject */}
      <ToggleGroup value={selection} onValueChange={setSelection}>
        <ToggleGroupItem value="approve">👍 Approve</ToggleGroupItem>
        <ToggleGroupItem value="reject">👎 Reject</ToggleGroupItem>
      </ToggleGroup>
      <Textarea
        placeholder="Feedback (required if rejecting)..."
        value={feedback}
        onChange={e => setFeedback(e.target.value)}
        rows={3}
      />
      <Button onClick={handleSubmit} disabled={!approval || loading} size="sm">
        {loading ? 'Submitting...' : 'Submit'}
      </Button>
    </div>
  )
}
