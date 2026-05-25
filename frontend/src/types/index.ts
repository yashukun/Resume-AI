export type JobStatus = 
  | 'pending'
  | 'parsing'
  | 'processing'
  | 'optimizing'
  | 'completed'
  | 'failed';

export interface Job {
  id: string;
  status: JobStatus;
  original_filename: string;
  file_type: string;
  job_description: string;
  job_title?: string;
  company_name?: string;
  optimized_file_path?: string;
  error_message?: string;
  created_at: string;
  updated_at: string;
  completed_at?: string;
}

export interface JobStatusResponse {
  id: string;
  status: JobStatus;
  progress_message?: string;
  error_message?: string;
}

export interface UploadResponse {
  job_id: string;
  message: string;
  status: JobStatus;
  user_resume_id?: string;
  reused_existing_parse?: boolean;
}

export interface UserResumeSummary {
  id: string;
  original_filename: string;
  file_type: string;
  file_hash: string;
  name?: string;
  is_parsed: boolean;
  created_at: string;
}

export interface PersonalInfo {
  name?: string;
  email?: string;
  phone?: string;
  location?: string;
  linkedin?: string;
  github?: string;
}

export interface ResumeData {
  id: string;
  job_id: string;
  raw_text?: string;
  personal_info?: PersonalInfo;
  summary?: string;
  experience?: Array<Record<string, unknown>>;
  education?: Array<Record<string, unknown>>;
  skills?: string[];
  ats_score?: Record<string, unknown>;
  created_at: string;
}

export interface HealthCheck {
  status: string;
  version: string;
  services: Record<string, string>;
}
