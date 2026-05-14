interface MessageBubbleProps {
  role: 'user' | 'assistant'
  text: string
}

export function MessageBubble({ role, text }: MessageBubbleProps) {
  const isUser = role === 'user'
  return (
    <div className={`flex my-2 ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-lg px-3 py-2 text-base ${
          isUser
            ? 'bg-primary text-primary-foreground'
            : 'bg-muted text-muted-foreground'
        }`}
      >
        {text}
      </div>
    </div>
  )
}
