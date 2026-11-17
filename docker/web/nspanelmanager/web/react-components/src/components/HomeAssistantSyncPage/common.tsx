/** An error banner. Home Assistant failures are shown with the server's message, never as an empty list. */
export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="alert alert-error my-2">
      <span>{message}</span>
      {onRetry && (
        <button type="button" className="btn btn-sm" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Loading({ text }: { text: string }) {
  return (
    <div className="flex w-full items-center justify-center text-xl my-4">
      <span className="loading loading-spinner loading-sm mr-2"></span>
      <span className="font-medium">{text}</span>
    </div>
  );
}
