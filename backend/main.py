# backend/main.py
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, BackgroundTasks, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl, Field
import os
import shutil
import time
from typing import List, Optional
import uuid as app_uuid
import asyncio
import logging
import redis
import json
import re
import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from services.code_service import run_code2prompt
from services.website_service import run_crawl4ai
from filter_patterns import get_default_exclude_patterns

# Analytics DB 
from analytics_db import (
    init_analytics_db, get_analytics_session_context, get_analytics_session_dependency, analytics_engine,
    UploadJobAnalytics, RepoJobAnalytics, WebsiteJobAnalytics
)

# Config 
TEMP_DIR = "temp"
RESULTS_DIR = "results"
TEMP_CLONES_DIR = "temp_clones"
CLEANUP_AGE_SECONDS = 10 * 60  # 10 minutes
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
JOB_EXPIRY_SECONDS = CLEANUP_AGE_SECONDS + 300

# Logging Setup 
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# FastAPI App 
app = FastAPI(title="PromptMan API")

# Redis Connection 
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

# CORS 
allowed_origins_str = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
ALLOWED_ORIGINS = [origin.strip() for origin in allowed_origins_str.split(',') if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Temp Directory Creation for strorage of Results 
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(TEMP_CLONES_DIR, exist_ok=True)

# Job Management Functions 
def create_job(job_type: str):
    """Creates a new job, storing its type."""
    if not redis_client:
        raise HTTPException(status_code=503, detail="Job storage unavailable (Redis connection failed)")
    job_id = str(app_uuid.uuid4())
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

# Cleanup Logic 
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

# Repository Processing 
class RepoRequest(BaseModel):
    repo_url: str
    include_patterns: Optional[str] = None
    exclude_patterns: Optional[str] = None

# WebsiteRequest Model 
class WebsiteRequest(BaseModel):
    website_url: HttpUrl
    max_depth: Optional[int] = Field(None, ge=0, le=10, description="Max crawl depth (0=start page only)")
    max_pages: Optional[int] = Field(None, ge=1, le=1000, description="Max total pages to crawl")
    stay_on_domain: Optional[bool] = Field(None, description="Restrict crawl to initial domain")
    include_patterns: Optional[str] = Field(None, description="Comma-separated URL wildcard patterns to include")
    exclude_patterns: Optional[str] = Field(None, description="Comma-separated URL wildcard patterns to exclude")
    keywords: Optional[str] = Field(None, description="Comma-separated keywords to prioritize relevant pages")

@app.on_event("startup")
async def on_startup():
    if analytics_engine:
        await init_analytics_db()
    else:
        logger.warning("Analytics database URL not configured or engine creation failed. Analytics features will be disabled.")
    
    global redis_client
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

# Helper function for directory size calculation
def get_dir_size(path='.'):
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat(follow_symlinks=False).st_size
            elif entry.is_dir(follow_symlinks=False):
                try:
                    total += get_dir_size(entry.path)
                except OSError:
                    logger.warning(f"Could not access {entry.path} to calculate size.")
    except FileNotFoundError:
        logger.warning(f"Path not found during size calculation: {path}")
    except PermissionError:
        logger.warning(f"Permission denied for path: {path}")
    return total

async def process_repository_job(job_id_str: str, repo_url: str, include_patterns: Optional[str] = None, exclude_patterns: Optional[str] = None):
    job_uuid_for_analytics = app_uuid.UUID(job_id_str)
    job_clone_base_dir = os.path.join(TEMP_CLONES_DIR, job_id_str)
    result_file_path_on_disk = os.path.join(RESULTS_DIR, f"{job_id_str}.md")
    
    # Get default exclude patterns and combine with user-provided patterns
    default_exclude_patterns = get_default_exclude_patterns()
    combined_exclude_patterns = default_exclude_patterns
    if exclude_patterns:
        combined_exclude_patterns = f"{default_exclude_patterns},{exclude_patterns}"
    
    overall_task_start_time = time.perf_counter()
    git_clone_duration: Optional[float] = None
    code_analysis_duration: Optional[float] = None
    cloned_repo_name_capture: Optional[str] = None
    cloned_repo_size_capture: Optional[int] = None
    clone_success_flag = False
    output_file_size_capture: Optional[int] = None
    final_status_for_analytics = "failed"
    error_msg_for_analytics: Optional[str] = None
    error_type_for_analytics: Optional[str] = None
    input_path_for_service: Optional[str] = None

    try:
        os.makedirs(job_clone_base_dir, exist_ok=True)
        update_job_status(job_id_str, "cloning")

        # Extract repo name from URL
        repo_name = repo_url.split('/')[-1].replace('.git', '')
        cloned_repo_name_capture = repo_name
        repo_clone_dir = os.path.join(job_clone_base_dir, repo_name)

        t_clone_start = time.perf_counter()
        cmd = ['git', 'clone', '--depth', '1', repo_url, repo_name]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=job_clone_base_dir
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300.0)
        except asyncio.TimeoutError:
            logger.error(f"[Repo Job {job_id_str}] Git clone timed out.")
            update_job_status(job_id_str, "failed", error="Repository cloning timed out")
            error_msg_for_analytics = "Repository cloning timed out"
            error_type_for_analytics = "TimeoutError"
            raise

        t_clone_end = time.perf_counter()
        git_clone_duration = t_clone_end - t_clone_start

        if process.returncode != 0:
            error_output = stderr.decode().strip() if stderr else "Unknown clone error"
            logger.error(f"[Repo Job {job_id_str}] Git clone failed: {error_output}")
            update_job_status(job_id_str, "failed", error=f"Failed to clone repository: {error_output[:200]}")
            error_msg_for_analytics = f"Failed to clone repository: {error_output[:200]}"
            error_type_for_analytics = "CloneError"
            raise Exception(error_msg_for_analytics)

        clone_success_flag = True
        logger.info(f"[Repo Job {job_id_str}] Cloning successful.")
        cloned_repo_size_capture = get_dir_size(repo_clone_dir)
        input_path_for_service = repo_clone_dir

        update_job_status(job_id_str, "processing")
        logger.info(f"[Repo Job {job_id_str}] Starting analysis on path: {input_path_for_service}")
        
        t_analysis_start = time.perf_counter()
        result_content = await run_code2prompt(
            input_path_for_service,
            include_patterns=include_patterns,
            exclude_patterns=combined_exclude_patterns
        )
        t_analysis_end = time.perf_counter()
        code_analysis_duration = t_analysis_end - t_analysis_start
        logger.info(f"[Repo Job {job_id_str}] Analysis finished. Output length: {len(result_content)}")

        if result_content.startswith(("# Error:", "# Warning:")):
            first_line = result_content.split('\n', 1)[0]
            logger.warning(f"[Repo Job {job_id_str}] code2prompt reported: {first_line}")
            if result_content.startswith("# Error:"):
                update_job_status(job_id_str, "failed", error=f"Code analysis failed: {first_line}")
                error_msg_for_analytics = f"Code analysis failed: {first_line}"
                error_type_for_analytics = "Code2PromptError"
                raise Exception(error_msg_for_analytics)

        os.makedirs(RESULTS_DIR, exist_ok=True)
        with open(result_file_path_on_disk, "w", encoding="utf-8") as f:
            f.write(result_content)
        output_file_size_capture = os.path.getsize(result_file_path_on_disk)
        final_status_for_analytics = "completed"
        update_job_status(job_id_str, "completed", result_file=result_file_path_on_disk)
        logger.info(f"[Repo Job {job_id_str}] Output saved to {result_file_path_on_disk}")

    except Exception as e:
        logger.exception(f"[Repo Job {job_id_str}] Error during processing: {e}")
        if not error_msg_for_analytics:
            error_msg_for_analytics = str(e)[:500]
        if not error_type_for_analytics:
            error_type_for_analytics = type(e).__name__
        update_job_status(job_id_str, "failed", error=error_msg_for_analytics)
    finally:
        overall_task_end_time = time.perf_counter()
        total_task_duration = overall_task_end_time - overall_task_start_time
        job_end_timestamp = datetime.datetime.utcnow()

        if not analytics_engine:
            logger.warning(f"Analytics engine not available for final update of repo job {job_uuid_for_analytics}. Skipping.")
        else:
            async with get_analytics_session_context() as analytics_session:
                if analytics_session:
                    stmt = select(RepoJobAnalytics).where(RepoJobAnalytics.job_uuid == job_uuid_for_analytics)
                    result_proxy = await analytics_session.execute(stmt)
                    record_to_update = result_proxy.scalar_one_or_none()
                    
                    if record_to_update:
                        record_to_update.job_end_time = job_end_timestamp
                        record_to_update.final_status = final_status_for_analytics
                        record_to_update.error_message = error_msg_for_analytics
                        record_to_update.error_type = error_type_for_analytics
                        record_to_update.output_size_bytes = output_file_size_capture
                        record_to_update.total_processing_duration_seconds = total_task_duration
                        
                        record_to_update.cloned_repo_name = cloned_repo_name_capture
                        record_to_update.clone_successful = clone_success_flag
                        record_to_update.cloned_repo_size_bytes = cloned_repo_size_capture
                        record_to_update.git_clone_duration_seconds = git_clone_duration
                        record_to_update.code_analysis_duration_seconds = code_analysis_duration
                        
                        analytics_session.add(record_to_update)
                        try:
                            await analytics_session.commit()
                            logger.info(f"Final analytics updated for repo job {job_uuid_for_analytics}")
                        except Exception as e_final_analytics:
                            logger.error(f"Analytics DB error on final repo job log for {job_uuid_for_analytics}: {e_final_analytics}")
                            await analytics_session.rollback()
                    else:
                        logger.error(f"Analytics record for repo job {job_uuid_for_analytics} not found for final update.")
                else:
                    logger.warning(f"Failed to get analytics session for final update of repo job {job_uuid_for_analytics}. Skipping.")
        
        if os.path.isdir(job_clone_base_dir):
            shutil.rmtree(job_clone_base_dir, ignore_errors=True)

