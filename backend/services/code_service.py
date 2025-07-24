# backend/services/code_service.py
import asyncio
import subprocess
import os
import logging
import traceback
import time
import tempfile
import uuid
import shutil
from typing import Optional

# Logging Setup 
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Config
CODE2PROMPT_TIMEOUT_SECONDS = 300  # 5 minutes

# code2prompt Executable 
CODE2PROMPT_EXECUTABLE = shutil.which("code2prompt")

if not CODE2PROMPT_EXECUTABLE:
    logger.error("Cannot find 'code2prompt' executable in PATH. Ensure it's installed and accessible.")
    CODE2PROMPT_EXECUTABLE = "__EXECUTABLE_NOT_FOUND__"
else:
    logger.info(f"Found code2prompt executable at: {CODE2PROMPT_EXECUTABLE}")

def run_code2prompt_sync(directory: str, include_patterns: Optional[str] = None, exclude_patterns: Optional[str] = None):
    """Synchronous function using the dynamically found executable."""
    if CODE2PROMPT_EXECUTABLE == "__EXECUTABLE_NOT_FOUND__":
        return "# Error: Executable Not Found\n\nCould not find code2prompt executable in PATH."

    temp_output_filename = os.path.join(tempfile.gettempdir(), f"code2prompt_{uuid.uuid4()}.md")
    cmd = [CODE2PROMPT_EXECUTABLE, directory, "--output-file", temp_output_filename]
    
    if include_patterns:
        cmd.extend(["--include", include_patterns])
    if exclude_patterns:
        cmd.extend(["--exclude", exclude_patterns])

    logger.info(f"Executing command synchronously: {' '.join(cmd)}")
    output_content = None
    error_occurred = False

    try:
        process_start_time = time.time()
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=CODE2PROMPT_TIMEOUT_SECONDS,
            check=False
        )
        process_end_time = time.time()
        process_duration = process_end_time - process_start_time
        logger.info(f"Synchronous code2prompt subprocess finished in {process_duration:.2f} seconds.")

        if process.returncode == 0:
            logger.info(f"code2prompt successfully processed directory {directory} to {temp_output_filename}")
            try:
                with open(temp_output_filename, 'r', encoding='utf-8') as f:
                    output_content = f.read()
                logger.info(f"Successfully read content from {temp_output_filename}")
            except Exception as read_error:
                logger.error(f"Failed to read temp output file {temp_output_filename}: {read_error}", exc_info=True)
                error_occurred = True
                output_content = f"# Error: Failed to Read Output File\n\nCould not read the temporary result file: {read_error}"
            if process.stderr:
                stderr_lines = process.stderr.splitlines()
                filtered_stderr = "\n".join(line for line in stderr_lines if "copied to clipboard" not in line.lower())
                if filtered_stderr.strip():
                    logger.warning(f"code2prompt stderr output (even on success):\n{filtered_stderr}")
        else:
            error_occurred = True
            error_message = process.stderr.strip() if process.stderr else "No error output."
            logger.error(f"code2prompt failed with exit code {process.returncode}. Error: {error_message}")
            output_content = f"# Error: Code2Prompt Failed\n\nExit Code: {process.returncode}\n\n**Error Output:**\n```\n{error_message}\n```"
    except subprocess.TimeoutExpired:
        error_occurred = True
        logger.error(f"code2prompt timed out after {CODE2PROMPT_TIMEOUT_SECONDS} seconds processing directory: {directory}")
        output_content = f"# Error: Processing Timeout\n\nThe analysis of directory `{directory}` exceeded the time limit of {CODE2PROMPT_TIMEOUT_SECONDS} seconds."
    except FileNotFoundError:
        error_occurred = True
        logger.error(f"Executable not found at {CODE2PROMPT_EXECUTABLE}. Ensure the path is correct.")
        output_content = f"# Error: Executable Not Found\n\nCould not find code2prompt executable at specified path: {CODE2PROMPT_EXECUTABLE}"
    except Exception as e:
        error_occurred = True
        logger.error(f"An unexpected error occurred while running synchronous code2prompt: {e}", exc_info=True)
        output_content = f"# Error: Unexpected Failure\n\nAn error occurred during processing:\n```\n{traceback.format_exc()}\n```"
    finally:
        if os.path.exists(temp_output_filename):
            try:
                os.remove(temp_output_filename)
                logger.info(f"Cleaned up temporary output file: {temp_output_filename}")
            except Exception as cleanup_error:
                logger.warning(f"Failed to clean up temporary output file {temp_output_filename}: {cleanup_error}")

    return output_content

