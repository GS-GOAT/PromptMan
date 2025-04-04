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

# Import the revised code service
from services.code_service import run_code2prompt

# --- Configuration ---
TEMP_DIR = "temp"
RESULTS_DIR = "results"
CLEANUP_AGE_SECONDS = 24 * 60 * 60 # 24 hours

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- FastAPI App Initialization ---
app = FastAPI(title="PromptMan Direct API") # Changed title slightly

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all origins for simplicity, restrict in production
    allow_credentials=True,
    allow_methods=["*"], # Allow all methods
    allow_headers=["*"], # Allow all headers
)

# --- Directory Creation ---
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

# --- In-memory Job Tracking ---
JOBS = {} # Simple dictionary to store job status

def create_job():
    """Creates a new job entry and returns its ID."""
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "status": "pending",
        "created_at": time.time(),
        "updated_at": time.time(),
        "error": None,
        "result_file": None # Store path to result file if successful
    }
    logger.info(f"Job created: {job_id}")
    return job_id

def update_job_status(job_id, status, error=None, result_file=None):
    """Updates the status and other details of a job."""
    if job_id in JOBS:
        JOBS[job_id]["status"] = status
        JOBS[job_id]["updated_at"] = time.time()
        JOBS[job_id]["error"] = str(error) if error else None
        JOBS[job_id]["result_file"] = result_file
        logger.info(f"Job {job_id} status updated to {status}")
        if error:
             logger.error(f"Job {job_id} failed with error: {error}")
    else:
         logger.warning(f"Attempted to update status for non-existent job: {job_id}")

def get_job_status(job_id):
    """Retrieves the status of a job."""
    return JOBS.get(job_id)

# --- Cleanup Logic ---
def cleanup_old_files(directory: str, max_age_seconds: int):
    """Removes files/dirs older than max_age_seconds in a given directory."""
    if not os.path.isdir(directory):
        return
    current_time = time.time()
    for item_name in os.listdir(directory):
        item_path = os.path.join(directory, item_name)
        try:
            item_age = current_time - os.path.getmtime(item_path) # Use modification time
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

        # Basic check: ensure temp directory exists
        if not os.path.isdir(temp_dir):
             raise FileNotFoundError(f"Temporary directory {temp_dir} vanished before processing.")

        # --- Call the revised run_code2prompt ---
        logger.info(f"Calling run_code2prompt (at once) for job {job_id}")
        result_content = await run_code2prompt(temp_dir) # This now runs on the whole dir
        logger.info(f"Code analysis finished for job {job_id}. Result length: {len(result_content)}")

        # Check if the result content indicates an error occurred within the service
        if result_content.startswith("# Error:") or result_content.startswith("# Warning:"):
             # Treat errors reported by the service as job failures or warnings
             logger.warning(f"Job {job_id}: run_code2prompt reported an issue:\n{result_content[:200]}...") # Log snippet
             # Decide if it's a failure or just a warning to pass through
             if result_content.startswith("# Error:"):
                  update_job_status(job_id, "failed", error=result_content.split('\n', 2)[1]) # Extract error line
             else: # It's a warning (e.g., empty folder)
                  update_job_status(job_id, "completed", result_file=result_file_path) # Mark completed but content has warning
        else:
             # Success
             update_job_status(job_id, "completed", result_file=result_file_path)

        # Save the result (could be success output, warning, or error message)
        os.makedirs(RESULTS_DIR, exist_ok=True)
        with open(result_file_path, "w", encoding="utf-8") as f:
            f.write(result_content)
        logger.info(f"Output for job {job_id} saved to {result_file_path}")

    except Exception as e:
        # Catch errors from the process_upload function itself or exceptions
        # re-raised from run_code2prompt (like tool not found)
        logger.exception(f"Error processing upload for job {job_id}: {e}") # Log full traceback
        update_job_status(job_id, "failed", error=e)
        # Ensure result file doesn't exist if failed outside the service writing it
        if os.path.exists(result_file_path):
            try: os.remove(result_file_path)
            except OSError: pass
    finally:
        # Clean up the temporary upload directory regardless of success/failure
        logger.info(f"Cleaning up temporary directory {temp_dir} for job {job_id}")
        try:
            if os.path.isdir(temp_dir): # Check existence before removal
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as cleanup_error:
            logger.warning(f"Error during final cleanup of {temp_dir}: {str(cleanup_error)}")

@app.post("/api/upload-codebase")
async def upload_codebase(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
    """
    Accepts folder uploads, saves files, and starts background processing.
    """
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
                    while content := await file.read(1024 * 1024): # Read in chunks
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

# --- Static File Serving (Optional: For Development) ---
try:
    app.mount("/", StaticFiles(directory="../frontend/build", html=True), name="static_frontend")
    logger.info("Serving static frontend files from ../frontend/build")
except RuntimeError:
     logger.info("Static frontend directory not found or not configured.")
     @app.get("/")
     async def root():
          return {"message": "PromptMan Backend is running. Frontend not served."}


# --- Main Execution ---
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting PromptMan Direct Backend") # Updated name
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info") 