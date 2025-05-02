# backend/main.py
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import shutil
import time
from typing import List
import uuid
import asyncio
import logging
import redis
import json

# Import the revised code service
from services.code_service import run_code2prompt

# --- Configuration ---
TEMP_DIR = "temp"
RESULTS_DIR = "results"
CLEANUP_AGE_SECONDS = 24 * 60 * 60  # 24 hours
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
JOB_EXPIRY_SECONDS = CLEANUP_AGE_SECONDS + 3600  # Keep job data slightly longer than files

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- FastAPI App Initialization ---
app = FastAPI(title="PromptMan Direct API")

# --- Redis Connection ---
try:
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
    redis_client.ping()
    logger.info(f"Successfully connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
except redis.exceptions.ConnectionError as e:
    logger.error(f"Failed to connect to Redis at {REDIS_HOST}:{REDIS_PORT} - {e}")
    redis_client = None

# --- CORS Middleware ---
allowed_origins_str = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
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

def create_job():
    """Creates a new job entry in Redis and returns its ID."""
    if not redis_client:
        raise HTTPException(status_code=503, detail="Job storage unavailable (Redis connection failed)")
    job_id = str(uuid.uuid4())
    job_data = {
        "status": "pending",
        "created_at": time.time(),
        "updated_at": time.time(),
        "error": None,
        "result_file": None
    }
    redis_client.set(f"job:{job_id}", json.dumps(job_data), ex=JOB_EXPIRY_SECONDS)
    logger.info(f"Job created in Redis: {job_id}")
    return job_id

def update_job_status(job_id, status, error=None, result_file=None):
    """Updates the status and other details of a job in Redis."""
    if not redis_client:
        return
    job_key = f"job:{job_id}"
    try:
        job_data_str = redis_client.get(job_key)
        if not job_data_str:
            logger.warning(f"Attempted to update status for non-existent job in Redis: {job_id}")
            return

        job_data = json.loads(job_data_str)
        job_data["status"] = status
        job_data["updated_at"] = time.time()
        job_data["error"] = str(error) if error else None
        job_data["result_file"] = result_file

        redis_client.set(job_key, json.dumps(job_data), ex=JOB_EXPIRY_SECONDS)
        logger.info(f"Job {job_id} status updated to {status} in Redis")
        if error:
            logger.error(f"Job {job_id} failed with error: {error}")
    except Exception as e:
        logger.error(f"Failed to update job {job_id} status in Redis: {e}")

def get_job_status(job_id):
    """Retrieves the status of a job from Redis."""
    if not redis_client:
        return None
    job_data_str = redis_client.get(f"job:{job_id}")
    if job_data_str:
        return json.loads(job_data_str)
    return None

# --- Cleanup Logic ---
def cleanup_old_files(directory: str, max_age_seconds: int):
    """Removes files/dirs older than max_age_seconds in a given directory."""
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
                    shutil.rmtree(item_path)
                    logger.info(f"Cleaned up old directory: {item_path}")
        except Exception as e:
            logger.warning(f"Error during cleanup of {item_path}: {e}")

# --- Middleware for Cleanup ---
@app.middleware("http")
async def cleanup_middleware(request: Request, call_next):
    cleanup_old_files(TEMP_DIR, CLEANUP_AGE_SECONDS)
    cleanup_old_files(RESULTS_DIR, CLEANUP_AGE_SECONDS)
    response = await call_next(request)
    return response

# --- Background Task for Processing Uploads ---
async def process_upload(temp_dir: str, job_id: str):
    """Handles the actual code processing in the background."""
    result_file_path = os.path.join(RESULTS_DIR, f"{job_id}.md")
    try:
        logger.info(f"Starting code analysis for job {job_id} in directory {temp_dir}")
        update_job_status(job_id, "processing")

        if not os.path.isdir(temp_dir):
            raise FileNotFoundError(f"Temporary directory {temp_dir} vanished before processing.")

        logger.info(f"Calling run_code2prompt (at once) for job {job_id}")
        result_content = await run_code2prompt(temp_dir)
        logger.info(f"Code analysis finished for job {job_id}. Result length: {len(result_content)}")

        if result_content.startswith("# Error:") or result_content.startswith("# Warning:"):
            logger.warning(f"Job {job_id}: run_code2prompt reported an issue:\n{result_content[:200]}...")
            if result_content.startswith("# Error:"):
                update_job_status(job_id, "failed", error=result_content.split('\n', 2)[1])
            else:
                update_job_status(job_id, "completed", result_file=result_file_path)
        else:
            update_job_status(job_id, "completed", result_file=result_file_path)

        os.makedirs(RESULTS_DIR, exist_ok=True)
        with open(result_file_path, "w", encoding="utf-8") as f:
            f.write(result_content)
        logger.info(f"Output for job {job_id} saved to {result_file_path}")

    except Exception as e:
        logger.exception(f"Error processing upload for job {job_id}: {e}")
        update_job_status(job_id, "failed", error=str(e))
        if os.path.exists(result_file_path):
            try:
                os.remove(result_file_path)
            except OSError:
                pass
    finally:
        logger.info(f"Cleaning up temporary directory {temp_dir} for job {job_id}")
        try:
            if os.path.isdir(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as cleanup_error:
            logger.warning(f"Error during final cleanup of {temp_dir}: {str(cleanup_error)}")

@app.post("/api/upload-codebase")
async def upload_codebase(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
    """Accepts folder uploads, saves files, and starts background processing."""
    job_id = create_job()
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

            file_size = 0
            try:
                with open(full_path, "wb") as f:
                    while content := await file.read(1024 * 1024):
                        f.write(content)
                        file_size += len(content)
                file_count += 1
                total_size += file_size
            except Exception as write_error:
                logger.error(f"Job {job_id}: Failed to write file {relative_path}: {write_error}")

        logger.info(f"Job {job_id}: Upload complete. Received {file_count} files, total size {total_size} bytes.")

        if file_count == 0:
            logger.warning(f"Job {job_id}: No valid files were uploaded.")
            update_job_status(job_id, "failed", error="No valid files uploaded.")
            shutil.rmtree(upload_dir, ignore_errors=True)
            return {"job_id": job_id}

        background_tasks.add_task(process_upload, upload_dir, job_id)
        logger.info(f"Job {job_id}: Background processing task scheduled.")

        return {"job_id": job_id}

    except Exception as e:
        logger.exception(f"Critical error during file upload for job {job_id}: {e}")
        update_job_status(job_id, "failed", error=f"Upload failed: {e}")
        if os.path.isdir(upload_dir):
            shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"File upload failed: {e}")

@app.get("/api/job-status/{job_id}")
async def job_status(job_id: str):
    """Returns the current status of a background job."""
    status_info = get_job_status(job_id)
    if status_info is None:
        logger.warning(f"Status requested for unknown job: {job_id}")
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "status": status_info["status"],
        "created_at": status_info["created_at"],
        "updated_at": status_info["updated_at"],
        "error": status_info["error"]
    }

@app.get("/api/download/{job_id}")
async def download_file(job_id: str):
    """Allows downloading the result file for a completed job."""
    status_info = get_job_status(job_id)
    if status_info is None or status_info["status"] != "completed" or not status_info.get("result_file"):
        logger.warning(f"Download requested for incomplete or non-existent job result: {job_id}")
        raise HTTPException(status_code=404, detail="Result not found or job not completed")

    file_path = status_info["result_file"]
    if not os.path.exists(file_path):
        logger.error(f"Result file path recorded but file missing for job {job_id}: {file_path}")
        raise HTTPException(status_code=404, detail="Result file not found")

    logger.info(f"Serving download for job {job_id} from {file_path}")
    return FileResponse(file_path, filename=f"promptman_result_{job_id}.md", media_type='text/markdown')

@app.get("/")
async def root():
    """Simple health check or API root message"""
    return {"message": "PromptMan Backend is running."}