async def run_code2prompt(directory: str, include_patterns: Optional[str] = None, exclude_patterns: Optional[str] = None):
    """
    Run Code2Prompt using the dynamically found executable.
    """
    logger.info(f"Starting 'at once' code analysis for directory: {directory}")

    # Basic Input Validation 
    if not os.path.isdir(directory):
        logger.error(f"Directory does not exist or is not a directory: {directory}")
        return f"# Error: Input Path Not Found\n\nThe specified path `{directory}` does not exist or is not a directory."

    # Check if directory is empty (or only contains empty subdirs)
    has_files = any(os.path.isfile(os.path.join(root, f)) for root, _, files in os.walk(directory) for f in files)
    if not has_files:
        logger.warning(f"Input directory {directory} is empty or contains no files.")
        return f"# Warning: No Files to Analyze\n\nThe directory `{directory}` contains no files to analyze."

    try:
        if CODE2PROMPT_EXECUTABLE == "__EXECUTABLE_NOT_FOUND__":
            raise FileNotFoundError("code2prompt executable not found in PATH.")

        logger.info(f"Checking availability of executable: {CODE2PROMPT_EXECUTABLE}")
        version_process = await asyncio.create_subprocess_exec(
            CODE2PROMPT_EXECUTABLE, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout_v, stderr_v = await asyncio.wait_for(version_process.communicate(), timeout=10)
        if version_process.returncode != 0:
            err_msg = stderr_v.decode().strip() if stderr_v else "Unknown error checking version"
            if "No such option: --version" in err_msg:
                logger.info("Retrying version check with -V for cargo executable")
                version_process = await asyncio.create_subprocess_exec(
                    CODE2PROMPT_EXECUTABLE, "-V",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout_v, stderr_v = await asyncio.wait_for(version_process.communicate(), timeout=10)
                if version_process.returncode != 0:
                    err_msg = stderr_v.decode().strip() if stderr_v else "Unknown error checking version with -V"
                    raise RuntimeError(f"code2prompt command error during version check (-V): {err_msg}")
            else:
                raise RuntimeError(f"code2prompt command error during version check (--version): {err_msg}")

        reported_version = stdout_v.decode().strip()
        logger.info(f"Using code2prompt version: {reported_version}")
        if not reported_version.startswith("code2prompt 3."):
            logger.warning(f"Reported version '{reported_version}' does not look like v3.x")

    except FileNotFoundError:
        logger.error(f"`{CODE2PROMPT_EXECUTABLE}` not found. Ensure executable path is correct and exists.")
        return f"# Error: Executable Not Found\n\nCould not find code2prompt executable at specified path: {CODE2PROMPT_EXECUTABLE}"
    except asyncio.TimeoutError:
        logger.error("Timeout checking code2prompt version.")
        pass  # Don't raise, let execution attempt continue
    except Exception as e:
        logger.error(f"Error checking code2prompt at {CODE2PROMPT_EXECUTABLE}: {e}", exc_info=True)
        pass  # Allow execution to continue, run_code2prompt_sync will handle errors

    # Execute code2prompt using synchronous call in thread 
    try:
        result = await asyncio.to_thread(run_code2prompt_sync, directory, include_patterns, exclude_patterns)
        return result
    except Exception as e:
        logger.error(f"Error executing code2prompt via thread: {e}", exc_info=True)
        return f"# Error: Thread Execution Failed\n\nAn error occurred during processing via thread:\n```\n{traceback.format_exc()}\n```"