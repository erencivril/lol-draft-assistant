import { useEffect } from "react";

type ToastProps = {
  message: string;
  tone?: "success" | "error";
  onClose: () => void;
};

export function Toast({ message, tone = "success", onClose }: ToastProps) {
  useEffect(() => {
    const timeoutId = window.setTimeout(onClose, 3000);
    return () => window.clearTimeout(timeoutId);
  }, [onClose]);

  return (
    <aside className={`toast toast-${tone}`} role="status" aria-live="polite">
      <span>{message}</span>
      <button className="toast-close" type="button" onClick={onClose}>
        Dismiss
      </button>
    </aside>
  );
}
