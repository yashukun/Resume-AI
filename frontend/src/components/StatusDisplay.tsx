import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import type { JobStatus } from "../types";
import { cn } from "../utils/cn";

interface StatusDisplayProps {
  status: JobStatus | null;
  progressMessage?: string;
  errorMessage?: string;
}

const STEPS: { key: JobStatus; label: string }[] = [
  { key: "pending", label: "Uploading" },
  { key: "parsing", label: "Parsing Resume" },
  { key: "processing", label: "Extracting Data" },
  { key: "optimizing", label: "AI Optimization" },
  { key: "completed", label: "Complete" },
];

function getStepIndex(status: JobStatus): number {
  const index = STEPS.findIndex((s) => s.key === status);
  return index === -1 ? 0 : index;
}

export function StatusDisplay({
  status,
  progressMessage,
  errorMessage,
}: StatusDisplayProps) {
  if (!status) return null;

  const isFailed = status === "failed";
  const currentIndex = getStepIndex(status);

  return (
    <div className="bg-white dark:bg-surface-800 rounded-2xl border border-gray-200 dark:border-white/5 p-6 shadow-sm animate-fadeIn">
      <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-6">
        Processing Status
      </h3>

      {isFailed ? (
        <div className="flex items-start gap-3 p-4 bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 rounded-xl">
          <XCircle className="w-5 h-5 text-red-500 dark:text-red-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-red-800 dark:text-red-300">
              Processing Failed
            </p>
            {errorMessage && (
              <p className="text-sm text-red-600 dark:text-red-400/80 mt-1">
                {errorMessage}
              </p>
            )}
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {/* Progress Steps */}
          <div className="flex items-center justify-between">
            {STEPS.map((step, index) => {
              const isCompleted = index < currentIndex;
              const isCurrent = index === currentIndex;
              const isPending = index > currentIndex;

              return (
                <div key={step.key} className="flex items-center flex-1">
                  {/* Step indicator */}
                  <div className="flex flex-col items-center">
                    <div
                      className={cn(
                        "w-10 h-10 rounded-full flex items-center justify-center transition-all duration-500",
                        (isCompleted ||
                          (isCurrent && status === "completed")) &&
                          "bg-emerald-500 text-white scale-100",
                        isCurrent &&
                          status !== "completed" &&
                          "bg-primary-500 text-white animate-progressPulse",
                        isPending &&
                          "bg-gray-100 dark:bg-surface-700 text-gray-400 dark:text-slate-500 scale-95",
                      )}
                    >
                      {isCompleted || (isCurrent && status === "completed") ? (
                        <CheckCircle2 className="w-5 h-5" />
                      ) : isCurrent ? (
                        <Loader2 className="w-5 h-5 animate-spin" />
                      ) : (
                        <Circle className="w-5 h-5" />
                      )}
                    </div>
                    <span
                      className={cn(
                        "text-xs mt-2 text-center max-w-[80px]",
                        (isCompleted ||
                          (isCurrent && status === "completed")) &&
                          "text-emerald-600 dark:text-emerald-400 font-medium",
                        isCurrent &&
                          status !== "completed" &&
                          "text-primary-600 dark:text-primary-400 font-medium",
                        isPending && "text-gray-400 dark:text-slate-500",
                      )}
                    >
                      {step.label}
                    </span>
                  </div>

                  {/* Connector line */}
                  {index < STEPS.length - 1 && (
                    <div
                      className={cn(
                        "flex-1 h-0.5 mx-2 transition-colors duration-300",
                        index < currentIndex
                          ? "bg-emerald-500"
                          : "bg-gray-200 dark:bg-surface-700",
                      )}
                    />
                  )}
                </div>
              );
            })}
          </div>

          {/* Progress Message */}
          {progressMessage && status !== "completed" && (
            <div className="flex items-center gap-2 p-3 bg-primary-50 dark:bg-primary-500/10 rounded-xl mt-4">
              <Loader2 className="w-4 h-4 text-primary-500 dark:text-primary-400 animate-spin" />
              <p className="text-sm text-primary-700 dark:text-primary-300">
                {progressMessage}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