# process_website_job 
async def process_website_job(
    job_id_str: str,
    website_url: str,
    max_depth: Optional[int],
    max_pages: Optional[int],
    stay_on_domain: Optional[bool],
    include_patterns: Optional[str],
    exclude_patterns: Optional[str],
    keywords: Optional[str]
):
    job_uuid_for_analytics = app_uuid.UUID(job_id_str)
    result_file_path_on_disk = os.path.join(RESULTS_DIR, f"{job_id_str}.md")

    overall_task_start_time = time.perf_counter()
    website_crawl_duration: Optional[float] = None
    pages_crawled_capture: Optional[int] = 0
    output_file_size_capture: Optional[int] = None
    final_status_for_analytics = "failed"
    error_msg_for_analytics: Optional[str] = None
    error_type_for_analytics: Optional[str] = None

    try:
        update_job_status(job_id_str, "crawling")
        logger.info(f"[Website Job {job_id_str}] Status set to crawling. Starting crawl for: {website_url}")

        t_crawl_start = time.perf_counter()
        crawl_result_data = await run_crawl4ai(
            url=website_url,
            max_depth=max_depth,
            max_pages=max_pages,
            stay_on_domain=stay_on_domain,
            include_patterns_str=include_patterns,
            exclude_patterns_str=exclude_patterns,
            keywords_str=keywords
        )
        t_crawl_end = time.perf_counter()
        website_crawl_duration = t_crawl_end - t_crawl_start

        result_content = crawl_result_data.get("markdown_content", "")
        pages_crawled_capture = crawl_result_data.get("pages_processed", 0)
        logger.info(f"[Website Job {job_id_str}] crawl4ai service finished. Pages processed: {pages_crawled_capture}")

        if result_content.startswith(("# Error:", "# Warning:")):
            first_line = result_content.split('\n', 1)[0]
            logger.warning(f"[Website Job {job_id_str}] crawl4ai service reported: {first_line}")
            if result_content.startswith("# Error:"):
                error_msg_for_analytics = first_line
                error_type_for_analytics = "CrawlError"
                update_job_status(job_id_str, "failed", error=error_msg_for_analytics)
        else:
            os.makedirs(RESULTS_DIR, exist_ok=True)
            with open(result_file_path_on_disk, "w", encoding="utf-8") as f:
                f.write(result_content)
            output_file_size_capture = os.path.getsize(result_file_path_on_disk)
            final_status_for_analytics = "completed"
            update_job_status(job_id_str, "completed", result_file=result_file_path_on_disk)
            logger.info(f"[Website Job {job_id_str}] Output saved to {result_file_path_on_disk}")

    except Exception as e:
        logger.exception(f"[Website Job {job_id_str}] Error during processing: {e}")
        final_status_for_analytics = "failed"
        if not error_msg_for_analytics: error_msg_for_analytics = str(e)[:500]
        if not error_type_for_analytics: error_type_for_analytics = type(e).__name__
        update_job_status(job_id_str, "failed", error=error_msg_for_analytics)
    finally:
        overall_task_end_time = time.perf_counter()
        total_task_duration = overall_task_end_time - overall_task_start_time
        job_end_timestamp = datetime.datetime.utcnow()

        if not analytics_engine:
            logger.warning(f"Analytics engine not available for final update of website job {job_uuid_for_analytics}. Skipping.")
        else:
            async with get_analytics_session_context() as analytics_session:
                if analytics_session:
                    stmt = select(WebsiteJobAnalytics).where(WebsiteJobAnalytics.job_uuid == job_uuid_for_analytics)
                    result_proxy = await analytics_session.execute(stmt)
                    record_to_update = result_proxy.scalar_one_or_none()

                    if record_to_update:
                        record_to_update.job_end_time = job_end_timestamp
                        record_to_update.final_status = final_status_for_analytics
                        record_to_update.error_message = error_msg_for_analytics
                        record_to_update.error_type = error_type_for_analytics
                        record_to_update.output_size_bytes = output_file_size_capture
                        record_to_update.total_processing_duration_seconds = total_task_duration
                        record_to_update.pages_actually_crawled_count = pages_crawled_capture
                        record_to_update.website_crawl_duration_seconds = website_crawl_duration
                        
                        analytics_session.add(record_to_update)
                        try:
                            await analytics_session.commit()
                            logger.info(f"Final analytics updated for website job {job_uuid_for_analytics}")
                        except Exception as e_final_analytics:
                            logger.error(f"Analytics DB error on final website job log for {job_uuid_for_analytics}: {e_final_analytics}")
                            await analytics_session.rollback()
                    else:
                        logger.error(f"Analytics record for website job {job_uuid_for_analytics} not found for final update. If analytics are working, this might be an old log path.")
                else:
                    logger.warning(f"Failed to get analytics session for final update of website job {job_uuid_for_analytics}. Skipping.")

