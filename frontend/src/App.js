import React, { useState, useEffect, useRef } from 'react';
import './App.css';

// Base URL for API - Use environment variable provided during Docker build
const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || "/api";

// --- Patterns/Names to Ignore during Client-Side Filtering ---
const IGNORE_PATTERNS = [
  'node_modules',
  '.git',
  'build',
  'dist',
  'coverage',
  'venv',
  'env',
  '.env',
  '__pycache__',
  '.vscode',
  '.idea',
  '.DS_Store',
  'Thumbs.db',
  '.log',
];

function App() {
  const [filesToUpload, setFilesToUpload] = useState([]);
  const [totalFilesSelected, setTotalFilesSelected] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [error, setError] = useState(null);
  const fileInputRef = useRef(null);

  // Polling interval for job status (in milliseconds)
  const STATUS_POLL_INTERVAL = 2000;
  const STATUS_POLL_MAX_TIME = 30 * 60 * 1000; // 30 minutes

  // --- Filter Function ---
  const filterIgnoredFiles = (fileList) => {
    const allFiles = Array.from(fileList);
    setTotalFilesSelected(allFiles.length);

    const filtered = allFiles.filter(file => {
      const relativePath = file.webkitRelativePath || file.name;
      if (!relativePath) return false;

      const filename = relativePath.split('/').pop();
      if (IGNORE_PATTERNS.includes(filename)) {
        return false;
      }

      if (filename.endsWith('.log')) {
        return false;
      }

      const segments = relativePath.split('/');
      for (let i = 0; i < segments.length - 1; i++) {
        if (IGNORE_PATTERNS.includes(segments[i])) {
          return false;
        }
      }

      return true;
    });

    console.log(`Selected ${allFiles.length} files, kept ${filtered.length} after filtering.`);
    return filtered;
  };

  // Effect to poll for job status
  useEffect(() => {
    let intervalId;
    let startTime;

    const checkJobStatus = async () => {
      if (!jobId) return;

      try {
        const response = await fetch(`${API_BASE_URL}/api/job-status/${jobId}`);

        if (!response.ok) {
          throw new Error(`Error checking job status: ${response.statusText}`);
        }

        const data = await response.json();
        setJobStatus(data);

        // If job is completed or failed, stop polling
        if (data.status === 'completed' || data.status === 'failed') {
          clearInterval(intervalId);
          console.log(`Job ${data.status}: `, data);
        }

        // Check if we've exceeded the maximum poll time
        const currentTime = new Date().getTime();
        if (currentTime - startTime > STATUS_POLL_MAX_TIME) {
          clearInterval(intervalId);
          console.warn('Job status polling exceeded maximum time limit');
        }
      } catch (err) {
        console.error('Error checking job status:', err);
        setError(err.message);
        clearInterval(intervalId);
      }
    };

    if (jobId) {
      startTime = new Date().getTime();
      // Check immediately, then start polling
      checkJobStatus();
      intervalId = setInterval(checkJobStatus, STATUS_POLL_INTERVAL);
    }

    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [jobId]);

  // Handle file selection
  const handleFileSelect = (event) => {
    const fileList = event.target.files || [];
    const filteredFiles = filterIgnoredFiles(fileList);
    setFilesToUpload(filteredFiles);
  };

  // Handle drag events
  const handleDragOver = (event) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (event) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (event) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragging(false);

    const items = event.dataTransfer.items;
    const files = event.dataTransfer.files;

    if (items && items.length > 0) {
      const filteredFiles = filterIgnoredFiles(files);
      setFilesToUpload(filteredFiles);
    }
  };

  // Handle browse files button click
  const handleBrowseClick = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  // Handle upload button click
  const handleUpload = async () => {
    if (filesToUpload.length === 0) {
      setError('No relevant files selected after filtering common ignores (like node_modules, .git, build, etc).');
      return;
    }

    setIsUploading(true);
    setError(null);

    const formData = new FormData();

    filesToUpload.forEach(file => {
      let relativePath = file.webkitRelativePath || file.name;
      formData.append('files', file, relativePath);
    });

    console.log(`Uploading ${filesToUpload.length} files...`);

    try {
      const response = await fetch(`${API_BASE_URL}/api/upload-codebase`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        let errorDetail = `Upload failed: ${response.statusText}`;
        try {
          const errorData = await response.json();
          if(errorData.detail) {
            errorDetail = errorData.detail;
          }
        } catch (parseError) {
          // Ignore if response is not JSON
        }
        if (response.status === 413) {
          errorDetail = "Upload failed: Request Entity Too Large. The selected code (after filtering) is still too big for the server's limit.";
        }
        throw new Error(errorDetail);
      }

      const data = await response.json();
      console.log('Upload successful', data);
      setJobId(data.job_id);

      setFilesToUpload([]);
      setTotalFilesSelected(0);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    } catch (err) {
      console.error('Error uploading files:', err);
      setError(err.message);
    } finally {
      setIsUploading(false);
    }
  };

  // Handle download
  const handleDownload = () => {
    if (!jobId || !jobStatus || jobStatus.status !== 'completed') return;

    window.location.href = `${API_BASE_URL}/api/download/${jobId}`;
  };

  // Reset state
  const handleReset = () => {
    setFilesToUpload([]);
    setTotalFilesSelected(0);
    setJobId(null);
    setJobStatus(null);
    setError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <h1 className="app-title">PromptMan</h1>
        <p className="app-subtitle">Generate LLM prompts from your codebase</p>
      </header>

      <section className="section-container">
        <div className="section-content">
          <h2 className="section-title">Upload Your Code</h2>
          <p className="section-description">
            Upload your code folder to generate a comprehensive prompt that describes the codebase.
          </p>

          {!jobId && (
            <>
              <div
                className={`drop-zone ${isDragging ? 'active' : ''}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={handleBrowseClick}
              >
                <i className="fas fa-folder-open fa-2x" style={{ marginBottom: '1rem', color: 'var(--primary-color)' }}></i>
                <p className="drop-zone-text">Drag & drop your code folder here</p>
                <p style={{color: 'var(--text-muted)'}}>or</p>
                <button className="btn">
                  <i className="fas fa-search"></i> Browse Files
                </button>
                <input
                  type="file"
                  ref={fileInputRef}
                  className="file-input"
                  onChange={handleFileSelect}
                  webkitdirectory="true"
                  directory="true"
                  multiple
                />
              </div>

              {totalFilesSelected > 0 && (
                <>
                  <div className="files-list">
                    <p><i className="fas fa-list"></i> Selected {totalFilesSelected} items, uploading {filesToUpload.length} relevant file(s)</p>
                    {filesToUpload.slice(0, 5).map((file, index) => (
                      <div key={index} className="files-list-item">
                        <i className="fas fa-file-code"></i> {file.webkitRelativePath || file.name}
                      </div>
                    ))}
                    {filesToUpload.length > 5 && (
                      <div className="files-list-item">
                        <i className="fas fa-ellipsis-h"></i> ... and {filesToUpload.length - 5} more relevant files
                      </div>
                    )}
                    {filesToUpload.length === 0 && totalFilesSelected > 0 && (
                      <div className="files-list-item" style={{color: 'var(--warning-color)'}}>
                        All selected files were filtered out (e.g., only node_modules, .git).
                      </div>
                    )}
                  </div>

                  <div style={{ marginTop: '1.5rem', textAlign: 'center' }}>
                    <button
                      className={`btn ${(isUploading || filesToUpload.length === 0) ? 'btn-disabled' : ''}`}
                      onClick={handleUpload}
                      disabled={isUploading || filesToUpload.length === 0}
                    >
                      {isUploading ? (
                        <><i className="fas fa-spinner fa-spin"></i> Uploading {filesToUpload.length} files...</>
                      ) : (
                        <><i className="fas fa-cogs"></i> Process {filesToUpload.length} Files</>
                      )}
                    </button>
                  </div>
                </>
              )}
            </>
          )}
        </div>
      </section>

      {error && (
        <section className="section-container">
          <div className="section-content">
            <div className="status-card failed">
              <div className="status-label"><i className="fas fa-exclamation-triangle"></i> Error</div>
              <div className="status-error">{error}</div>
              <button className="btn btn-reset" onClick={handleReset} style={{ marginTop: '1rem' }}>
                <i className="fas fa-sync-alt"></i> Start Over
              </button>
            </div>
          </div>
        </section>
      )}

      {jobId && (
        <section className="section-container">
          <div className="section-content">
            <h2 className="section-title">Processing Status</h2>

            <div className={`status-card ${jobStatus?.status || 'uploading'}`}>
              <div className="status-label">Status</div>
              <div className="status-text">
                {jobStatus?.status === 'pending' && 'Queued'}
                {jobStatus?.status === 'uploading' && 'Uploading Files'}
                {jobStatus?.status === 'processing' && 'Processing Code'}
                {jobStatus?.status === 'completed' && 'Processing Complete'}
                {jobStatus?.status === 'failed' && 'Processing Failed'}
                {!jobStatus?.status && 'Initializing...'}
              </div>

              {(jobStatus?.status === 'uploading' || jobStatus?.status === 'processing') && (
                <div className="progress-container">
                  <div className="progress-bar pulse" style={{ width: '100%' }}></div>
                </div>
              )}

              {jobStatus?.status === 'failed' && jobStatus.error && (
                <div className="status-error">{jobStatus.error}</div>
              )}

              {jobStatus?.status === 'completed' && (
                <button className="btn btn-download" onClick={handleDownload} style={{ marginTop: '1rem' }}>
                  Download Result
                </button>
              )}

              {(jobStatus?.status === 'completed' || jobStatus?.status === 'failed') && (
                <button className="btn btn-reset" onClick={handleReset} style={{ marginTop: '1rem', marginLeft: '0.5rem' }}>
                  Start New Job
                </button>
              )}
            </div>

            <div className="job-id-display">
              Job ID: {jobId}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

export default App;