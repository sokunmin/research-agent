// Named submitHitlFeedbackApi to avoid collision with the hook action of the same name
export async function submitHitlFeedbackApi(
  backendUrl: string,
  workflowId: string,
  approved: boolean,
  feedback: string,
): Promise<void> {
  // user_input must be a JSON string — backend calls json.loads() on it
  // approval values must match what gather_feedback_outline() expects in slide_gen.py
  const res = await fetch(`${backendUrl}/submit_user_input`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      workflow_id: workflowId,
      user_input: JSON.stringify({
        approval: approved ? ':material/thumb_up:' : ':material/thumb_down:',
        feedback,
      }),
    }),
  })
  if (!res.ok) throw new Error(`HITL submit failed: ${res.status}`)
}
