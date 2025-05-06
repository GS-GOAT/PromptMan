import asyncio
import logging
import traceback
from crawl4ai import AsyncWebCrawler

logger = logging.getLogger(__name__)

# Default options for the crawler
DEFAULT_CRAWLER_OPTIONS = {
    "limit": 20,          # Max pages to crawl
    "max_depth": 5,       # Max crawl depth
    "timeout": 600,       # Overall crawl timeout in seconds
    "page_timeout": 60,   # Timeout per page request
}

async def run_crawl4ai(url: str):
    """
    Crawls a website using the crawl4ai library.

    Args:
        url: The website URL to crawl.

    Returns:
        A string containing the crawled text content (Markdown formatted) on success,
        or an error message string (starting with '# Error:' or '# Warning:') on failure or warning.
    """
    logger.info(f"Starting website crawl using crawl4ai library for: {url}")
    output_content = None

    try:
        async with AsyncWebCrawler(**DEFAULT_CRAWLER_OPTIONS) as crawler:
            result = await crawler.arun(url=url)

            if result and hasattr(result, 'markdown') and result.markdown:
                output_content = result.markdown
                logger.info(f"Crawl successful for {url}. Content length: {len(output_content)}")
                
                if hasattr(result, 'errors') and result.errors:
                    logger.warning(f"Crawl for {url} completed with errors reported by crawl4ai: {result.errors}")

            elif result and not hasattr(result, 'markdown'):
                logger.warning(f"Crawl completed for {url}, but result object has no 'markdown' attribute. Result type: {type(result)}")
                output_content = "# Warning: No Markdown Content Found\n\nCrawl completed, but no Markdown content was extracted. The result format might have changed or extraction failed."

            else:
                logger.warning(f"Crawl successful for {url}, but no content extracted (result.markdown is empty/None).")
                output_content = f"# Warning: No Content Extracted\n\ncrawl4ai ran successfully but did not extract text content from `{url}`. The site might be empty, heavily dynamic, or protected."

    except ImportError as e:
        logger.error(f"ImportError using crawl4ai: {e}. Is crawl4ai installed correctly?")
        output_content = f"# Error: Library Import Failed\n\nCould not import required components from crawl4ai: {e}. Check backend dependencies."
    except asyncio.TimeoutError:
        logger.error(f"Asyncio timeout during crawl for {url}")
        output_content = f"# Error: Operation Timed Out\n\nThe crawl operation for `{url}` timed out."
    except Exception as e:
        logger.exception(f"An unexpected error occurred while running crawl4ai library for {url}: {e}")
        output_content = f"# Error: Unexpected Crawl Failure\n\nAn error occurred during library execution:\n```\n{traceback.format_exc()}\n```"

    if output_content is None:
        logger.error(f"run_crawl4ai completed for {url} but output_content is None. Returning generic error.")
        output_content = "# Error: Unknown internal processing error occurred during crawl."

    return output_content