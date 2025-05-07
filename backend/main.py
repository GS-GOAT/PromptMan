# backend/main.py
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl, Field
import os
import shutil
import time
from typing import List, Optional
import uuid
import asyncio
import logging
import redis
import json
import re

# Import the services
from services.code_service import run_code2prompt
from services.website_service import run_crawl4ai  # Add website service import

# --- Configuration ---
TEMP_DIR = "temp"
RESULTS_DIR = "results"
TEMP_CLONES_DIR = "temp_clones"
CLEANUP_AGE_SECONDS = 10 * 60  # 10 minutes
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
JOB_EXPIRY_SECONDS = CLEANUP_AGE_SECONDS + 300

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- FastAPI App Setup ---
app = FastAPI(title="PromptMan API")

# --- Redis Connection ---
redis_client = None
try:
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
    redis_client.ping()
    logger.info(f"Successfully connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
except redis.exceptions.ConnectionError as e:
    logger.error(f"Failed to connect to Redis at {REDIS_HOST}:{REDIS_PORT} - {e}")
    redis_client = None
except Exception as e:
    logger.error(f"Failed to initialize Redis client - {e}")
    redis_client = None

# --- CORS Setup ---
allowed_origins_str = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
ALLOWED_ORIGINS = [origin.strip() for origin in allowed_origins_str.split(',') if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Directory Creation ---
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(TEMP_CLONES_DIR, exist_ok=True)

# --- Job Management Functions ---
def create_job(job_type: str):
    """Creates a new job, storing its type."""
    if not redis_client:
        raise HTTPException(status_code=503, detail="Job storage unavailable (Redis connection failed)")
    job_id = str(uuid.uuid4())
    job_data = {
        "status": "pending",
        "created_at": time.time(),
        "updated_at": time.time(),
        "error": None,
        "result_file": None,
        "type": job_type  # Store job type
    }
    try:
        redis_client.set(f"job:{job_id}", json.dumps(job_data), ex=JOB_EXPIRY_SECONDS)
        logger.info(f"Job created in Redis: {job_id} (Type: {job_type})")
    except redis.exceptions.RedisError as e:
        logger.error(f"Redis error creating job {job_id}: {e}")
        raise HTTPException(status_code=503, detail="Job storage error during creation")
    return job_id

def update_job_status(job_id, status, error=None, result_file=None):
    if not redis_client:
        logger.error(f"Cannot update job {job_id}: Redis client unavailable.")
        return
    job_key = f"job:{job_id}"
    try:
        job_data_str = redis_client.get(job_key)
        if not job_data_str:
            logger.warning(f"Attempted to update status for non-existent/expired job in Redis: {job_id}")
            return

        job_data = json.loads(job_data_str)
        job_data["status"] = status
        job_data["updated_at"] = time.time()
        job_data["error"] = str(error) if error else None
        job_data["result_file"] = result_file

        ttl = redis_client.ttl(job_key)
        expiry = ttl if ttl > 0 else JOB_EXPIRY_SECONDS
        redis_client.set(job_key, json.dumps(job_data), ex=expiry)
        
        logger.info(f"Job {job_id} status updated to {status} in Redis")
        if error:
            logger.error(f"Job {job_id} failed with error: {error}")
    except Exception as e:
        logger.exception(f"Error updating job {job_id} status: {e}")

def get_job_status(job_id):
    if not redis_client:
        logger.error("Cannot get job status: Redis client unavailable.")
        return None
    job_data_str = redis_client.get(f"job:{job_id}")
    if job_data_str:
        try:
            return json.loads(job_data_str)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON found in Redis for job {job_id}")
            return None
    return None

# --- Cleanup Logic ---
def cleanup_old_files(directory: str, max_age_seconds: int):
    if not os.path.isdir(directory):
        return
    current_time = time.time()
    for item_name in os.listdir(directory):
        item_path = os.path.join(directory, item_name)
        try:
            item_age = current_time - os.path.getmtime(item_path)
            if item_age > max_age_seconds:
                if os.path.isfile(item_path):
                    os.remove(item_path)
                    logger.info(f"Cleaned up old file: {item_path}")
                elif os.path.isdir(item_path):
                    if item_path != directory:
                        shutil.rmtree(item_path)
                        logger.info(f"Cleaned up old directory: {item_path}")
        except Exception as e:
            logger.warning(f"Error during cleanup of {item_path}: {e}")

@app.middleware("http")
async def cleanup_middleware(request: Request, call_next):
    cleanup_old_files(TEMP_DIR, CLEANUP_AGE_SECONDS)
    cleanup_old_files(RESULTS_DIR, CLEANUP_AGE_SECONDS)
    cleanup_old_files(TEMP_CLONES_DIR, CLEANUP_AGE_SECONDS)
    response = await call_next(request)
    return response

# --- Repository Processing ---
class RepoRequest(BaseModel):
    repo_url: str

# --- MODIFIED: WebsiteRequest Model ---
class WebsiteRequest(BaseModel):
    website_url: HttpUrl
    max_depth: Optional[int] = Field(None, ge=0, le=10, description="Max crawl depth (0=start page only)")
    max_pages: Optional[int] = Field(None, ge=1, le=1000, description="Max total pages to crawl")
    stay_on_domain: Optional[bool] = Field(None, description="Restrict crawl to initial domain")
    include_patterns: Optional[str] = Field(None, description="Comma-separated URL wildcard patterns to include")
    exclude_patterns: Optional[str] = Field(None, description="Comma-separated URL wildcard patterns to exclude")
    keywords: Optional[str] = Field(None, description="Comma-separated keywords to prioritize relevant pages")

async def process_repository_job(job_id: str, repo_url: str):
    """Clones a repository (creating repo-named subdir) and handles code processing."""
    # Define the base directory for this job's clone operation
    job_clone_base_dir = os.path.join(TEMP_CLONES_DIR, job_id)
    result_file_path = os.path.join(RESULTS_DIR, f"{job_id}.md")
    # We expect the actual code path to be detected later
    input_path_for_service = None # Will be determined after clone

    try:
        # Create the unique base directory for this job
        os.makedirs(job_clone_base_dir, exist_ok=True)
        logger.info(f"[Repo Job {job_id}] Starting cloning: {repo_url} into base dir {job_clone_base_dir}")
        update_job_status(job_id, "cloning")

        # Let git create the repo-named subdirectory
        cmd = ['git', 'clone', '--depth', '1', repo_url]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=job_clone_base_dir # Run git in the base directory
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300.0)
        except asyncio.TimeoutError:
            logger.error(f"[Repo Job {job_id}] Git clone timed out after 300 seconds.")
            update_job_status(job_id, "failed", error="Repository cloning timed out")
            try: process.kill()
            except ProcessLookupError: pass
            return

        if process.returncode != 0:
            error_output = stderr.decode().strip() if stderr else "Unknown clone error"
            logger.error(f"[Repo Job {job_id}] Git clone failed: {error_output}")
            update_job_status(job_id, "failed", error=f"Failed to clone repository: {error_output[:200]}")
            return

        logger.info(f"[Repo Job {job_id}] Cloning successful.")

        # Determine effective input directory
        items_in_base_dir = os.listdir(job_clone_base_dir)
        if len(items_in_base_dir) == 1:
            # Expecting exactly one item: the directory named after the repo
            repo_subdir_name = items_in_base_dir[0]
            potential_project_dir = os.path.join(job_clone_base_dir, repo_subdir_name)
            if os.path.isdir(potential_project_dir):
                input_path_for_service = potential_project_dir
                logger.info(f"[Repo Job {job_id}] Detected repository subdirectory '{repo_subdir_name}', using it.")
            else:
                logger.error(f"[Repo Job {job_id}] Cloned successfully, but single item '{repo_subdir_name}' is not a directory?")
                raise FileNotFoundError("Cloned item is not a directory.")
        elif len(items_in_base_dir) == 0:
            logger.error(f"[Repo Job {job_id}] Clone directory {job_clone_base_dir} is empty after successful clone command?")
            raise FileNotFoundError("Cloned directory appears empty.")
        else:
            # Handle unusual cases with multiple items
            logger.warning(f"[Repo Job {job_id}] Multiple items found in clone base directory ({items_in_base_dir}). Attempting to find repo root or using base.")
            # Attempt heuristic: find the dir containing .git
            found_repo_dir = None
            for item in items_in_base_dir:
                potential_dir = os.path.join(job_clone_base_dir, item)
                if os.path.isdir(potential_dir) and os.path.exists(os.path.join(potential_dir, '.git')):
                    found_repo_dir = potential_dir
                    logger.info(f"[Repo Job {job_id}] Found likely repo dir: '{item}'")
                    break
            if found_repo_dir:
                input_path_for_service = found_repo_dir
            else:
                logger.warning(f"[Repo Job {job_id}] Could not definitively identify repo root among multiple items. Using base directory {job_clone_base_dir} - This might be incorrect!")
                input_path_for_service = job_clone_base_dir

        # Proceed with processing
        update_job_status(job_id, "processing")
        logger.info(f"[Repo Job {job_id}] Starting analysis on path: {input_path_for_service}")
        result_content = await run_code2prompt(input_path_for_service)
        logger.info(f"[Repo Job {job_id}] Analysis finished. Output length: {len(result_content)}")

        if result_content.startswith(("# Error:", "# Warning:")):
            first_line = result_content.split('\n', 1)[0]
            logger.warning(f"[Repo Job {job_id}] code2prompt reported: {first_line}")
            if result_content.startswith("# Error:"):
                update_job_status(job_id, "failed", error=f"Code analysis failed: {first_line}")
                return

        os.makedirs(RESULTS_DIR, exist_ok=True)
        with open(result_file_path, "w", encoding="utf-8") as f:
            f.write(result_content)
        logger.info(f"[Repo Job {job_id}] Output saved to {result_file_path}")
        update_job_status(job_id, "completed", result_file=result_file_path)

    except FileNotFoundError as e:
        logger.error(f"[Repo Job {job_id}] File/Directory error during processing: {e}")
        update_job_status(job_id, "failed", error=str(e))
    except Exception as e:
        logger.exception(f"[Repo Job {job_id}] Unexpected error during repo processing: {e}")
        update_job_status(job_id, "failed", error=f"Unexpected error: {type(e).__name__}")
    finally:
        # Cleanup uses the base directory for the job
        logger.info(f"[Repo Job {job_id}] Cleaning up base clone directory {job_clone_base_dir}")
        shutil.rmtree(job_clone_base_dir, ignore_errors=True)

# --- MODIFIED: process_website_job ---
async def process_website_job(job_id: str, website_url: str,
                            max_depth: Optional[int] = None,
                            max_pages: Optional[int] = None,
                            stay_on_domain: Optional[bool] = None,
                            include_patterns: Optional[str] = None,
                            exclude_patterns: Optional[str] = None,
                            keywords: Optional[str] = None):
    """Crawls a website using crawl4ai with advanced options and saves the result."""
    # Use .md extension for website results
    result_file_path = os.path.join(RESULTS_DIR, f"{job_id}.md")

    try:
        logger.info(f"[Website Job {job_id}] Starting enhanced crawl for: {website_url}")
        update_job_status(job_id, "crawling")

        # Run the crawl4ai service with all options
        result_content = await run_crawl4ai(
            url=website_url,
            max_depth=max_depth,
            max_pages=max_pages,
            stay_on_domain=stay_on_domain,
            include_patterns_str=include_patterns,
            exclude_patterns_str=exclude_patterns,
            keywords_str=keywords
        )
        logger.info(f"[Website Job {job_id}] crawl4ai service finished.")

        # Check result
        if result_content.startswith(("# Error:", "# Warning:")):
            first_line = result_content.split('\n', 1)[0]
            logger.warning(f"[Website Job {job_id}] crawl4ai service reported: {first_line}")
            if result_content.startswith("# Error:"):
                update_job_status(job_id, "failed", error=result_content)
                return

        # Save result
        os.makedirs(RESULTS_DIR, exist_ok=True)
        with open(result_file_path, "w", encoding="utf-8") as f:
            f.write(result_content)
        logger.info(f"[Website Job {job_id}] Output saved to {result_file_path}")
        update_job_status(job_id, "completed", result_file=result_file_path)

    except Exception as e:
        logger.exception(f"[Website Job {job_id}] Unexpected error in background task: {e}")
        update_job_status(job_id, "failed", error=f"Unexpected backend task error: {type(e).__name__}")

# --- File Upload Background Task ---
async def process_upload(temp_dir: str, job_id: str):
    """Handles code processing for direct file uploads."""
    result_file_path = os.path.join(RESULTS_DIR, f"{job_id}.md")
    input_path_for_service = temp_dir

    try:
        if not os.path.isdir(temp_dir):
            logger.error(f"[Upload Job {job_id}] Initial upload directory {temp_dir} not found.")
            raise FileNotFoundError(f"Upload directory {temp_dir} missing.")

        items_in_temp = os.listdir(temp_dir)
        if len(items_in_temp) == 1:
            potential_project_dir_path = os.path.join(temp_dir, items_in_temp[0])
            if os.path.isdir(potential_project_dir_path):
                input_path_for_service = potential_project_dir_path
                logger.info(f"[Upload Job {job_id}] Using upload subdirectory: {items_in_temp[0]}")
        elif len(items_in_temp) == 0:
            logger.warning(f"[Upload Job {job_id}] Upload directory {temp_dir} is empty.")
            raise FileNotFoundError("No files found in upload directory.")

        update_job_status(job_id, "processing")
        result_content = await run_code2prompt(input_path_for_service)

        if result_content.startswith(("# Error:", "# Warning:")):
            first_line = result_content.split('\n', 1)[0]
            logger.warning(f"[Upload Job {job_id}] code2prompt reported: {first_line}")
            if result_content.startswith("# Error:"):
                update_job_status(job_id, "failed", error=f"Code analysis failed: {first_line}")
                return
            # Continue with warnings

        os.makedirs(RESULTS_DIR, exist_ok=True)
        with open(result_file_path, "w", encoding="utf-8") as f:
            f.write(result_content)
        logger.info(f"[Upload Job {job_id}] Output saved to {result_file_path}")
        update_job_status(job_id, "completed", result_file=result_file_path)

    except FileNotFoundError as e:
        logger.error(f"[Upload Job {job_id}] File/Directory error: {e}")
        update_job_status(job_id, "failed", error=str(e))
    except Exception as e:
        logger.exception(f"[Upload Job {job_id}] Unexpected error: {e}")
        update_job_status(job_id, "failed", error=f"Unexpected error: {type(e).__name__}")
    finally:
        logger.info(f"[Upload Job {job_id}] Cleaning up upload directory {temp_dir}")
        shutil.rmtree(temp_dir, ignore_errors=True)

# --- API Endpoints ---
@app.post("/api/process-repo")
async def process_repo(repo_request: RepoRequest, background_tasks: BackgroundTasks):
    """Accepts a Git repository URL and starts background processing."""
    repo_url = repo_request.repo_url.strip()
    if not re.match(r'^https?://[^\s/$.?#].[^\s]*$', repo_url):
        raise HTTPException(status_code=400, detail="Invalid repository URL format.")
    job_id = create_job(job_type="repo")  # Changed from "repository" to "repo"
    background_tasks.add_task(process_repository_job, job_id, repo_url)
    logger.info(f"Job {job_id}: Background repository processing scheduled for {repo_url}")
    return {"job_id": job_id}

@app.post("/api/process-website")
async def process_website(website_request: WebsiteRequest, background_tasks: BackgroundTasks):
    """Accepts a website URL and crawl options, validates them, and starts background crawling."""
    website_url = str(website_request.website_url)
    job_id = create_job(job_type="website")  # Explicit job_type parameter
    background_tasks.add_task(
        process_website_job,
        job_id=job_id,
        website_url=website_url,
        max_depth=website_request.max_depth,
        max_pages=website_request.max_pages,
        stay_on_domain=website_request.stay_on_domain,
        include_patterns=website_request.include_patterns,
        exclude_patterns=website_request.exclude_patterns,
        keywords=website_request.keywords
    )
    logger.info(f"Job {job_id}: Background website processing scheduled for {website_url}")
    return {"job_id": job_id}

@app.post("/api/upload-codebase")
async def upload_codebase(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
    """Accepts folder uploads, saves files, and starts background processing."""
    job_id = create_job(job_type="upload")  # Explicit job_type parameter
    upload_dir = os.path.join(TEMP_DIR, job_id)
    os.makedirs(upload_dir, exist_ok=True)

    file_count = 0
    total_size = 0
    try:
        update_job_status(job_id, "uploading")
        logger.info(f"Receiving upload for job {job_id}")

        for file in files:
            relative_path = file.filename
            if not relative_path:
                logger.warning(f"Job {job_id}: Skipping file with empty filename.")
                continue

            clean_relative_path = os.path.normpath(relative_path).lstrip('/\\.')
            if clean_relative_path != relative_path or "/../" in relative_path or "\\..\\" in relative_path:
                logger.error(f"Job {job_id}: Potentially unsafe path detected, skipping file: {relative_path}")
                continue

            full_path = os.path.join(upload_dir, clean_relative_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            try:
                with open(full_path, "wb") as f:
                    while content := await file.read(1024 * 1024):
                        f.write(content)
                        total_size += len(content)
                file_count += 1
            except Exception as write_error:
                logger.error(f"Job {job_id}: Failed to write file {relative_path}: {write_error}")
                continue

        if file_count == 0:
            logger.warning(f"Job {job_id}: No valid files were uploaded.")
            update_job_status(job_id, "failed", error="No valid files uploaded.")
            shutil.rmtree(upload_dir, ignore_errors=True)
            return {"job_id": job_id}

        logger.info(f"Job {job_id}: Received {file_count} files, total size {total_size} bytes.")
        background_tasks.add_task(process_upload, upload_dir, job_id)
        return {"job_id": job_id}

    except Exception as e:
        logger.exception(f"Critical error during file upload for job {job_id}: {e}")
        update_job_status(job_id, "failed", error=f"Critical upload error: {type(e).__name__}")
        if os.path.isdir(upload_dir):
            shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="File upload failed critically.") from e

@app.get("/api/job-status/{job_id}")
async def job_status(job_id: str):
    """Returns the current status of a background job."""
    status_info = get_job_status(job_id)
    if status_info is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return {
        "job_id": job_id,
        "status": status_info.get("status", "unknown"),
        "error": status_info.get("error")
    }

@app.get("/api/download/{job_id}")
async def download_file(job_id: str):
    """Allows downloading the result file for a completed job."""
    status_info = get_job_status(job_id)
    if not status_info:
        raise HTTPException(status_code=404, detail="Job not found or expired.")

    job_current_status = status_info.get("status")
    
    if job_current_status == "failed":
        error_message = status_info.get('error', 'Unknown processing error')
        if error_message.startswith("# Error:"):
            error_message = error_message.split('\n', 1)[0]
        raise HTTPException(status_code=400, detail=f"Job failed: {error_message[:200]}")

    if job_current_status != "completed":
        raise HTTPException(status_code=400,
                          detail=f"Job not completed. Current status: {job_current_status or 'unknown'}")

    file_path = status_info.get("result_file")
    if not file_path:
        logger.error(f"Job {job_id} is 'completed' but result_file path is missing in Redis data.")
        raise HTTPException(status_code=500, detail="Internal error: Result file path missing for completed job.")

    if not os.path.exists(file_path):
        logger.error(f"Result file not found at path stored in Redis: {file_path} for job {job_id}")
        job_updated_time = status_info.get("updated_at", 0)
        if time.time() - job_updated_time > CLEANUP_AGE_SECONDS:
            raise HTTPException(status_code=404, detail="Result file not found (likely cleaned up due to age).")
        else:
            raise HTTPException(status_code=404, detail="Result file not found on server (unexpectedly missing).")

    # Determine filename and media type based on extension
    _, extension = os.path.splitext(file_path)
    extension = extension.lower()

    if extension == ".md":
        filename = f"promptman_result_{job_id}.md"
        media_type = "text/markdown"
    else:
        logger.warning(f"Unexpected file extension '{extension}' for job {job_id}. Serving as octet-stream.")
        filename = f"promptman_result_{job_id}{extension}"
        media_type = "application/octet-stream"

    return FileResponse(file_path, filename=filename, media_type=media_type)

@app.get("/")
async def root():
    """Simple health check endpoint"""
    return {"message": "PromptMan Backend is running."}