# File Upload Background Task 
async def process_upload(
    job_id_str: str,
    upload_dir_path: str,
    filtered_files_count_from_endpoint: int,
    upload_size_bytes_from_endpoint: int
):
    job_uuid_for_analytics = app_uuid.UUID(job_id_str)
    result_file_path_on_disk = os.path.join(RESULTS_DIR, f"{job_id_str}.md")
    
    overall_task_start_time = time.perf_counter()
    code_analysis_duration: Optional[float] = None
    output_file_size_capture: Optional[int] = None
    final_status_for_analytics = "failed"
    error_msg_for_analytics: Optional[str] = None
    error_type_for_analytics: Optional[str] = None
    input_path_for_service = upload_dir_path

    try:
        update_job_status(job_id_str, "processing")

        items_in_temp = os.listdir(upload_dir_path)
        if len(items_in_temp) == 1 and os.path.isdir(os.path.join(upload_dir_path, items_in_temp[0])):
            input_path_for_service = os.path.join(upload_dir_path, items_in_temp[0])
            logger.info(f"[Upload Job {job_id_str}] Using upload subdirectory: {items_in_temp[0]}")
        elif not items_in_temp and os.path.isdir(upload_dir_path):
            input_path_for_service = upload_dir_path
        elif not items_in_temp:
            logger.warning(f"[Upload Job {job_id_str}] Upload directory {upload_dir_path} appears empty.")
            error_msg_for_analytics = "Upload directory empty or files not found."
            error_type_for_analytics = "FileUploadError"
            raise FileNotFoundError(error_msg_for_analytics)

        logger.info(f"[Upload Job {job_id_str}] Starting analysis on path: {input_path_for_service}")
        t_analysis_start = time.perf_counter()
        result_content = await run_code2prompt(input_path_for_service)
        t_analysis_end = time.perf_counter()
        code_analysis_duration = t_analysis_end - t_analysis_start
        
        if result_content.startswith(("# Error:", "# Warning:")):
            first_line = result_content.split('\n', 1)[0]
            logger.warning(f"[Upload Job {job_id_str}] code2prompt reported: {first_line}")
            if result_content.startswith("# Error:"):
                update_job_status(job_id_str, "failed", error=f"Code analysis failed: {first_line}")
                error_msg_for_analytics = f"Code analysis failed: {first_line}"
                error_type_for_analytics = "Code2PromptError"
                raise Exception(error_msg_for_analytics)

        os.makedirs(RESULTS_DIR, exist_ok=True)
        with open(result_file_path_on_disk, "w", encoding="utf-8") as f:
            f.write(result_content)
        output_file_size_capture = os.path.getsize(result_file_path_on_disk)
        final_status_for_analytics = "completed"
        update_job_status(job_id_str, "completed", result_file=result_file_path_on_disk)
        logger.info(f"[Upload Job {job_id_str}] Output saved to {result_file_path_on_disk}")

    except Exception as e:
        logger.exception(f"[Upload Job {job_id_str}] Error during processing: {e}")
        if not error_msg_for_analytics:
            error_msg_for_analytics = str(e)[:500]
        if not error_type_for_analytics:
            error_type_for_analytics = type(e).__name__
        update_job_status(job_id_str, "failed", error=error_msg_for_analytics)
    finally:
        overall_task_end_time = time.perf_counter()
        total_task_duration = overall_task_end_time - overall_task_start_time
        job_end_timestamp = datetime.datetime.utcnow()

        if not analytics_engine:
            logger.warning(f"Analytics engine not available for final update of upload job {job_uuid_for_analytics}. Skipping.")
        else:
            async with get_analytics_session_context() as analytics_session:
                if analytics_session:
                    stmt = select(UploadJobAnalytics).where(UploadJobAnalytics.job_uuid == job_uuid_for_analytics)
                    result_proxy = await analytics_session.execute(stmt)
                    record_to_update = result_proxy.scalar_one_or_none()
                    
                    if record_to_update:
                        record_to_update.job_end_time = job_end_timestamp
                        record_to_update.final_status = final_status_for_analytics
                        record_to_update.error_message = error_msg_for_analytics
                        record_to_update.error_type = error_type_for_analytics
                        record_to_update.output_size_bytes = output_file_size_capture
                        record_to_update.total_processing_duration_seconds = total_task_duration
                        
                        record_to_update.filtered_files_processed_count = filtered_files_count_from_endpoint
                        record_to_update.upload_folder_size_bytes = upload_size_bytes_from_endpoint
                        record_to_update.code_analysis_duration_seconds = code_analysis_duration
                        
                        analytics_session.add(record_to_update)
                        try:
                            await analytics_session.commit()
                            logger.info(f"Final analytics updated for upload job {job_uuid_for_analytics}")
                        except Exception as e_final_analytics:
                            logger.error(f"Analytics DB error on final upload job log for {job_uuid_for_analytics}: {e_final_analytics}")
                            await analytics_session.rollback()
                    else:
                        logger.error(f"Analytics record for upload job {job_uuid_for_analytics} not found for final update.")
                else:
                    logger.warning(f"Failed to get analytics session for final update of upload job {job_uuid_for_analytics}. Skipping.")
        
        if os.path.isdir(upload_dir_path):
            shutil.rmtree(upload_dir_path, ignore_errors=True)

