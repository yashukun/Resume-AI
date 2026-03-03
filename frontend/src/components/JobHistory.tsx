import { useState, useEffect, useCallback } from "react";
import {
  Clock,
  Download,
  Trash2,
  ChevronDown,
  ChevronUp,
  FileText,
  CheckCircle,
  XCircle,
  Loader2,
} from "lucide-react";
import { apiService } from "../services/api";
import type { Job, JobStatus } from "../types";
import { cn } from "../utils/cn";

interface JobHistoryProps {
  /** Refresh trigger — increment to force a refresh */
  refreshKey?: number;
  onDownload: (jobId: string, format: "docx" | "pdf") => void;
}

const STATUS_CONFIG: Record<
  JobStatus,
  { label: string; className: string; icon: typeof CheckCircle }
> = {
  pending: {
    label: "Pending",
    className:
      "bg-gray-100 dark:bg-slate-500/10 text-gray-600 dark:text-slate-400",
    icon: Clock,
  },
  parsing: {
    label: "Parsing",
    className:
      "bg-blue-100 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400",
    icon: Loader2,
  },
  processing: {
    label: "Processing",
    className:
      "bg-indigo-100 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-400",
    icon: Loader2,
  },
  optimizing: {
    label: "Optimizing",
    className:
      "bg-purple-100 dark:bg-purple-500/10 text-purple-700 dark:text-purple-400",
    icon: Loader2,
  },
  completed: {
    label: "Completed",
    className:
      "bg-green-100 dark:bg-emerald-500/10 text-green-700 dark:text-emerald-400",
    icon: CheckCircle,
  },
  failed: {
    label: "Failed",
    className: "bg-red-100 dark:bg-red-500/10 text-red-700 dark:text-red-400",
    icon: XCircle,
  },
};

function Skeleton() {
  return (
    <div className="space-y-3">
      {[1, 2, 3].map((i) => (
        <div key={i} className="h-16 rounded-xl animate-shimmer" />
      ))}
    </div>
  );
}

function timeAgo(dateStr: string): string {
  const now = new Date();
  const date = new Date(dateStr);
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function JobHistory({ refreshKey, onDownload }: JobHistoryProps) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isExpanded, setIsExpanded] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchJobs = useCallback(async () => {
    try {
      const data = await apiService.listJobs(10, 0);
      setJobs(data);
    } catch {
      // Silently fail — history is non-critical
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs, refreshKey]);

  const handleDelete = async (jobId: string) => {
    setDeletingId(jobId);
    try {
      await apiService.deleteJob(jobId);
      setJobs((prev) => prev.filter((j) => j.id !== jobId));
    } catch {
      // ignore
    } finally {
      setDeletingId(null);
    }
  };

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-surface-800 rounded-3xl border border-gray-200 dark:border-white/5 shadow-lg shadow-gray-200/50 dark:shadow-black/30 p-6 animate-fadeIn">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Recent Jobs
        </h3>
        <Skeleton />
      </div>
    );
  }

  if (jobs.length === 0) return null;

  const visibleJobs = isExpanded ? jobs : jobs.slice(0, 3);

  return (
    <div className="bg-white dark:bg-surface-800 rounded-3xl border border-gray-200 dark:border-white/5 shadow-lg shadow-gray-200/50 dark:shadow-black/30 overflow-hidden animate-fadeIn">
      <div className="p-6 pb-0">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Clock className="w-5 h-5 text-gray-400 dark:text-slate-500" />
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Recent Jobs
            </h3>
            <span className="text-xs font-medium text-gray-400 dark:text-slate-500 bg-gray-100 dark:bg-surface-700 rounded-full px-2 py-0.5">
              {jobs.length}
            </span>
          </div>
        </div>
      </div>

      <div className="px-6 pb-4 space-y-2">
        {visibleJobs.map((job) => {
          const config = STATUS_CONFIG[job.status];
          const StatusIcon = config.icon;
          const isActive =
            job.status !== "completed" && job.status !== "failed";

          return (
            <div
              key={job.id}
              className="group flex items-center gap-3 p-3 rounded-xl border border-gray-100 dark:border-white/5 hover:border-gray-200 dark:hover:border-white/10 hover:bg-gray-50/50 dark:hover:bg-surface-700/50 transition-all duration-200"
            >
              <div className="flex-shrink-0 w-9 h-9 bg-gray-50 dark:bg-surface-700 rounded-lg flex items-center justify-center">
                <FileText className="w-4 h-4 text-gray-400 dark:text-slate-500" />
              </div>

              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-800 dark:text-slate-200 truncate">
                  {job.original_filename}
                </p>
                <div className="flex items-center gap-2 mt-0.5">
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full",
                      config.className,
                    )}
                  >
                    <StatusIcon
                      className={cn("w-3 h-3", isActive && "animate-spin")}
                    />
                    {config.label}
                  </span>
                  <span className="text-xs text-gray-400 dark:text-slate-500">
                    {timeAgo(job.created_at)}
                  </span>
                  {job.job_title && (
                    <span className="text-xs text-gray-400 dark:text-slate-500 truncate hidden sm:inline">
                      • {job.job_title}
                    </span>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                {job.status === "completed" && (
                  <button
                    onClick={() => onDownload(job.id, "docx")}
                    className="p-2 rounded-lg text-gray-400 dark:text-slate-500 hover:text-primary-600 dark:hover:text-primary-400 hover:bg-primary-50 dark:hover:bg-primary-500/10 transition-colors"
                    title="Download DOCX"
                  >
                    <Download className="w-4 h-4" />
                  </button>
                )}
                <button
                  onClick={() => handleDelete(job.id)}
                  disabled={deletingId === job.id}
                  className="p-2 rounded-lg text-gray-400 dark:text-slate-500 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10 transition-colors disabled:opacity-50"
                  title="Delete"
                >
                  {deletingId === job.id ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Trash2 className="w-4 h-4" />
                  )}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {jobs.length > 3 && (
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="w-full flex items-center justify-center gap-1 py-3 text-sm font-medium text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-white hover:bg-gray-50 dark:hover:bg-surface-700/50 border-t border-gray-100 dark:border-white/5 transition-colors"
        >
          {isExpanded ? (
            <>
              Show Less <ChevronUp className="w-4 h-4" />
            </>
          ) : (
            <>
              Show All ({jobs.length}) <ChevronDown className="w-4 h-4" />
            </>
          )}
        </button>
      )}
    </div>
  );
}
