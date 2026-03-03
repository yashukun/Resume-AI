import { Briefcase, Building2 } from "lucide-react";

interface JobDescriptionInputProps {
  jobDescription: string;
  jobTitle: string;
  companyName: string;
  onJobDescriptionChange: (value: string) => void;
  onJobTitleChange: (value: string) => void;
  onCompanyNameChange: (value: string) => void;
}

export function JobDescriptionInput({
  jobDescription,
  jobTitle,
  companyName,
  onJobDescriptionChange,
  onJobTitleChange,
  onCompanyNameChange,
}: JobDescriptionInputProps) {
  const charCount = jobDescription.length;
  const minChars = 50;
  const isValid = charCount >= minChars;

  return (
    <div className="space-y-4">
      {/* Optional fields */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-slate-300 mb-2">
            <Briefcase
              size={16}
              className="text-gray-400 dark:text-slate-500"
            />
            Job Title
            <span className="text-xs text-gray-400 dark:text-slate-500 font-normal">
              (optional)
            </span>
          </label>
          <input
            type="text"
            value={jobTitle}
            onChange={(e) => onJobTitleChange(e.target.value)}
            placeholder="e.g., Senior Software Engineer"
            className="w-full px-4 py-2.5 rounded-xl border border-gray-200 dark:border-white/10 bg-white dark:bg-surface-850
                     text-gray-900 dark:text-slate-100 placeholder:text-gray-400 dark:placeholder:text-slate-500
                     focus:outline-none focus:ring-2 focus:ring-primary-500/20 dark:focus:ring-primary-500/30 focus:border-primary-500 dark:focus:border-primary-500/50
                     transition-all duration-200"
          />
        </div>

        <div>
          <label className="flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-slate-300 mb-2">
            <Building2
              size={16}
              className="text-gray-400 dark:text-slate-500"
            />
            Company Name
            <span className="text-xs text-gray-400 dark:text-slate-500 font-normal">
              (optional)
            </span>
          </label>
          <input
            type="text"
            value={companyName}
            onChange={(e) => onCompanyNameChange(e.target.value)}
            placeholder="e.g., Google, Apple, Amazon"
            className="w-full px-4 py-2.5 rounded-xl border border-gray-200 dark:border-white/10 bg-white dark:bg-surface-850
                     text-gray-900 dark:text-slate-100 placeholder:text-gray-400 dark:placeholder:text-slate-500
                     focus:outline-none focus:ring-2 focus:ring-primary-500/20 dark:focus:ring-primary-500/30 focus:border-primary-500 dark:focus:border-primary-500/50
                     transition-all duration-200"
          />
        </div>
      </div>

      {/* Job Description */}
      <div>
        <label className="flex items-center justify-between text-sm font-medium text-gray-700 dark:text-slate-300 mb-2">
          <span>Job Description</span>
          <span
            className={`text-xs ${
              isValid
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-gray-400 dark:text-slate-500"
            }`}
          >
            {charCount} / {minChars} characters min
          </span>
        </label>
        <textarea
          value={jobDescription}
          onChange={(e) => onJobDescriptionChange(e.target.value)}
          placeholder="Paste the full job description here. Include responsibilities, requirements, qualifications, and any other details that will help optimize your resume..."
          rows={8}
          className="w-full px-4 py-3 rounded-xl border border-gray-200 dark:border-white/10 bg-white dark:bg-surface-850
                   text-gray-900 dark:text-slate-100 placeholder:text-gray-400 dark:placeholder:text-slate-500
                   focus:outline-none focus:ring-2 focus:ring-primary-500/20 dark:focus:ring-primary-500/30 focus:border-primary-500 dark:focus:border-primary-500/50
                   transition-all duration-200 resize-none"
        />
        {charCount > 0 && !isValid && (
          <p className="mt-1.5 text-xs text-amber-600 dark:text-amber-400">
            Please enter at least {minChars} characters for better results
          </p>
        )}
      </div>
    </div>
  );
}
