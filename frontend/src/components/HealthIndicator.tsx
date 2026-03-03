import { cn } from "../utils/cn";

interface HealthIndicatorProps {
  isOnline: boolean | null;
}

export function HealthIndicator({ isOnline }: HealthIndicatorProps) {
  if (isOnline === null) {
    // Still checking
    return (
      <div className="flex items-center gap-2">
        <div className="w-2 h-2 rounded-full bg-gray-300 dark:bg-slate-600 animate-pulse" />
        <span className="text-xs text-gray-400 dark:text-slate-500 hidden sm:inline">
          Connecting...
        </span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <div className="relative">
        <div
          className={cn(
            "w-2 h-2 rounded-full transition-colors duration-500",
            isOnline ? "bg-green-500" : "bg-red-500",
          )}
        />
        {isOnline && (
          <div className="absolute inset-0 w-2 h-2 rounded-full bg-green-400 animate-ping opacity-75" />
        )}
      </div>
      <span
        className={cn(
          "text-xs font-medium hidden sm:inline transition-colors duration-500",
          isOnline
            ? "text-emerald-600 dark:text-emerald-400"
            : "text-red-500 dark:text-red-400",
        )}
      >
        {isOnline ? "API Online" : "API Offline"}
      </span>
    </div>
  );
}
