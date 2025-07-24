import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactGA from 'react-ga4';
import './App.css';

const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || "/api";

// Initialize Google Analytics
const GA_MEASUREMENT_ID = process.env.REACT_APP_GA_MEASUREMENT_ID;
if (GA_MEASUREMENT_ID) {
  ReactGA.initialize(GA_MEASUREMENT_ID);
  console.log('GA Initialized with ID:', GA_MEASUREMENT_ID);
} else {
  console.warn('REACT_APP_GA_MEASUREMENT_ID not found in .env. Analytics will not be sent.');
}

// Helper function for sending GA events
const sendGAEvent = (category, action, label = null, value = null) => {
  if (GA_MEASUREMENT_ID) {
    ReactGA.event({
      category,
      action,
      ...(label && { label }),
      ...(value && { value })
    });
  }
};

// Defaults 
const DEFAULT_CRAWL_MAX_DEPTH = 0;
const DEFAULT_CRAWL_MAX_PAGES = 5;
const DEFAULT_CRAWL_STAY_ON_DOMAIN = true;

// existing ignore patterns
const IGNORE_PATH_PATTERNS = new Set([
  'node_modules', '.git', '__pycache__', '.pytest_cache',
  'venv', 'env', '.env', '.venv', '.idea', '.vscode',
  'build', 'dist', 'target', 'out', 'bin', 'release', 'debug', '__deploy__',
  '_build', 'site', 'public',
  'vendor', 'deps', 'Pods', 'Carthage', 'packages',
  '.history', '.metals', '.bsp'
]);

const IGNORE_FILE_PATTERNS = new Set([
  'package-lock.json', 'yarn.lock', '.gitignore', '.DS_Store', 'pnpm-lock.yaml',
  'Thumbs.db'
]);