# API Endpoints 
@app.post("/api/process-repo")
async def process_repo(
    repo_request: RepoRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    analytics_session: Optional[AsyncSession] = Depends(get_analytics_session_dependency)
):
    repo_url_str = repo_request.repo_url.strip()
    if not re.match(r'^https?://[^\s/$.?#].[^\s]*$', repo_url_str):
        raise HTTPException(status_code=400, detail="Invalid repository URL format.")
    
    job_id_str = create_job(job_type="repo")
    
    if analytics_session:
        try:
            job_uuid_for_analytics = app_uuid.UUID(job_id_str)
            user_ip = http_request.client.host
            
            analytics_entry = RepoJobAnalytics(
                job_uuid=job_uuid_for_analytics,
                job_start_time=datetime.datetime.utcnow(),
                user_ip=user_ip,
                repo_url=repo_url_str,
                include_patterns=repo_request.include_patterns,
                exclude_patterns=repo_request.exclude_patterns
            )
            analytics_session.add(analytics_entry)
            await analytics_session.commit()
            logger.info(f"Initial analytics record created for repo job {job_uuid_for_analytics}")
        except Exception as e_analytics:
            logger.error(f"Analytics DB error on initial repo job log for {job_id_str}: {e_analytics}")
    else:
        logger.warning(f"Analytics session not available for repo job {job_id_str}. Skipping initial analytics log.")

    background_tasks.add_task(process_repository_job, job_id_str, repo_url_str, repo_request.include_patterns, repo_request.exclude_patterns)
    logger.info(f"Job {job_id_str}: Background repository processing scheduled for {repo_url_str}")
    return {"job_id": job_id_str}

