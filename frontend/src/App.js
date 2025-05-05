import React, { useState, useEffect, useRef, useCallback } from 'react';
import './App.css';

const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || "/api";

// Keep existing ignore patterns
const IGNORE_PATH_PATTERNS = new Set([
  'node_modules', '.git', '__pycache__', '.pytest_cache',
  'venv', 'env', '.env', '.venv', '.idea', '.vscode'
]);

const IGNORE_FILE_PATTERNS = new Set([
  'package-lock.json', 'yarn.lock', '.gitignore', '.DS_Store'
]);

const IGNORE_EXTENSIONS = new Set([
  '.pyc', '.pyo', '.pyd', '.so', '.dll', '.dylib',
  '.log', '.tmp', '.temp', '.swp'
]);

function App() {
  const [filesToUpload, setFilesToUpload] = useState([]);
  const [totalFilesSelected, setTotalFilesSelected] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [error, setError] = useState(null);
  const [isFiltering, setIsFiltering] = useState(false);
  const [repoUrl, setRepoUrl] = useState('');
  const [isProcessingRepo, setIsProcessingRepo] = useState(false);
  const fileInputRef = useRef(null);

  const STATUS_POLL_INTERVAL = 2000;
  const STATUS_POLL_MAX_TIME = 30 * 60 * 1000;

  // --- Status Polling Effect ---
  useEffect(() => {
    let intervalId = null;
    let startTime = 0;

    const checkJobStatus = async () => {
      if (!jobId) return;

      try {
        const response = await fetch(`${API_BASE_URL}/api/job-status/${jobId}`);
        if (!response.ok) {
          if (response.status === 404) {
            setError(`Job ${jobId} not found or may have expired.`);
          } else {
            throw new Error(`Error checking job status: ${response.statusText}`);
          }
          clearInterval(intervalId);
          intervalId = null;
          return;
        }

        const data = await response.json();
        setJobStatus(data);

        if (data.status === 'completed' || data.status === 'failed') {
          clearInterval(intervalId);
          intervalId = null;
        }

        if (intervalId && Date.now() - startTime > STATUS_POLL_MAX_TIME) {
          clearInterval(intervalId);
          intervalId = null;
          setError('Polling timed out. Please check status manually or try again.');
        }
      } catch (err) {
        console.error('Error checking job status:', err);
        setError(err.message);
        if (intervalId) clearInterval(intervalId);
        intervalId = null;
      }
    };

    if (jobId) {
      startTime = Date.now();
      setJobStatus(null);
      setError(null);
      checkJobStatus();
      intervalId = setInterval(checkJobStatus, STATUS_POLL_INTERVAL);
    }

    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [jobId]);

  // --- File Handling Functions ---
  const filterIgnoredFiles = useCallback((fileList) => {
    const allFiles = Array.from(fileList);
    setTotalFilesSelected(allFiles.length);
    const filtered = allFiles.filter(file => {
      const relativePath = file.webkitRelativePath || file.name;
      if (!relativePath) return false;
      const segments = relativePath.split('/');
      const filename = segments[segments.length - 1];
      if (filename.startsWith('.')) return false;
      if (IGNORE_FILE_PATTERNS.has(filename)) return false;
      const lastDotIndex = filename.lastIndexOf('.');
      if (lastDotIndex !== -1) {
        const extension = filename.slice(lastDotIndex);
        if (IGNORE_EXTENSIONS.has(extension)) return false;
      }
      for (let i = 0; i < segments.length - 1; i++) {
        const segment = segments[i];
        if (segment.startsWith('.')) return false;
        if (IGNORE_PATH_PATTERNS.has(segment)) return false;
      }
      return true;
    });
    return filtered;
  }, []);

  const handleFileSelect = useCallback((event) => {
    const fileList = event.target.files || [];
    if (fileList.length === 0) return;
    setIsFiltering(true);
    setError(null);
    setFilesToUpload([]);
    setTotalFilesSelected(0);
    setTimeout(() => {
      const filteredFiles = filterIgnoredFiles(fileList);
      setFilesToUpload(filteredFiles);
      setIsFiltering(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }, 0);
  }, [filterIgnoredFiles]);

  const handleDragOver = useCallback((event) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((event) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((event) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragging(false);
    setError(null);
    setFilesToUpload([]);
    setTotalFilesSelected(0);
    const items = event.dataTransfer.items;
    const files = event.dataTransfer.files;
    if (items && items.length > 0) {
      setIsFiltering(true);
      setTimeout(() => {
        const filteredFiles = filterIgnoredFiles(files);
        setFilesToUpload(filteredFiles);
        setIsFiltering(false);
      }, 0);
    }
  }, [filterIgnoredFiles]);

  const handleBrowseClick = useCallback(() => {
    if (fileInputRef.current) fileInputRef.current.click();
  }, []);

  const handleRemoveFile = useCallback((indexToRemove) => {
    setFilesToUpload(prevFiles => prevFiles.filter((_, index) => index !== indexToRemove));
  }, []);

  // --- Upload and Repository Processing ---
  const handleUpload = useCallback(async () => {
    if (filesToUpload.length === 0) {
      setError('No relevant files selected after filtering.');
      return;
    }
    setIsUploading(true);
    setError(null);
    setJobId(null);
    setJobStatus(null);

    const formData = new FormData();
    filesToUpload.forEach(file => {
      formData.append('files', file, file.webkitRelativePath || file.name);
    });

    try {
      const response = await fetch(`${API_BASE_URL}/api/upload-codebase`, {
        method: 'POST',
        body: formData
      });
      if (!response.ok) {
        let errorDetail = `Upload failed (${response.status})`;
        try {
          const errorData = await response.json();
          if (errorData.detail) errorDetail = errorData.detail;
        } catch (e) { /* ignore */ }
        throw new Error(errorDetail);
      }
      const data = await response.json();
      setFilesToUpload([]);
      setTotalFilesSelected(0);
      setJobId(data.job_id);
    } catch (err) {
      console.error('Error uploading files:', err);
      setError(err.message);
      setJobId(null);
    } finally {
      setIsUploading(false);
    }
  }, [filesToUpload]);

  const handleRepoUrlChange = useCallback((event) => {
    setRepoUrl(event.target.value);
  }, []);

  const handleProcessRepo = useCallback(async () => {
    if (!repoUrl.trim()) {
      setError('Please enter a repository URL.');
      return;
    }

    if (!repoUrl.startsWith('http://') && !repoUrl.startsWith('https://')) {
      setError('Please enter a valid HTTP/HTTPS repository URL.');
      return;
    }

    setIsProcessingRepo(true);
    setError(null);
    setJobId(null);
    setJobStatus(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/process-repo`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: repoUrl })
      });

      if (!response.ok) {
        let errorDetail = `Failed to start processing (${response.status})`;
        try {
          const errorData = await response.json();
          if (errorData.detail) errorDetail = errorData.detail;
        } catch (e) { /* ignore */ }
        throw new Error(errorDetail);
      }

      const data = await response.json();
      setRepoUrl('');
      setJobId(data.job_id);
    } catch (err) {
      console.error('Error processing repository URL:', err);
      setError(err.message);
      setJobId(null);
    } finally {
      setIsProcessingRepo(false);
    }
  }, [repoUrl]);

  // --- Result Handling ---
  const handleDownload = useCallback(() => {
    if (!jobId || !jobStatus || jobStatus.status !== 'completed') return;
    window.location.href = `${API_BASE_URL}/api/download/${jobId}`;
  }, [jobId, jobStatus]);

  const handleReset = useCallback(() => {
    setFilesToUpload([]);
    setTotalFilesSelected(0);
    setRepoUrl('');
    setJobId(null);
    setJobStatus(null);
    setError(null);
    setIsUploading(false);
    setIsProcessingRepo(false);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, []);

  return (
    <div className="app-container">
      <header className="app-header">
        <h1 className="app-title">PromptMan</h1>
        <p className="app-subtitle">Codebase-to-Prompt Generator</p>
      </header>

      {!jobId ? (
        <>
          <section className="section-container">
            <div className="section-content">
              <h2 className="section-title">
                <i className="fas fa-upload"></i> Upload Codebase Folder
              </h2>
              <p className="section-description">
                Select your project folder. Common artifacts (node_modules, .git) are skipped.
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
                  <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', margin: '0.5rem 0' }}>or</p>
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
              {isFiltering && (
                <div className="filtering-overlay">
                  <div className="filtering-content">
                    <div className="filtering-spinner"></div>
                    <p>Filtering files...</p>
                  </div>
                </div>
              )}
              {totalFilesSelected > 0 && !isFiltering && (
                <>
                  <div className="files-list">
                    <p className="files-list-header">
                      <i className="fas fa-list-ul"></i> Processing {filesToUpload.length} relevant files (out of {totalFilesSelected} selected)
                    </p>
                    {filesToUpload.map((file, index) => (
                      <div key={file.name + index + file.size} className="files-list-item">
                        <div className="file-item-content">
                          <i className="fas fa-file-code"></i>
                          <span className="file-item-text" title={file.webkitRelativePath || file.name}>
                            {file.webkitRelativePath || file.name}
                          </span>
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
                      <div className="files-list-item" style={{ color: 'var(--warning-color)', fontStyle: 'italic' }}>
                        All selected files/folders were ignored.
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
                        <><i className="fas fa-spinner fa-spin"></i> Uploading...</>
                      ) : (
                        <><i className="fas fa-cogs"></i> Process {filesToUpload.length} Files</>
                      )}
                    </button>
                  </div>
                </>
              )}
            </div>
          </section>

          <section className="section-container">
            <div className="section-content">
              <h2 className="section-title">
                <i className="fab fa-git-alt"></i> Process Public Repository
              </h2>
              <p className="section-description">
                Enter the URL of a public Git repository (e.g., GitHub, GitLab).
              </p>
              <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                <input
                  type="url"
                  value={repoUrl}
                  onChange={handleRepoUrlChange}
                  placeholder="https://github.com/owner/repo.git"
                  aria-label="Repository URL"
                  disabled={isProcessingRepo}
                  style={{
                    flexGrow: 1,
                    padding: '0.6rem 0.8rem',
                    borderRadius: '6px',
                    border: '1px solid var(--card-border-color)',
                    background: 'rgba(var(--card-bg-rgb), 0.8)',
                    color: 'var(--text-color)',
                    fontSize: '0.9rem'
                  }}
                />
                <button
                  className={`btn ${isProcessingRepo ? 'btn-disabled' : ''}`}
                  onClick={handleProcessRepo}
                  disabled={isProcessingRepo}
                >
                  {isProcessingRepo ? (
                    <><i className="fas fa-spinner fa-spin"></i> Starting...</>
                  ) : (
                    <><i className="fas fa-cogs"></i> Process URL</>
                  )}
                </button>
              </div>
            </div>
          </section>

          {error && (
            <section className="section-container">
              <div className="section-content">
                <div className="status-card failed">
                  <div className="status-label">
                    <i className="fas fa-exclamation-triangle"></i> Error
                  </div>
                  <div className="status-error">{error}</div>
                  <div className="status-actions">
                    <button className="btn" onClick={handleReset}>
                      <i className="fas fa-sync-alt"></i> Clear
                    </button>
                  </div>
                </div>
              </div>
            </section>
          )}
        </>
      ) : (
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
                {jobStatus?.status === 'pending' && <><i className="fas fa-clock"></i> Queued...</>}
                {jobStatus?.status === 'uploading' && <><i className="fas fa-spinner fa-spin"></i> Uploading Files...</>}
                {jobStatus?.status === 'cloning' && <><i className="fas fa-spinner fa-spin"></i> Cloning Repository...</>}
                {jobStatus?.status === 'processing' && <><i className="fas fa-cog fa-spin"></i> Analyzing Codebase...</>}
                {jobStatus?.status === 'completed' && <><i className="fas fa-check-circle"></i> Processing Complete!</>}
                {jobStatus?.status === 'failed' && <><i className="fas fa-times-circle"></i> Processing Failed</>}
                {!jobStatus && <><i className="fas fa-spinner fa-spin"></i> Loading Status...</>}
              </div>

              {(jobStatus?.status === 'pending' || jobStatus?.status === 'uploading' ||
                jobStatus?.status === 'cloning' || jobStatus?.status === 'processing') && (
                <div className="progress-container">
                  <div className="progress-bar"></div>
                </div>
              )}

              {jobStatus?.status === 'failed' && jobStatus.error && (
                <div className="status-error">{jobStatus.error}</div>
              )}
              {error && !jobStatus?.error && (
                <div className="status-error">{error}</div>
              )}

              <div className="status-actions">
                {jobStatus?.status === 'completed' && (
                  <button className="btn" onClick={handleDownload}>
                    <i className="fas fa-download"></i> Download Prompt
                  </button>
                )}
                {(jobStatus?.status === 'completed' || jobStatus?.status === 'failed' || error) && (
                  <button className="btn" onClick={handleReset}>
                    <i className="fas fa-redo-alt"></i> Start New Job
                  </button>
                )}
              </div>
            </div>
            <div className="job-id-display">Job ID: {jobId}</div>
          </div>
        </section>
      )}
    </div>
  );
}

export default App;