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
  '.next',
  'package-lock.json',
  '.csv',
  'results'
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

  const handleRemoveFile = (indexToRemove) => {
    setFilesToUpload(prevFiles => {
      const newFiles = [...prevFiles];
      newFiles.splice(indexToRemove, 1);
      return newFiles;
    });
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <h1 className="app-title">PromptMan</h1>
        <p className="app-subtitle">Codebase-to-Prompt Generator</p>
      </header>

      {!jobId && !error && (
        <section className="section-container">
          <div className="section-content">
            <h2 className="section-title">
              <i className="fas fa-upload"></i>
              Upload Codebase
            </h2>
            <p className="section-description">
              Select your project folder. Common build artifacts and ignored files (node_modules, .git) are skipped automatically.
            </p>
            
            <div
              className={`drop-zone ${isDragging ? 'active' : ''}`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={handleBrowseClick}
              role="button"
              tabIndex="0"
              aria-label="Drop code folder here or click to browse"
            >
              <div className="drop-zone-content">
                <i className="fas fa-folder-open drop-zone-icon"></i>
                <p className="drop-zone-text">Drag & Drop Folder</p>
                <p style={{color: 'var(--text-muted)', fontSize: '0.9rem', margin: '0.5rem 0'}}>or</p>
                <button type="button" className="btn">
                  <i className="fas fa-search"></i> Browse Files
                </button>
              </div>
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
                  <p className="files-list-header">
                    <i className="fas fa-list-ul"></i>
                    Processing {filesToUpload.length} relevant files (out of {totalFilesSelected} selected)
                  </p>
                  {filesToUpload.map((file, index) => (
                    <div key={file.name + index} className="files-list-item">
                      <div className="file-item-content">
                        <i className="fas fa-file-code"></i>
                        <span className="file-item-text">{file.webkitRelativePath || file.name}</span>
                      </div>
                      <button
                        className="remove-file-btn"
                        onClick={(e) => { e.stopPropagation(); handleRemoveFile(index); }}
                        title="Remove file"
                        aria-label={`Remove file ${file.name}`}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    </div>
                  ))}
                  {filesToUpload.length === 0 && (
                    <div className="files-list-item" style={{color: 'var(--warning-color)', fontStyle: 'italic'}}>
                      All selected files/folders were ignored.
                    </div>
                  )}
                </div>

                <div style={{marginTop: '1.5rem', textAlign: 'center'}}>
                  <button
                    className={`btn ${(isUploading || filesToUpload.length === 0) ? 'btn-disabled' : ''}`}
                    onClick={handleUpload}
                    disabled={isUploading || filesToUpload.length === 0}
                  >
                    {isUploading ? (
                      <><i className="fas fa-spinner fa-spin"></i> Uploading ({filesToUpload.length})...</>
                    ) : (
                      <><i className="fas fa-cogs"></i> Process {filesToUpload.length} Files</>
                    )}
                  </button>
                </div>
              </>
            )}
          </div>
        </section>
      )}

      {error && !jobId && (
        <section className="section-container">
          <div className="section-content">
            <div className="status-card failed">
              <div className="status-label">
                <i className="fas fa-exclamation-triangle"></i> Error
              </div>
              <div className="status-error">{error}</div>
              <div class="status-actions">
                <button className="btn btn-reset" onClick={handleReset}>
                  <i className="fas fa-sync-alt"></i> Try Again
                </button>
              </div>
            </div>
          </div>
        </section>
      )}

      {jobId && (
        <section className="section-container">
          <div className="section-content">
            <h2 className="section-title">
              <i className="fas fa-tasks"></i> Processing Status
            </h2>
            <div className={`status-card ${jobStatus?.status || 'pending'}`}>
              <div className="status-label">
                <i className="fas fa-info-circle"></i> Status
              </div>
              <div className="status-text">
                {jobStatus?.status === 'pending' && <><i className="fas fa-clock"></i> Queued for Processing...</>}
                {jobStatus?.status === 'uploading' && <><i className="fas fa-spinner fa-spin"></i> Uploading Files...</>}
                {jobStatus?.status === 'processing' && <><i className="fas fa-cog fa-spin"></i> Analyzing Codebase...</>}
                {jobStatus?.status === 'completed' && <><i className="fas fa-check-circle"></i> Processing Complete!</>}
                {jobStatus?.status === 'failed' && <><i className="fas fa-times-circle"></i> Processing Failed</>}
                {!jobStatus && <>Initializing...</>}
              </div>

              {(jobStatus?.status === 'pending' || jobStatus?.status === 'uploading' || jobStatus?.status === 'processing') && (
                <div className="progress-container">
                  <div className="progress-bar"></div>
                </div>
              )}

              {jobStatus?.status === 'failed' && jobStatus.error && (
                <div className="status-error">{jobStatus.error}</div>
              )}

              <div className="status-actions">
                {jobStatus?.status === 'completed' && (
                  <button className="btn btn-download" onClick={handleDownload}>
                    <i className="fas fa-download"></i> Download Prompt
                  </button>
                )}

                {(jobStatus?.status === 'completed' || jobStatus?.status === 'failed') && (
                  <button className="btn btn-reset" onClick={handleReset}>
                    <i className="fas fa-redo-alt"></i> Start New Job
                  </button>
                )}
              </div>
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