const IGNORE_EXTENSIONS = new Set([
  '.pyc', '.pyo', '.pyd', '.so', '.dll', '.dylib',
  '.log', '.tmp', '.temp', '.swp', '.svg', 
  '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', 
  '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', 
  '.zip', '.tar.gz', '.rar', '.gz', '.bz2', '.7z', '.iso', '.dmg', '.pkg', '.deb', '.rpm', 
  '.mp3', '.wav', '.ogg', '.mp4', '.mov', '.avi', '.mkv', '.webm', 
  '.pkl', '.parquet', '.hdf5', '.feather', '.arrow', '.csv', '.json', '.xml', '.sqlite', '.db', 
  '.pt', '.pth', '.pb', '.tflite', '.onnx', '.h5', '.keras', 
  '.stl', '.obj', '.fbx', '.dae', '.blend', '.dwg', '.dxf', '.step', '.iges', 
  '.ttf', '.otf', '.woff', '.woff2', '.eot', 
  '.o', 
  '.class', '.jar', '.war', '.ear' 
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
  const [isFileSelecting, setIsFileSelecting] = useState(false);
  const [repoUrl, setRepoUrl] = useState('');
  const [isProcessingRepo, setIsProcessingRepo] = useState(false);
  const [repoIncludePatterns, setRepoIncludePatterns] = useState('');
  const [repoExcludePatterns, setRepoExcludePatterns] = useState('');
  const fileInputRef = useRef(null);

  const [activeInputMode, setActiveInputMode] = useState('upload');
  const [showRepoOptions, setShowRepoOptions] = useState(false);

  const [websiteUrl, setWebsiteUrl] = useState('');
  const [isProcessingWebsite, setIsProcessingWebsite] = useState(false);

  // Crawl Options State 
  const [crawlMaxDepth, setCrawlMaxDepth] = useState(DEFAULT_CRAWL_MAX_DEPTH);
  const [crawlMaxPages, setCrawlMaxPages] = useState(DEFAULT_CRAWL_MAX_PAGES);
  const [crawlStayOnDomain, setCrawlStayOnDomain] = useState(DEFAULT_CRAWL_STAY_ON_DOMAIN);
  const [crawlIncludePatterns, setCrawlIncludePatterns] = useState('');
  const [crawlExcludePatterns, setCrawlExcludePatterns] = useState('');
  const [crawlKeywords, setCrawlKeywords] = useState('');
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  const STATUS_POLL_INTERVAL = 2000;
  const STATUS_POLL_MAX_TIME = 30 * 60 * 1000;

  // Common Job Handlers 
  const handleJobSubmitError = useCallback((error, jobType, input = '') => {
    console.error(`Error processing ${jobType}:`, error);
    setError(error.message);
    setJobId(null);
    sendGAEvent('Job Submit', 'Error', `${jobType} - ${error.message.substring(0, 100)}`);
  }, []);

  const handleJobSubmitSuccess = useCallback((data, jobType, input = '') => {
    setJobId(data.job_id);
    sendGAEvent('Job Submit', 'Success', jobType);
  }, []);

  // Status Polling Effect
  useEffect(() => {
    let intervalId = null;
    let startTime = 0;

    const checkJobStatus = async () => {
      if (!jobId) return;
      try {
        const response = await fetch(`${API_BASE_URL}/api/job-status/${jobId}`);
        if (!response.ok) {
          let errorMsg = `Job ${jobId} status check failed: ${response.status}`;
          if (response.status === 404) errorMsg = `Job ${jobId} not found or expired.`;
          setError(errorMsg);
          sendGAEvent('Job Status', 'Error - API Fetch', `${jobId} - ${response.status}`);
          clearInterval(intervalId);
          intervalId = null;
          return;
        }

        const data = await response.json();
        const jobType = data.type || 'unknown';

        // Only update and send event if status string changes
        if (jobStatus?.status !== data.status) {
          if (data.status === 'completed') {
            sendGAEvent('Job Status', 'Completed', jobType);
          } else if (data.status === 'failed') {
            sendGAEvent('Job Status', 'Failed', jobType);
          }
        }
        setJobStatus(data);

        if (data.status === 'completed' || data.status === 'failed') {
          clearInterval(intervalId);
          intervalId = null;
        }

        if (intervalId && Date.now() - startTime > STATUS_POLL_MAX_TIME) {
          setError('Polling timed out. Please check status manually or try again.');
          sendGAEvent('Job Status', 'Error - Polling Timeout', jobType);
          clearInterval(intervalId);
          intervalId = null;
        }
      } catch (err) {
        console.error('Error checking job status:', err);
        setError(err.message);
        sendGAEvent('Job Status', 'Error - Client Exception', jobId);
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

  // File Handling Functions 
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

  const handleBrowseClick = useCallback(() => {
    if (fileInputRef.current) {
      setIsFileSelecting(true);
      fileInputRef.current.click();
    }
  }, []);

  const handleFileSelect = useCallback((event) => {
    const fileList = event.target.files || [];
    if (fileList.length === 0) {
      setIsFileSelecting(false);
      return;
    }
    
    sendGAEvent('User Interaction', 'Select Files', 'upload', fileList.length);
    setIsFiltering(true);
    setError(null);
    setFilesToUpload([]);
    setTotalFilesSelected(0);
    
    // Add a small delay to ensure the loading state is visible
    setTimeout(() => {
      const filteredFiles = filterIgnoredFiles(fileList);
      setFilesToUpload(filteredFiles);
      setIsFiltering(false);
      setIsFileSelecting(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
      
      if (filteredFiles.length === 0) {
        sendGAEvent('User Interaction', 'No Valid Files', 'upload', fileList.length);
      }
    }, 500);
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
    setIsFileSelecting(true);
    const items = event.dataTransfer.items;
    const files = event.dataTransfer.files;
    if (items && items.length > 0) {
      setIsFiltering(true);
      setTimeout(() => {
        const filteredFiles = filterIgnoredFiles(files);
        setFilesToUpload(filteredFiles);
        setIsFiltering(false);
        setIsFileSelecting(false);
      }, 500);
    } else {
      setIsFileSelecting(false);
    }
  }, [filterIgnoredFiles]);

  const handleRemoveFile = useCallback((indexToRemove) => {
    setFilesToUpload(prevFiles => prevFiles.filter((_, index) => index !== indexToRemove));
  }, []);

  // Upload and Repository Processing 
  const handleUpload = useCallback(async () => {
    if (filesToUpload.length === 0) {
      setError('No relevant files selected after filtering.');
      return;
    }

    setIsUploading(true);
    setError(null);
    setJobId(null);
    setJobStatus(null);

    sendGAEvent('Job Submit', 'Start', 'upload', filesToUpload.length);

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
      handleJobSubmitSuccess(data, 'upload', `${filesToUpload.length} files`);
      setFilesToUpload([]);
      setTotalFilesSelected(0);
    } catch (err) {
      handleJobSubmitError(err, 'upload', `${filesToUpload.length} files`);
    } finally {
      setIsUploading(false);
    }
  }, [filesToUpload, handleJobSubmitSuccess, handleJobSubmitError]);

  const handleRepoUrlChange = useCallback((event) => {
    setRepoUrl(event.target.value);
  }, []);

  const handleRepoIncludePatternsChange = useCallback((event) => {
    setRepoIncludePatterns(event.target.value);
  }, []);

  const handleRepoExcludePatternsChange = useCallback((event) => {
    setRepoExcludePatterns(event.target.value);
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

    sendGAEvent('Job Submit', 'Start', 'repo');

    try {
      const response = await fetch(`${API_BASE_URL}/api/process-repo`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          repo_url: repoUrl,
          include_patterns: repoIncludePatterns || undefined,
          exclude_patterns: repoExcludePatterns || undefined
        })
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
      handleJobSubmitSuccess(data, 'repo', repoUrl);
      setRepoUrl('');
    } catch (err) {
      handleJobSubmitError(err, 'repo', repoUrl);
    } finally {
      setIsProcessingRepo(false);
    }
  }, [repoUrl, repoIncludePatterns, repoExcludePatterns, handleJobSubmitSuccess, handleJobSubmitError]);

  const handleWebsiteUrlChange = useCallback((event) => {
    setWebsiteUrl(event.target.value);
  }, []);

  const handleMaxDepthChange = useCallback((e) => {
    setCrawlMaxDepth(e.target.value === '' ? '' : Math.min(10, Math.max(0, parseInt(e.target.value, 10) || 0)));
  }, []);

  const handleMaxPagesChange = useCallback((e) => {
    setCrawlMaxPages(e.target.value === '' ? '' : Math.min(1000, Math.max(1, parseInt(e.target.value, 10) || 1)));
  }, []);

  const handleStayOnDomainChange = useCallback((e) => {
    setCrawlStayOnDomain(e.target.checked);
  }, []);

  const handleIncludePatternsChange = useCallback((e) => {
    setCrawlIncludePatterns(e.target.value);
  }, []);

  const handleExcludePatternsChange = useCallback((e) => {
    setCrawlExcludePatterns(e.target.value);
  }, []);

  const handleKeywordsChange = useCallback((e) => {
    setCrawlKeywords(e.target.value);
  }, []);

  const handleProcessWebsite = useCallback(async () => {
    const url = websiteUrl.trim();
    if (!url) {
      setError('Please enter a website URL.');
      return;
    }

    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      setError('Please enter a valid HTTP/HTTPS website URL.');
      return;
    }

    setIsProcessingWebsite(true);
    setError(null);
    setJobId(null);
    setJobStatus(null);

    sendGAEvent('Job Submit', 'Start', 'website');

    const payload = {
      website_url: url,
      max_depth: crawlMaxDepth === '' ? null : crawlMaxDepth,
      max_pages: crawlMaxPages === '' ? null : crawlMaxPages,
      stay_on_domain: crawlStayOnDomain,
      include_patterns: crawlIncludePatterns.trim() || null,
      exclude_patterns: crawlExcludePatterns.trim() || null,
      keywords: crawlKeywords.trim() || null,
    };

    try {
      const response = await fetch(`${API_BASE_URL}/api/process-website`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
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
      handleJobSubmitSuccess(data, 'website', url);
      setWebsiteUrl('');
    } catch (err) {
      handleJobSubmitError(err, 'website', url);
    } finally {
      setIsProcessingWebsite(false);
    }
  }, [websiteUrl, crawlMaxDepth, crawlMaxPages, crawlStayOnDomain, 
      crawlIncludePatterns, crawlExcludePatterns, crawlKeywords,
      handleJobSubmitSuccess, handleJobSubmitError]);

  // Result Handling 
  const handleDownload = useCallback(() => {
    if (!jobId || !jobStatus || jobStatus.status !== 'completed') return;
    
    const jobType = jobStatus.type || 'unknown';
    sendGAEvent('User Interaction', 'Download Result', jobType);
    
    window.location.href = `${API_BASE_URL}/api/download/${jobId}`;
  }, [jobId, jobStatus]);

  const handleOpenLLM = useCallback((llmUrl) => {
    if (!jobId || !jobStatus || jobStatus.status !== 'completed') return;
    
    const jobType = jobStatus.type || 'unknown';
    sendGAEvent('User Interaction', 'Open LLM Interface', `${jobType} - ${llmUrl}`);
    
    window.open(llmUrl, '_blank');
  }, [jobId, jobStatus]);

  // Updated Reset Handler
  const handleReset = useCallback(() => {
    sendGAEvent('User Interaction', 'Reset Form');
    
    setFilesToUpload([]);
    setTotalFilesSelected(0);
    setRepoUrl('');
    setWebsiteUrl('');
    // Reset crawl options
    setCrawlMaxDepth(DEFAULT_CRAWL_MAX_DEPTH);
    setCrawlMaxPages(DEFAULT_CRAWL_MAX_PAGES);
    setCrawlStayOnDomain(DEFAULT_CRAWL_STAY_ON_DOMAIN);
    setCrawlIncludePatterns('');
    setCrawlExcludePatterns('');
    setCrawlKeywords('');
    setShowAdvancedOptions(false);
    // Reset job/error state
    setJobId(null);
    setJobStatus(null);
    setError(null);
    setIsUploading(false);
    setIsProcessingRepo(false);
    setIsProcessingWebsite(false);
    setActiveInputMode('upload');
    setShowRepoOptions(false);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, []);

  const isProcessing = isUploading || isProcessingRepo || isProcessingWebsite || isFiltering;

  return (
    <div className="app-container">
      <header className="app-header">
        <h1 className="app-title">PromptMan</h1>
        <p className="app-subtitle">Codebase & Website to Prompt Generator</p>
      </header>

      {!jobId ? (
        <section className="section-container">
          <div className="section-content">
            {/* Tab Header */}
            <div className="input-mode-tabs">
              <button className={`tab-button ${activeInputMode === 'upload' ? 'active' : ''}`}
                      onClick={() => setActiveInputMode('upload')} disabled={isProcessing}>
                <i className="fas fa-upload"></i> Upload Folder
              </button>
              <button className={`tab-button ${activeInputMode === 'repo' ? 'active' : ''}`}
                      onClick={() => setActiveInputMode('repo')} disabled={isProcessing}>
                <i className="fab fa-git-alt"></i> Repository URL
              </button>
              <button className={`tab-button ${activeInputMode === 'website' ? 'active' : ''}`}
                      onClick={() => setActiveInputMode('website')} disabled={isProcessing}>
                <i className="fas fa-globe"></i> Website URL
              </button>
            </div>

            {/* Tab Content */}
            <div className="tab-content">
              {/* Upload Tab */}
              {activeInputMode === 'upload' && (
                <>
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
                    style={{ position: 'relative' }}
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
                      disabled={isUploading || isProcessingRepo}
                    />
                    {(isFiltering || isFileSelecting) && (
                      <div className="filtering-overlay">
                        <div className="filtering-content">
                          <div className="filtering-spinner"></div>
                          <p>{isFileSelecting ? 'Selecting files...' : 'Filtering files...'}</p>
                        </div>
                      </div>
                    )}
                  </div>
                  
                  {totalFilesSelected > 0 && !isFiltering && !isFileSelecting && (
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
                              disabled={isUploading}
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
                          disabled={isUploading || filesToUpload.length === 0 || isProcessingRepo}
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
                </>
              )}

              {/* Repository Tab */}
              {activeInputMode === 'repo' && (
                <>
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
                      disabled={isProcessingRepo || isUploading}
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
                      className={`btn ${(isProcessingRepo || !repoUrl.trim()) ? 'btn-disabled' : ''}`}
                      onClick={handleProcessRepo}
                      disabled={isProcessingRepo || isUploading || !repoUrl.trim()}
                    >
                      {isProcessingRepo ? (
                        <><i className="fas fa-spinner fa-spin"></i> Starting...</>
                      ) : (
                        <><i className="fas fa-cogs"></i> Process URL</>
                      )}
                    </button>
                  </div>

                  {/* Advanced Options Toggle */}
                  <div style={{ marginBottom: '1rem', borderTop: '1px solid var(--card-border-color)', paddingTop: '1rem' }}>
                    <button onClick={() => setShowRepoOptions(!showRepoOptions)}
                            style={{ background: 'none', border: 'none', color: 'var(--primary-color)', cursor: 'pointer', padding: '0.5rem 0', fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                            aria-expanded={showRepoOptions}>
                      <i className={`fas fa-chevron-${showRepoOptions ? 'down' : 'right'}`}></i>
                      {showRepoOptions ? 'Hide' : 'Show'} Clone Options
                    </button>
                  </div>

                  {/* Repo Options Grid */}
                  {showRepoOptions && (
                    <div className="crawl-options-grid">
                      <div style={{ flex: 1, gridColumn: '1 / -1' }}>
                        <label htmlFor="repoIncludePatterns" style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.9rem' }}>
                          Include Patterns (comma-separated glob patterns)
                        </label>
                        <input
                          id="repoIncludePatterns"
                          type="text"
                          value={repoIncludePatterns}
                          onChange={handleRepoIncludePatternsChange}
                          placeholder="*.py,*.js,*.ts"
                          disabled={isProcessingRepo || isUploading}
                          style={{
                            width: '100%',
                            padding: '0.6rem 0.8rem',
                            borderRadius: '6px',
                            border: '1px solid var(--card-border-color)',
                            background: 'rgba(var(--card-bg-rgb), 0.8)',
                            color: 'var(--text-color)',
                            fontSize: '0.9rem'
                          }}
                        />
                      </div>
                      <div style={{ flex: 1, gridColumn: '1 / -1' }}>
                        <label htmlFor="repoExcludePatterns" style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.9rem' }}>
                          Exclude Patterns (comma-separated glob patterns)
                        </label>
                        <input
                          id="repoExcludePatterns"
                          type="text"
                          value={repoExcludePatterns}
                          onChange={handleRepoExcludePatternsChange}
                          placeholder="node_modules,__pycache__,*.log"
                          disabled={isProcessingRepo || isUploading}
                          style={{
                            width: '100%',
                            padding: '0.6rem 0.8rem',
                            borderRadius: '6px',
                            border: '1px solid var(--card-border-color)',
                            background: 'rgba(var(--card-bg-rgb), 0.8)',
                            color: 'var(--text-color)',
                            fontSize: '0.9rem'
                          }}
                        />
                      </div>
                    </div>
                  )}
                </>
              )}

              {/* Website Tab */}
              {activeInputMode === 'website' && (
                <>
                  <h2 className="section-title"><i className="fas fa-globe"></i> Process Public Website</h2>
                  <p className="section-description">Enter the URL of a public website. Use options below to refine the crawl.</p>

                  {/* URL Input */}
                  <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', marginBottom: '1.5rem' }}>
                    <input type="url" value={websiteUrl} onChange={handleWebsiteUrlChange}
                           placeholder="https://example.com" aria-label="Website URL" disabled={isProcessing}
                           style={{ flexGrow: 1, padding: '0.6rem 0.8rem', borderRadius: '6px', border: '1px solid var(--card-border-color)', background: 'rgba(var(--card-bg-rgb), 0.8)', color: 'var(--text-color)', fontSize: '0.9rem' }}/>
                  </div>

                  {/* Advanced Options Toggle */}
                  <div style={{ marginBottom: '1rem', borderTop: '1px solid var(--card-border-color)', paddingTop: '1rem' }}>
                    <button onClick={() => setShowAdvancedOptions(!showAdvancedOptions)}
                            style={{ background: 'none', border: 'none', color: 'var(--primary-color)', cursor: 'pointer', padding: '0.5rem 0', fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                            aria-expanded={showAdvancedOptions}>
                      <i className={`fas fa-chevron-${showAdvancedOptions ? 'down' : 'right'}`}></i>
                      {showAdvancedOptions ? 'Hide' : 'Show'} Crawl Options
                    </button>
                  </div>

                  {/* Advanced Options Grid */}
                  {showAdvancedOptions && (
                    <div className="crawl-options-grid">
                      {/* Max Depth */}
                      <div className="option-item">
                        <label htmlFor="max-depth">Max Depth</label>
                        <input type="number" id="max-depth" value={crawlMaxDepth} onChange={handleMaxDepthChange}
                               min="0" max="10" step="1" disabled={isProcessing}
                               aria-describedby="max-depth-desc" placeholder={`Default: ${DEFAULT_CRAWL_MAX_DEPTH}`} />
                        <small id="max-depth-desc">0 = starting page only.</small>
                      </div>

                      {/* Max Pages */}
                      <div className="option-item">
                        <label htmlFor="max-pages">Max Pages</label>
                        <input type="number" id="max-pages" value={crawlMaxPages} onChange={handleMaxPagesChange}
                               min="1" max="1000" step="1" disabled={isProcessing}
                               placeholder={`Default: ${DEFAULT_CRAWL_MAX_PAGES}`} />
                      </div>

                      {/* Stay on Domain */}
                      <div className="option-item" style={{ gridColumn: '1 / -1' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          <input type="checkbox" id="stay-on-domain" checked={crawlStayOnDomain}
                                 onChange={handleStayOnDomainChange} disabled={isProcessing} />
                          <label htmlFor="stay-on-domain">Stay on initial domain only</label>
                        </div>
                      </div>

                      {/* Include Patterns */}
                      <div className="option-item" style={{ gridColumn: '1 / -1' }}>
                        <label htmlFor="include-patterns">Include URL Patterns (Optional)</label>
                        <input type="text" id="include-patterns" value={crawlIncludePatterns}
                               onChange={handleIncludePatternsChange} disabled={isProcessing}
                               placeholder="/docs/*, *.html" title="Comma-separated wildcards (*)" />
                      </div>

                      {/* Exclude Patterns */}
                      <div className="option-item" style={{ gridColumn: '1 / -1' }}>
                        <label htmlFor="exclude-patterns">Exclude URL Patterns (Optional)</label>
                        <input type="text" id="exclude-patterns" value={crawlExcludePatterns}
                               onChange={handleExcludePatternsChange} disabled={isProcessing}
                               placeholder="/login/*, */archive/*, *.pdf" title="Comma-separated wildcards (*)" />
                      </div>

                      {/* Keywords */}
                      <div className="option-item" style={{ gridColumn: '1 / -1' }}>
                        <label htmlFor="keywords">Keywords (Optional)</label>
                        <input type="text" id="keywords" value={crawlKeywords}
                               onChange={handleKeywordsChange} disabled={isProcessing}
                               placeholder="pricing, features, api" title="Comma-separated. Prioritizes pages containing these words." />
                        <small>Uses Best-First search if provided.</small>
                      </div>
                    </div>
                  )}

                  {/* Process Button */}
                  <div style={{ textAlign: 'center', marginTop: showAdvancedOptions ? '0' : '1.5rem' }}>
                    <button className={`btn ${(isProcessingWebsite || !websiteUrl.trim()) ? 'btn-disabled' : ''}`}
                            onClick={handleProcessWebsite} disabled={isProcessing || !websiteUrl.trim()}>
                      {isProcessingWebsite ? (
                        <><i className="fas fa-spinner fa-spin"></i> Starting Crawl...</>
                      ) : (
                        <><i className="fas fa-spider"></i> Process Website</>
                      )}
                    </button>
                  </div>
                </>
              )}

              {/* Error Display */}
              {error && (
                <div className="status-card failed" style={{ marginTop: '2rem' }}>
                  <div className="status-label">
                    <i className="fas fa-exclamation-triangle"></i> Error
                  </div>
                  <div className="status-error">{error}</div>
                  <div className="status-actions">
                    <button className="btn" onClick={() => setError(null)}>
                      <i className="fas fa-times"></i> Dismiss
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>
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
                {jobStatus?.status === 'crawling' && <><i className="fas fa-spider fa-spin"></i> Crawling Website...</>}
                {jobStatus?.status === 'processing' && <><i className="fas fa-cog fa-spin"></i> Analyzing Content...</>}
                {jobStatus?.status === 'completed' && (
                  <><i className="fas fa-check-circle" style={{color: 'var(--success-color)'}}/> Processing Complete!</>
                )}
                {jobStatus?.status === 'failed' && (
                  <><i className="fas fa-times-circle" style={{color: 'var(--error-color)'}}/> Processing Failed</>
                )}
                {!jobStatus && <><i className="fas fa-spinner fa-spin"></i> Loading Status...</>}
              </div>

              {/* Progress Bar */}
              {(jobStatus?.status === 'pending' || jobStatus?.status === 'uploading' ||
                jobStatus?.status === 'cloning' || jobStatus?.status === 'crawling' ||
                jobStatus?.status === 'processing') && (
                <div className="progress-container">
                  <div className="progress-bar"></div>
                </div>
              )}

              {/* Error Display */}
              {jobStatus?.status === 'failed' && jobStatus.error && (
                <div className="status-error">{jobStatus.error}</div>
              )}
              {error && !jobStatus?.error && (
                <div className="status-error">{error}</div>
              )}

              {/* Actions */}
              <div className="status-actions">
                {jobStatus?.status === 'completed' && (
                  <button className="btn" onClick={handleDownload}>
                    <i className="fas fa-download"></i> Download Result
                  </button>
                )}
                {(jobStatus?.status === 'completed' || jobStatus?.status === 'failed' || error) && (
                  <button className="btn" onClick={handleReset} style={{ background: 'var(--card-border-color)', color: 'var(--text-muted)' }}>
                    <i className="fas fa-redo-alt"></i> Start New Job
                  </button>
                )}
                {jobStatus?.status === 'completed' && (
                  <>
                    <div className="llm-buttons-container" style={{ marginTop: '1rem', display: 'flex', flexWrap: 'wrap', gap: '0.5rem', justifyContent: 'center' }}>
                      <button className="btn btn-secondary" onClick={() => handleOpenLLM('https://chat.openai.com')}>
                        <i className="fas fa-comment"></i> Open in ChatGPT
                      </button>
                      <button className="btn btn-secondary" onClick={() => handleOpenLLM('https://gemini.google.com')}>
                        <i className="fas fa-robot"></i> Open in Gemini
                      </button>
                      <button className="btn btn-secondary" onClick={() => handleOpenLLM('https://www.quicke.in')}>
                        <i className="fas fa-rocket"></i> Open in Quicke
                      </button>
                      <button className="btn btn-secondary" onClick={() => handleOpenLLM('https://claude.ai')}>
                        <i className="fas fa-brain"></i> Open in Claude
                      </button>
                      <button className="btn btn-secondary" onClick={() => handleOpenLLM('https://grok.com')}>
                        <i className="fas fa-bolt"></i> Open in Grok
                      </button>
                    </div>
                    <div style={{ marginTop: '0.5rem', fontSize: '0.9rem', color: 'var(--text-muted)', textAlign: 'center' }}>
                      <i className="fas fa-info-circle"></i> Download the file first, then upload it to your preferred LLM interface
                    </div>
                  </>
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