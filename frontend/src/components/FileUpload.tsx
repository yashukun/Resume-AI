import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import { Upload, FileText, X, CheckCircle } from "lucide-react";
import { cn } from "../utils/cn";

interface FileUploadProps {
  onFileSelect: (file: File) => void;
  selectedFile: File | null;
  onClear: () => void;
}

export function FileUpload({
  onFileSelect,
  selectedFile,
  onClear,
}: FileUploadProps) {
  const [error, setError] = useState<string | null>(null);

  const onDrop = useCallback(
    (
      acceptedFiles: File[],
      rejectedFiles: { errors: { message: string }[] }[],
    ) => {
      setError(null);

      if (rejectedFiles.length > 0) {
        setError(rejectedFiles[0].errors[0].message);
        return;
      }

      if (acceptedFiles.length > 0) {
        onFileSelect(acceptedFiles[0]);
      }
    },
    [onFileSelect],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "application/pdf": [".pdf"],
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        [".docx"],
      "application/msword": [".doc"],
    },
    maxSize: 10 * 1024 * 1024, // 10MB
    maxFiles: 1,
  });

  if (selectedFile) {
    return (
      <div className="relative bg-gradient-to-br from-emerald-50 to-teal-50 dark:from-emerald-500/10 dark:to-teal-500/10 border-2 border-emerald-200 dark:border-emerald-500/20 rounded-2xl p-6 animate-fadeIn">
        <button
          onClick={onClear}
          className="absolute top-3 right-3 p-1.5 rounded-full bg-white/80 dark:bg-surface-700/80 hover:bg-white dark:hover:bg-surface-600 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-white transition-colors shadow-sm"
          aria-label="Remove file"
        >
          <X size={18} />
        </button>

        <div className="flex items-center gap-4">
          <div className="flex-shrink-0 w-14 h-14 bg-gradient-to-br from-emerald-500 to-teal-600 rounded-xl flex items-center justify-center shadow-lg shadow-emerald-500/25">
            <CheckCircle className="w-7 h-7 text-white" />
          </div>

          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-emerald-800 dark:text-emerald-300 truncate">
              {selectedFile.name}
            </p>
            <p className="text-xs text-emerald-600 dark:text-emerald-400/70 mt-0.5">
              {(selectedFile.size / 1024).toFixed(1)} KB • Ready to upload
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div
        {...getRootProps()}
        className={cn(
          "relative cursor-pointer rounded-2xl border-2 border-dashed transition-all duration-200",
          "bg-gradient-to-br from-slate-50 to-gray-50 dark:from-surface-800 dark:to-surface-850 hover:from-primary-50 hover:to-violet-50 dark:hover:from-primary-500/5 dark:hover:to-violet-500/5",
          "p-8 text-center",
          isDragActive
            ? "border-primary-400 dark:border-primary-500/50 bg-primary-50 dark:bg-primary-500/10 scale-[1.02]"
            : "border-gray-300 dark:border-white/10 hover:border-primary-300 dark:hover:border-primary-500/30",
          error &&
            "border-red-300 dark:border-red-500/30 bg-red-50 dark:bg-red-500/10",
        )}
      >
        <input {...getInputProps()} />

        <div className="flex flex-col items-center justify-center gap-4">
          <div
            className={cn(
              "w-16 h-16 rounded-2xl flex items-center justify-center transition-all duration-200",
              isDragActive
                ? "bg-gradient-to-br from-primary-500 to-accent-600 shadow-lg shadow-primary-500/25"
                : "bg-gradient-to-br from-gray-100 to-gray-200 dark:from-surface-700 dark:to-surface-700",
            )}
          >
            {isDragActive ? (
              <Upload className="w-8 h-8 text-white animate-bounce" />
            ) : (
              <FileText className="w-8 h-8 text-gray-400 dark:text-slate-500" />
            )}
          </div>

          <div>
            <p className="text-base font-medium text-gray-700 dark:text-slate-200">
              {isDragActive ? "Drop your resume here" : "Upload your resume"}
            </p>
            <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">
              Drag & drop or{" "}
              <span className="text-primary-600 dark:text-primary-400 font-medium hover:text-primary-700 dark:hover:text-primary-300">
                browse
              </span>
            </p>
            <p className="text-xs text-gray-400 dark:text-slate-500 mt-2">
              PDF or DOCX • Max 10MB
            </p>
          </div>
        </div>
      </div>

      {error && (
        <p className="mt-2 text-sm text-red-600 dark:text-red-400 animate-fadeIn">
          {error}
        </p>
      )}
    </div>
  );
}
