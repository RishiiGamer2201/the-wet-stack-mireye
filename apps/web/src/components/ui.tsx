/** Small accessible primitives (shadcn/ui-equivalent, hand-rolled to keep the
 *  dependency surface small). Every interactive element is a real button/input
 *  with a visible focus ring and an accessible name. */

import { AlertTriangle, Inbox, Loader2, X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

export const cx = (...parts: (string | false | null | undefined)[]) =>
  parts.filter(Boolean).join(" ");

export function Card({
  title,
  subtitle,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section
      className={cx(
        "rounded-xl border border-ink-200 bg-white shadow-sm",
        className,
      )}
    >
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-ink-100 px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-ink-900">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-ink-500">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

export function Badge({
  children,
  className,
  title,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap",
        className ?? "border-ink-300 bg-ink-100 text-ink-700",
      )}
    >
      {children}
    </span>
  );
}

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  loading?: boolean;
};

export function Button({
  variant = "secondary",
  size = "md",
  loading,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  const variants = {
    primary: "bg-ink-900 text-white hover:bg-ink-800 disabled:bg-ink-400",
    secondary:
      "bg-white text-ink-800 border border-ink-300 hover:bg-ink-50 disabled:text-ink-400",
    ghost: "text-ink-700 hover:bg-ink-100 disabled:text-ink-400",
    danger: "bg-rose-600 text-white hover:bg-rose-700 disabled:bg-rose-300",
  };
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors disabled:cursor-not-allowed",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-sm",
        variants[variant],
        className,
      )}
    >
      {loading && <Loader2 aria-hidden className="h-3.5 w-3.5 animate-spin" />}
      {children}
    </button>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
}: {
  tabs: { id: T; label: ReactNode; badge?: ReactNode }[];
  value: T;
  onChange: (id: T) => void;
  label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-1 border-b border-ink-200">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={value === tab.id}
          onClick={() => onChange(tab.id)}
          className={cx(
            "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors",
            value === tab.id
              ? "border-ink-900 text-ink-900"
              : "border-transparent text-ink-500 hover:text-ink-800",
          )}
        >
          <span className="inline-flex items-center gap-1.5">
            {tab.label}
            {tab.badge}
          </span>
        </button>
      ))}
    </div>
  );
}

export function Drawer({
  open,
  onClose,
  title,
  children,
  width = "max-w-xl",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  width?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-ink-900/30"
        onClick={onClose}
        aria-hidden
      />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : "Details"}
        tabIndex={-1}
        className={cx(
          "relative flex h-full w-full flex-col bg-white shadow-2xl outline-none",
          width,
        )}
      >
        <header className="flex items-center justify-between border-b border-ink-200 px-4 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close panel">
            <X aria-hidden className="h-4 w-4" />
          </Button>
        </header>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  );
}

export function Meter({ value, className }: { value: number; className?: string }) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div
      className="h-1.5 w-full overflow-hidden rounded-full bg-ink-200"
      role="img"
      aria-label={`${clamped.toFixed(0)} out of 100`}
    >
      <div
        className={cx("h-full rounded-full", className ?? "bg-ink-700")}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 py-8 text-sm text-ink-500">
      <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
      {label}
    </div>
  );
}

export function EmptyState({
  title,
  detail,
  action,
}: {
  title: string;
  detail?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-center">
      <Inbox aria-hidden className="h-6 w-6 text-ink-400" />
      <p className="text-sm font-medium text-ink-700">{title}</p>
      {detail && <p className="max-w-md text-xs text-ink-500">{detail}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-2 rounded-lg border border-rose-300 bg-rose-50 p-4 text-sm text-rose-900"
    >
      <div className="flex items-center gap-2 font-medium">
        <AlertTriangle aria-hidden className="h-4 w-4" />
        Something went wrong
      </div>
      <p className="text-xs">{message}</p>
      {onRetry && (
        <Button size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function Field({
  label,
  hint,
  children,
  htmlFor,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={htmlFor} className="text-xs font-medium text-ink-700">
        {label}
      </label>
      {children}
      {hint && <p className="text-[11px] text-ink-500">{hint}</p>}
    </div>
  );
}

export const inputClass =
  "w-full rounded-lg border border-ink-300 bg-white px-2.5 py-1.5 text-sm text-ink-900 placeholder:text-ink-400";