@app.post("/api/process-website")
async def process_website(
    website_request: WebsiteRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    analytics_session: Optional[AsyncSession] = Depends(get_analytics_session_dependency)
):
    website_url_str = str(website_request.website_url)
    job_id_str = create_job(job_type="website")
    
    if analytics_session:
        try:
            job_uuid_for_analytics = app_uuid.UUID(job_id_str)
            user_ip = http_request.client.host
            
            analytics_entry = WebsiteJobAnalytics(
                job_uuid=job_uuid_for_analytics,
                job_start_time=datetime.datetime.utcnow(),
                user_ip=user_ip,
                website_url=website_url_str,
                crawl_max_depth_setting=website_request.max_depth,
                crawl_max_pages_setting=website_request.max_pages,
                crawl_stay_on_domain_setting=website_request.stay_on_domain,
                crawl_include_patterns_setting=website_request.include_patterns,
                crawl_exclude_patterns_setting=website_request.exclude_patterns,
                crawl_keywords_setting=website_request.keywords
            )
            analytics_session.add(analytics_entry)
            await analytics_session.commit()
            logger.info(f"Initial analytics record created for website job {job_uuid_for_analytics}")
        except Exception as e_analytics:
            logger.error(f"Analytics DB error on initial website job log for {job_id_str}: {e_analytics}")
    else:
        logger.warning(f"Analytics session not available for website job {job_id_str}. Skipping initial analytics log.")

    background_tasks.add_task(
        process_website_job,
        job_id_str=job_id_str,
        website_url=website_url_str,
        max_depth=website_request.max_depth,
        max_pages=website_request.max_pages,
        stay_on_domain=website_request.stay_on_domain,
        include_patterns=website_request.include_patterns,
        exclude_patterns=website_request.exclude_patterns,
        keywords=website_request.keywords
    )
    logger.info(f"Job {job_id_str}: Background website processing scheduled for {website_url_str}")
    return {"job_id": job_id_str}

