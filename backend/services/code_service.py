# backend/services/code_service.py
import asyncio
import subprocess
import os
import logging
import traceback

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Configuration ---
# Timeout for the entire code2prompt process (adjust as needed)
CODE2PROMPT_TIMEOUT_SECONDS = 300 # 5 minutes

async def run_code2prompt(directory: str):
    """
    Run Code2Prompt on an entire directory at once.

    Captures the standard output of the code2prompt command.
    """
    logger.info(f"Starting 'at once' code analysis for directory: {directory}")

    # --- Basic Input Validation ---
    if not os.path.isdir(directory):
        logger.error(f"Directory does not exist or is not a directory: {directory}")
        # Return an error message consistent with generated output format
        return f"# Error: Input Path Not Found\n\nThe specified path `{directory}` does not exist or is not a directory."

    # Check if directory is empty (or only contains empty subdirs)
    has_files = any(os.path.isfile(os.path.join(root, f)) for root, _, files in os.walk(directory) for f in files)
    if not has_files:
        logger.warning(f"Input directory {directory} is empty or contains no files.")
        return f"# Warning: No Files to Analyze\n\nThe directory `{directory}` contains no files to analyze."

    # --- Check code2prompt Availability ---
    try:
        # Optionally kill hanging processes first (might still be useful)
        try:
            pkill_process = await asyncio.create_subprocess_exec(
                "pkill", "-f", "code2prompt", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            await asyncio.wait_for(pkill_process.communicate(), timeout=2)
            logger.info("Attempted cleanup of potential hanging code2prompt processes.")
        except Exception as kill_error:
             logger.info(f"pkill check/command note: {kill_error}") # Non-critical

        version_process = await asyncio.create_subprocess_exec(
            "code2prompt", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout_v, stderr_v = await asyncio.wait_for(version_process.communicate(), timeout=10)

        if version_process.returncode != 0:
            err_msg = stderr_v.decode().strip() if stderr_v else "Unknown error"
            raise RuntimeError(f"code2prompt command error during version check: {err_msg}")
        logger.info(f"Using code2prompt version: {stdout_v.decode().strip()}")

    except FileNotFoundError:
         logger.error("`code2prompt` command not found in PATH.")
         raise RuntimeError("`code2prompt` command not found. Please ensure it is installed and in the system PATH.")
    except asyncio.TimeoutError:
         logger.error("Timeout checking code2prompt version.")
         raise RuntimeError("Timeout checking code2prompt version.")
    except Exception as e:
         logger.error(f"Error checking code2prompt: {e}", exc_info=True)
         raise RuntimeError(f"Failed to verify code2prompt installation: {e}")

    # --- Execute code2prompt on the Directory ---
    # Based on the error message, we need to use the --path flag
    # instead of a positional argument
    cmd = ["code2prompt", "--path", directory]
    logger.info(f"Executing command: {' '.join(cmd)}")

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Wait for the process to complete with a single, longer timeout
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=CODE2PROMPT_TIMEOUT_SECONDS
        )

        if process.returncode == 0:
            logger.info(f"code2prompt successfully processed directory: {directory}")
            # Decode stdout (the generated prompt/markdown)
            result = stdout.decode('utf-8')
            # Optional: Log stderr even on success if it contains warnings
            if stderr:
                 logger.warning(f"code2prompt stderr output (even on success):\n{stderr.decode('utf-8')}")
            return result
        else:
            error_message = stderr.decode('utf-8').strip() if stderr else "No error output."
            logger.error(f"code2prompt failed with exit code {process.returncode}. Error: {error_message}")
            # Return a formatted error message
            return f"# Error: Code2Prompt Failed\n\nExit Code: {process.returncode}\n\n**Error Output:**\n```\n{error_message}\n```"

    except asyncio.TimeoutError:
        logger.error(f"code2prompt timed out after {CODE2PROMPT_TIMEOUT_SECONDS} seconds processing directory: {directory}")
        try:
            if process and process.returncode is None: process.kill()
        except Exception: pass
        return f"# Error: Processing Timeout\n\nThe analysis of directory `{directory}` exceeded the time limit of {CODE2PROMPT_TIMEOUT_SECONDS} seconds."

    except Exception as e:
        logger.error(f"An unexpected error occurred while running code2prompt: {e}", exc_info=True)
        return f"# Error: Unexpected Failure\n\nAn error occurred during processing:\n```\n{traceback.format_exc()}\n```" 