export function EmptyCanvas() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center p-8 text-muted-foreground">
      <div className="text-4xl mb-4">🔬</div>
      <h2 className="text-xl font-semibold mb-2 text-foreground">Research to Slides</h2>
      <p className="text-base max-w-sm">
        Enter a research topic in the chat to discover papers, generate summaries,
        and produce a PowerPoint presentation with AI.
      </p>
    </div>
  )
}
