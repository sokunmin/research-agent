import type { StepMessage } from '@/lib/types'

interface ProgressMessageProps {
  stepMessage: StepMessage
}

export function ProgressMessage({ stepMessage }: ProgressMessageProps) {
  const { sender, message, status } = stepMessage
  return (
    <div className="grid grid-cols-[16px_1fr] gap-x-1.5 py-0.5 text-sm text-foreground/90">
      <span className="mt-1 justify-self-center shrink-0">
        {status === 'running'
          ? <span className="block h-2 w-2 rounded-full bg-white animate-pulse" />
          : <span className="text-green-400 text-xs leading-none">✓</span>}
      </span>
      {/* tag + message flow as inline text — wraps naturally to full column width */}
      <p className="break-words">
        <span className="font-mono text-xs text-foreground/50 mr-1.5">[{sender}]</span>
        {message}
      </p>
    </div>
  )
}
