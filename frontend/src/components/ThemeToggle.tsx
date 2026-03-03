import { Moon, Sun } from "lucide-react";
import { cn } from "../utils/cn";

interface ThemeToggleProps {
  isDark: boolean;
  onToggle: () => void;
}

export function ThemeToggle({ isDark, onToggle }: ThemeToggleProps) {
  return (
    <button
      onClick={onToggle}
      className={cn(
        "relative w-14 h-7 rounded-full p-0.5 transition-colors duration-500 focus:outline-none focus:ring-2 focus:ring-primary-500/50",
        isDark
          ? "bg-primary-600/30 border border-primary-500/30"
          : "bg-slate-200 border border-slate-300",
      )}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
    >
      {/* Track icons */}
      <Sun
        className={cn(
          "absolute left-1.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 transition-opacity duration-300",
          isDark ? "opacity-30 text-slate-400" : "opacity-0",
        )}
      />
      <Moon
        className={cn(
          "absolute right-1.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 transition-opacity duration-300",
          isDark ? "opacity-0" : "opacity-30 text-slate-400",
        )}
      />

      {/* Thumb */}
      <div
        className={cn(
          "w-6 h-6 rounded-full shadow-md flex items-center justify-center transition-all duration-500",
          isDark ? "translate-x-7 bg-primary-500" : "translate-x-0 bg-white",
        )}
      >
        {isDark ? (
          <Moon className="w-3.5 h-3.5 text-white" />
        ) : (
          <Sun className="w-3.5 h-3.5 text-amber-500" />
        )}
      </div>
    </button>
  );
}
