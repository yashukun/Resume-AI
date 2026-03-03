import { useState, useCallback, useRef } from "react";
import { Sparkles, FileText, Zap, CheckCircle, Download } from "lucide-react";
import { FileUpload } from "./components/FileUpload";
import { JobDescriptionInput } from "./components/JobDescriptionInput";
import { StatusDisplay } from "./components/StatusDisplay";
import { HealthIndicator } from "./components/HealthIndicator";
import { JobHistory } from "./components/JobHistory";
import { ThemeToggle } from "./components/ThemeToggle";
import { useToast } from "./components/Toast";
import { apiService } from "./services/api";
import { usePolling } from "./hooks/usePolling";
import { useHealthCheck } from "./hooks/useHealthCheck";
import { useDarkMode } from "./hooks/useDarkMode";
import type { JobStatusResponse } from "./types";
import { cn } from "./utils/cn";

function App() {
  // Form state
  const [file, setFile] = useState<File | null>(null);
  const [jobDescription, setJobDescription] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [companyName, setCompanyName] = useState("");

  // Upload state
  const [isUploading, setIsUploading] = useState(false);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);

  // Refs for auto-scroll
  const statusRef = useRef<HTMLDivElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  // Hooks
  const { isDark, toggle: toggleDark } = useDarkMode();
  const { isOnline } = useHealthCheck();
  const { addToast } = useToast();

  // Check if form is valid
  const isFormValid = file !== null && jobDescription.length >= 50;

  // Adaptive polling callback
  const pollCallback = useCallback(async (): Promise<boolean> => {
    if (!currentJobId) return true;
    try {
      const status = await apiService.getJobStatus(currentJobId);
      setJobStatus(status);

      if (status.status === "completed") {
        addToast({
          type: "success",
          title: "Resume Optimized!",
          message: "Your optimized resume is ready to download.",
        });
        setHistoryRefreshKey((k) => k + 1);
        setTimeout(() => {
          resultRef.current?.scrollIntoView({
            behavior: "smooth",
            block: "center",
          });
        }, 100);
        return true;
      }

      if (status.status === "failed") {
        addToast({
          type: "error",
          title: "Optimization Failed",
          message: status.error_message || "Something went wrong.",
        });
        setHistoryRefreshKey((k) => k + 1);
        return true;
      }

      return false;
    } catch {
      return false;
    }
  }, [currentJobId, addToast]);

  // Use adaptive polling (starts at 1s, maxes at 3s)
  usePolling(pollCallback, {
    enabled:
      !!currentJobId &&
      jobStatus?.status !== "completed" &&
      jobStatus?.status !== "failed",
    initialInterval: 1000,
    maxInterval: 3000,
  });

  // Handle form submission
  const handleSubmit = async () => {
    if (!isFormValid || !file) return;

    setIsUploading(true);
    setJobStatus(null);

    try {
      const response = await apiService.uploadResume(
        file,
        jobDescription,
        jobTitle || undefined,
        companyName || undefined,
      );

      setCurrentJobId(response.job_id);
      setJobStatus({
        id: response.job_id,
        status: response.status,
        progress_message: "Job queued for processing",
      });

      addToast({
        type: "info",
        title: "Upload Successful",
        message: "Your resume is being processed.",
        duration: 3000,
      });

      setTimeout(() => {
        statusRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      }, 200);
    } catch (err: unknown) {
      const error = err as {
        response?: { data?: { detail?: string } };
        message?: string;
      };
      const msg =
        error.response?.data?.detail ||
        error.message ||
        "Failed to upload resume";
      addToast({ type: "error", title: "Upload Failed", message: msg });
    } finally {
      setIsUploading(false);
    }
  };

  // Download handler (shared between main UI and job history)
  const handleDownload = async (jobId: string, format: "docx" | "pdf") => {
    try {
      await apiService.downloadResume(jobId, format);
      addToast({ type: "success", title: "Download Started", duration: 2000 });
    } catch {
      addToast({
        type: "error",
        title: "Download Failed",
        message:
          format === "pdf"
            ? "PDF format may not be available for this job."
            : "Could not download the file.",
      });
    }
  };

  // Reset form
  const handleReset = () => {
    setFile(null);
    setJobDescription("");
    setJobTitle("");
    setCompanyName("");
    setCurrentJobId(null);
    setJobStatus(null);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-violet-50/30 dark:from-surface-950 dark:via-surface-900 dark:to-surface-950 transition-colors duration-500">
      {/* Header */}
      <header className="border-b border-gray-200/80 dark:border-white/5 bg-white/80 dark:bg-surface-900/80 backdrop-blur-xl sticky top-0 z-50">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-gradient-to-br from-primary-500 to-accent-600 rounded-xl flex items-center justify-center shadow-lg shadow-primary-500/25 dark:shadow-primary-500/20">
                <Sparkles className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-gray-900 dark:text-white">
                  Resume AI
                </h1>
                <p className="text-xs text-gray-500 dark:text-slate-400">
                  Intelligent Resume Optimization
                </p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <HealthIndicator isOnline={isOnline} />
              <ThemeToggle isDark={isDark} onToggle={toggleDark} />
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
        {/* Hero Section */}
        <div className="text-center mb-10 animate-fadeIn">
          <h2 className="text-3xl sm:text-4xl font-bold text-gray-900 dark:text-white mb-4">
            Optimize Your Resume with{" "}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-primary-500 to-accent-500">
              AI
            </span>
          </h2>
          <p className="text-gray-600 dark:text-slate-400 max-w-2xl mx-auto">
            Upload your resume and paste a job description. Our AI will analyze
            both and help optimize your resume to stand out.
          </p>
        </div>

        {/* Features */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-10 stagger-children">
          {[
            {
              icon: FileText,
              title: "Smart Parsing",
              description: "Extracts key information from your resume",
              gradient: "from-violet-500 to-purple-600",
              bgLight: "bg-violet-50",
              bgDark: "dark:bg-violet-500/10",
              iconColor: "text-violet-600 dark:text-violet-400",
            },
            {
              icon: Zap,
              title: "ATS Optimization",
              description: "Ensures compatibility with tracking systems",
              gradient: "from-amber-500 to-orange-600",
              bgLight: "bg-amber-50",
              bgDark: "dark:bg-amber-500/10",
              iconColor: "text-amber-600 dark:text-amber-400",
            },
            {
              icon: CheckCircle,
              title: "AI Enhancement",
              description: "Improves content based on job requirements",
              gradient: "from-emerald-500 to-teal-600",
              bgLight: "bg-emerald-50",
              bgDark: "dark:bg-emerald-500/10",
              iconColor: "text-emerald-600 dark:text-emerald-400",
            },
          ].map((feature) => (
            <div
              key={feature.title}
              className="bg-white dark:bg-surface-800 rounded-2xl border border-gray-200/80 dark:border-white/5 p-5 hover:shadow-lg hover:shadow-gray-200/50 dark:hover:shadow-black/30 hover:-translate-y-0.5 transition-all duration-300"
            >
              <div
                className={cn(
                  "w-10 h-10 rounded-xl flex items-center justify-center mb-3",
                  feature.bgLight,
                  feature.bgDark,
                )}
              >
                <feature.icon className={cn("w-5 h-5", feature.iconColor)} />
              </div>
              <h3 className="font-semibold text-gray-900 dark:text-white">
                {feature.title}
              </h3>
              <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">
                {feature.description}
              </p>
            </div>
          ))}
        </div>

        {/* Main Form */}
        <div className="bg-white dark:bg-surface-800 rounded-3xl border border-gray-200/80 dark:border-white/5 shadow-xl shadow-gray-200/50 dark:shadow-black/30 overflow-hidden animate-fadeInUp">
          <div className="p-6 sm:p-8 space-y-8">
            {/* Step 1: Upload Resume */}
            <section>
              <div className="flex items-center gap-3 mb-4">
                <div className="w-8 h-8 bg-gradient-to-br from-primary-500 to-accent-600 rounded-full flex items-center justify-center text-white text-sm font-bold shadow-md shadow-primary-500/25">
                  1
                </div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Upload Your Resume
                </h3>
              </div>
              <FileUpload
                onFileSelect={setFile}
                selectedFile={file}
                onClear={() => setFile(null)}
              />
            </section>

            {/* Step 2: Job Description */}
            <section>
              <div className="flex items-center gap-3 mb-4">
                <div
                  className={cn(
                    "w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold shadow-md transition-all duration-500",
                    file
                      ? "bg-gradient-to-br from-primary-500 to-accent-600 text-white shadow-primary-500/25"
                      : "bg-gray-200 dark:bg-surface-700 text-gray-400 dark:text-slate-500 shadow-none",
                  )}
                >
                  2
                </div>
                <h3
                  className={cn(
                    "text-lg font-semibold transition-colors duration-300",
                    file
                      ? "text-gray-900 dark:text-white"
                      : "text-gray-400 dark:text-slate-500",
                  )}
                >
                  Enter Job Details
                </h3>
              </div>
              <div
                className={cn(
                  "transition-all duration-500",
                  !file && "opacity-50 pointer-events-none",
                )}
              >
                <JobDescriptionInput
                  jobDescription={jobDescription}
                  jobTitle={jobTitle}
                  companyName={companyName}
                  onJobDescriptionChange={setJobDescription}
                  onJobTitleChange={setJobTitle}
                  onCompanyNameChange={setCompanyName}
                />
              </div>
            </section>

            {/* Status Display */}
            {jobStatus && (
              <div ref={statusRef} className="animate-scaleIn">
                <StatusDisplay
                  status={jobStatus.status}
                  progressMessage={jobStatus.progress_message}
                  errorMessage={jobStatus.error_message}
                />
              </div>
            )}

            {/* Download Section */}
            {jobStatus?.status === "completed" && currentJobId && (
              <div
                ref={resultRef}
                className="bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/20 rounded-2xl p-6 animate-scaleIn"
              >
                <div className="flex items-center gap-3 mb-4">
                  <CheckCircle className="w-6 h-6 text-emerald-600 dark:text-emerald-400" />
                  <h3 className="text-lg font-semibold text-emerald-900 dark:text-emerald-300">
                    Your Optimized Resume is Ready!
                  </h3>
                </div>
                <p className="text-sm text-emerald-700 dark:text-emerald-400/80 mb-4">
                  Download your ATS-optimized resume in your preferred format.
                </p>
                <div className="flex flex-col sm:flex-row gap-3">
                  <button
                    onClick={() => handleDownload(currentJobId, "docx")}
                    className="flex items-center justify-center gap-2 py-2.5 px-5 rounded-xl font-semibold text-white bg-gradient-to-r from-primary-500 to-accent-600 hover:from-primary-600 hover:to-accent-700 transition-all shadow-md shadow-primary-500/25 hover:shadow-lg"
                  >
                    <Download className="w-4 h-4" />
                    Download DOCX
                  </button>
                  <button
                    onClick={() => handleDownload(currentJobId, "pdf")}
                    className="flex items-center justify-center gap-2 py-2.5 px-5 rounded-xl font-semibold text-gray-700 dark:text-slate-200 bg-white dark:bg-surface-700 border border-gray-300 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-surface-600 transition-all shadow-sm hover:shadow-md"
                  >
                    <Download className="w-4 h-4" />
                    Download PDF
                  </button>
                </div>
              </div>
            )}

            {/* Actions */}
            <div className="flex flex-col sm:flex-row gap-3 pt-4">
              <button
                onClick={handleSubmit}
                disabled={!isFormValid || isUploading}
                className={cn(
                  "flex-1 py-3 px-6 rounded-xl font-semibold text-white transition-all duration-300",
                  "flex items-center justify-center gap-2",
                  isFormValid && !isUploading
                    ? "bg-gradient-to-r from-primary-500 to-accent-600 hover:from-primary-600 hover:to-accent-700 shadow-lg shadow-primary-500/25 hover:shadow-xl hover:shadow-primary-500/30 hover:-translate-y-0.5"
                    : "bg-gray-300 dark:bg-surface-700 dark:text-slate-500 cursor-not-allowed",
                )}
              >
                {isUploading ? (
                  <>
                    <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                      <circle
                        className="opacity-25"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        strokeWidth="4"
                        fill="none"
                      />
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                      />
                    </svg>
                    Uploading...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-5 h-5" />
                    Optimize My Resume
                  </>
                )}
              </button>

              {(file || jobDescription || currentJobId) && (
                <button
                  onClick={handleReset}
                  className="py-3 px-6 rounded-xl font-semibold text-gray-700 dark:text-slate-300 bg-gray-100 dark:bg-surface-700 hover:bg-gray-200 dark:hover:bg-surface-600 transition-all duration-200"
                >
                  Start Over
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Job History */}
        <div className="mt-8">
          <JobHistory
            refreshKey={historyRefreshKey}
            onDownload={handleDownload}
          />
        </div>

        {/* Footer */}
        <footer className="mt-12 text-center text-sm text-gray-500 dark:text-slate-500">
          <p>
            Powered by{" "}
            <span className="font-medium text-gray-700 dark:text-slate-300">
              Ollama
            </span>{" "}
            •{" "}
            <span className="font-medium text-gray-700 dark:text-slate-300">
              FastAPI
            </span>{" "}
            •{" "}
            <span className="font-medium text-gray-700 dark:text-slate-300">
              React
            </span>
          </p>
        </footer>
      </main>
    </div>
  );
}

export default App;