@app.post("/api/upload-codebase")
async def upload_codebase(
    background_tasks: BackgroundTasks,
    http_request: Request,
    files: List[UploadFile] = File(...),
    total_files_selected_by_user: Optional[int] = Form(None),
    analytics_session: Optional[AsyncSession] = Depends(get_analytics_session_dependency)
):
    job_id_str = create_job(job_type="upload")
    upload_dir = os.path.join(TEMP_DIR, job_id_str)
    os.makedirs(upload_dir, exist_ok=True)

    t_backend_upload_start = time.perf_counter()
    file_count = 0
    total_processed_size_bytes = 0
    original_folder_name_root_capture = None

    for file_idx, file in enumerate(files):
        relative_path = file.filename
        if not relative_path:
            logger.warning(f"Job {job_id_str}: Skipping file with empty filename.")
            continue
        
        if file_idx == 0 and relative_path:
            original_folder_name_root_capture = relative_path.split('/')[0] if '/' in relative_path else relative_path

        clean_relative_path = os.path.normpath(relative_path).lstrip('/\\.')
        if clean_relative_path != relative_path or "/../" in relative_path or "\\..\\" in relative_path:
            logger.error(f"Job {job_id_str}: Potentially unsafe path detected, skipping file: {relative_path}")
            continue
        
        full_path = os.path.join(upload_dir, clean_relative_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        try:
            with open(full_path, "wb") as f:
                while content := await file.read(1024 * 1024):
                    f.write(content)
                    total_processed_size_bytes += len(content)
            file_count += 1
        except Exception as write_error:
            logger.error(f"Job {job_id_str}: Failed to write file {relative_path}: {write_error}")
            continue

    t_backend_upload_end = time.perf_counter()
    backend_upload_handling_duration = t_backend_upload_end - t_backend_upload_start

    if analytics_session:
        try:
            job_uuid_for_analytics = app_uuid.UUID(job_id_str)
            user_ip = http_request.client.host

            analytics_entry = UploadJobAnalytics(
                job_uuid=job_uuid_for_analytics,
                job_start_time=datetime.datetime.utcnow(),
                user_ip=user_ip,
                initial_files_selected_count=total_files_selected_by_user,
                original_folder_name_root=original_folder_name_root_capture,
                backend_upload_handling_duration_seconds=backend_upload_handling_duration
            )
            analytics_session.add(analytics_entry)
            await analytics_session.commit()
            logger.info(f"Initial analytics record created for upload job {job_uuid_for_analytics}")
        except Exception as e_analytics:
            logger.error(f"Analytics DB error on initial upload job log for {job_id_str}: {e_analytics}")
    else:
        logger.warning(f"Analytics session not available for upload job {job_id_str}. Skipping initial analytics log.")

    if file_count == 0:
        update_job_status(job_id_str, "failed", error="No valid files uploaded.")
        if analytics_session:
            async with get_analytics_session_context() as final_session:
                if final_session:
                    stmt = select(UploadJobAnalytics).where(UploadJobAnalytics.job_uuid == app_uuid.UUID(job_id_str))
                    results = await final_session.exec(stmt)
                    record_to_update = results.one_or_none()
                    if record_to_update:
                        record_to_update.job_end_time = datetime.datetime.utcnow()
                        record_to_update.final_status = "failed"
                        record_to_update.error_message = "No valid files uploaded."
                        record_to_update.error_type = "UploadError"
                        record_to_update.filtered_files_processed_count = 0
                        record_to_update.upload_folder_size_bytes = 0
                        final_session.add(record_to_update)
                        try:
                            await final_session.commit()
                        except Exception as e_final_analytics:
                            logger.error(f"Analytics DB error on failed upload update for {job_id_str}: {e_final_analytics}")
                            await final_session.rollback()
        shutil.rmtree(upload_dir, ignore_errors=True)
        return {"job_id": job_id_str}

    update_job_status(job_id_str, "uploading")
    logger.info(f"Job {job_id_str}: Received {file_count} files, total size {total_processed_size_bytes} bytes.")
    background_tasks.add_task(
        process_upload,
        job_id_str,
        upload_dir,
        file_count,
        total_processed_size_bytes
    )
    return {"job_id": job_id_str}

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