import axios from 'axios';
import type { UploadResponse, Job, JobStatusResponse, ResumeData, HealthCheck } from '../types';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_PREFIX = '/api/v1';

const api = axios.create({
  baseURL: `${API_URL}${API_PREFIX}`,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const apiService = {
  /**
   * Upload resume and job description
   */
  uploadResume: async (
    file: File,
    jobDescription: string,
    jobTitle?: string,
    companyName?: string
  ): Promise<UploadResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('job_description', jobDescription);
    if (jobTitle) formData.append('job_title', jobTitle);
    if (companyName) formData.append('company_name', companyName);

    const response = await api.post<UploadResponse>('/upload/resume', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  /**
   * Get job status
   */
  getJobStatus: async (jobId: string): Promise<JobStatusResponse> => {
    const response = await api.get<JobStatusResponse>(`/upload/jobs/${jobId}/status`);
    return response.data;
  },

  /**
   * Get job details
   */
  getJob: async (jobId: string): Promise<Job> => {
    const response = await api.get<Job>(`/upload/jobs/${jobId}`);
    return response.data;
  },

  /**
   * Get parsed resume
   */
  getResume: async (jobId: string): Promise<ResumeData> => {
    const response = await api.get<ResumeData>(`/upload/jobs/${jobId}/resume`);
    return response.data;
  },

  /**
   * List all jobs
   */
  listJobs: async (limit = 10, offset = 0): Promise<Job[]> => {
    const response = await api.get<Job[]>(`/upload/jobs?limit=${limit}&offset=${offset}`);
    return response.data;
  },

  /**
   * Delete a job
   */
  deleteJob: async (jobId: string): Promise<void> => {
    await api.delete(`/upload/jobs/${jobId}`);
  },

  /**
   * Download optimized resume (streams file directly)
   */
  downloadResume: async (jobId: string, format: 'docx' | 'pdf' = 'docx'): Promise<void> => {
    const response = await api.get(`/upload/jobs/${jobId}/download?format=${format}`, {
      responseType: 'blob',
    });

    // Extract filename from Content-Disposition header or use default
    const disposition = response.headers['content-disposition'] || '';
    const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
    const filename = filenameMatch ? filenameMatch[1] : `optimized_resume.${format}`;

    // Create download link and trigger browser download
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  },

  /**
   * Health check
   */
  healthCheck: async (): Promise<HealthCheck> => {
    const response = await api.get<HealthCheck>('/health');
    return response.data;
  },
};
