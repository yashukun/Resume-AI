import { useEffect, useState } from "react";
import { FileText, Trash2, CheckCircle, Clock, Library } from "lucide-react";
import { apiService } from "../services/api";
import type { UserResumeSummary } from "../types";
import { cn } from "../utils/cn";

interface ResumeLibraryProps {
  selectedResumeId: string | null;
  onSelect: (resume: UserResumeSummary | null) => void;
  refreshKey?: number;
}

export function ResumeLibrary({
  selectedResumeId,
  onSelect,
  refreshKey = 0,
}: ResumeLibraryProps) {
  const [resumes, setResumes] = useState<UserResumeSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiService
      .listUserResumes()
      .then((data) => {
        if (!cancelled) {
          setResumes(data);
          setError(null);
        }
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load your saved resumes.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("Remove this resume from your library?")) return;
    try {
      await apiService.deleteUserResume(id);
      setResumes((prev) => prev.filter((r) => r.id !== id));
      if (selectedResumeId === id) onSelect(null);
    } catch {
      setError("Failed to delete.");
    }
  };

  if (loading) {
    return (
      <div className="text-sm text-gray-500 dark:text-slate-400 py-4">
        Loading your saved resumes…
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-sm text-red-600 dark:text-red-400 py-4">{error}</div>
    );
  }

  if (resumes.length === 0) {
    return (
      <div className="bg-slate-50 dark:bg-surface-900/50 border border-dashed border-gray-200 dark:border-white/10 rounded-2xl p-5 text-center">
        <Library className="w-6 h-6 text-gray-400 dark:text-slate-500 mx-auto mb-2" />
        <p className="text-sm text-gray-600 dark:text-slate-400">
          No saved resumes yet. Upload one below — we'll remember it so the
          next job skips parsing.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm font-medium text-gray-700 dark:text-slate-300">
          Pick from your saved resumes
        </p>
        {selectedResumeId && (
          <button
            onClick={() => onSelect(null)}
            className="text-xs text-primary-600 dark:text-primary-400 hover:underline"
          >
            Use a new file instead
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {resumes.map((r) => {
          const isSelected = r.id === selectedResumeId;
          return (
            <button
              key={r.id}
              type="button"
              onClick={() => onSelect(r)}
              className={cn(
                "group relative text-left rounded-xl border p-3 transition-all duration-200",
                "flex items-center gap-3",
                isSelected
                  ? "border-primary-500 bg-primary-50 dark:bg-primary-500/10 shadow-md"
                  : "border-gray-200 dark:border-white/10 bg-white dark:bg-surface-800 hover:border-primary-300 dark:hover:border-primary-500/30",
              )}
            >
              <div
                className={cn(
                  "w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0",
                  isSelected
                    ? "bg-gradient-to-br from-primary-500 to-accent-600 text-white"
                    : "bg-gray-100 dark:bg-surface-700 text-gray-500 dark:text-slate-400",
                )}
              >
                <FileText className="w-4 h-4" />
              </div>

              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                  {r.name || r.original_filename}
                </p>
                <p className="text-xs text-gray-500 dark:text-slate-400 truncate">
                  {r.original_filename} •{" "}
                  {new Date(r.created_at).toLocaleDateString()}
                </p>
              </div>

              <div className="flex items-center gap-1 flex-shrink-0">
                {r.is_parsed ? (
                  <span
                    title="Parsed — ready to reuse"
                    className="text-emerald-500"
                  >
                    <CheckCircle className="w-4 h-4" />
                  </span>
                ) : (
                  <span
                    title="Parsing in progress"
                    className="text-amber-500"
                  >
                    <Clock className="w-4 h-4" />
                  </span>
                )}
                <button
                  type="button"
                  onClick={(e) => handleDelete(r.id, e)}
                  className="p-1 rounded text-gray-400 hover:text-red-500 dark:hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                  aria-label="Delete"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
