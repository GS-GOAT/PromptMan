import asyncio
import logging
import traceback
from typing import Optional, List

# Import necessary crawl4ai components
from crawl4ai import (
    AsyncWebCrawler,
    CrawlerRunConfig,
    LXMLWebScrapingStrategy,
    CacheMode,
)
from crawl4ai.deep_crawling import (
    DeepCrawlStrategy,
    BFSDeepCrawlStrategy,
    BestFirstCrawlingStrategy,
)
from crawl4ai.deep_crawling.filters import (
    FilterChain,
    URLPatternFilter,
)
from crawl4ai.deep_crawling.scorers import (
    KeywordRelevanceScorer,
)

logger = logging.getLogger(__name__)

# --- Default Values ---
DEFAULT_CRAWL_MAX_DEPTH = 0
DEFAULT_CRAWL_MAX_PAGES = 5
DEFAULT_STAY_ON_DOMAIN = True

async def run_crawl4ai(url: str, 
                      max_depth: Optional[int] = None,
                      max_pages: Optional[int] = None,
                      stay_on_domain: Optional[bool] = None,
                      include_patterns_str: Optional[str] = None,
                      exclude_patterns_str: Optional[str] = None,
                      keywords_str: Optional[str] = None):
    """
    Enhanced website crawler using crawl4ai with advanced options.

    Args:
        url: The website URL to crawl
        max_depth: Maximum crawl depth (0=start page only)
        max_pages: Maximum total pages to crawl
        stay_on_domain: Whether to stay on the initial domain
        include_patterns_str: Comma-separated URL wildcard patterns to include
        exclude_patterns_str: Comma-separated URL wildcard patterns to exclude
        keywords_str: Comma-separated keywords for relevance-based crawling

    Returns:
        Markdown-formatted content string or error/warning message
    """
    logger.info(f"Starting enhanced crawl4ai for {url}")
    output_content = None

    try:
        # --- Apply Defaults ---
        effective_max_depth = max_depth if max_depth is not None else DEFAULT_CRAWL_MAX_DEPTH
        effective_max_pages = max_pages if max_pages is not None else DEFAULT_CRAWL_MAX_PAGES
        # include_external is the inverse of stay_on_domain
        effective_include_external = not (stay_on_domain if stay_on_domain is not None else DEFAULT_STAY_ON_DOMAIN)
        logger.info(f"Effective crawl params: depth={effective_max_depth}, pages={effective_max_pages}, include_external={effective_include_external}")

        # --- Prepare Filters ---
        filters = []
        if include_patterns_str:
            try:
                include_patterns = [p.strip() for p in include_patterns_str.split(',') if p.strip()]
                if include_patterns:
                    filters.append(URLPatternFilter(patterns=include_patterns, exclusion=False))
                    logger.info(f"Applying URL include patterns: {include_patterns}")
            except Exception as e:
                logger.warning(f"Could not parse include patterns '{include_patterns_str}': {e}")

        if exclude_patterns_str:
            try:
                exclude_patterns = [p.strip() for p in exclude_patterns_str.split(',') if p.strip()]
                if exclude_patterns:
                    filters.append(URLPatternFilter(patterns=exclude_patterns, exclusion=True))
                    logger.info(f"Applying URL exclude patterns: {exclude_patterns}")
            except Exception as e:
                logger.warning(f"Could not parse exclude patterns '{exclude_patterns_str}': {e}")

        # Always create a FilterChain, even if filters list is empty
        filter_chain = FilterChain(filters=filters)
        logger.info(f"Created filter chain with {len(filters)} filter(s)")

        # --- Prepare Scorer and Strategy ---
        url_scorer = None
        crawl_strategy_class = BFSDeepCrawlStrategy # Default

        if keywords_str:
            try:
                keywords = [k.strip().lower() for k in keywords_str.split(',') if k.strip()]
                if keywords:
                    url_scorer = KeywordRelevanceScorer(keywords=keywords, weight=1.0)
                    crawl_strategy_class = BestFirstCrawlingStrategy # Switch strategy
                    logger.info(f"Using BestFirstCrawlingStrategy with keywords: {keywords}")
                else:
                    logger.info("Keywords provided but resulted in empty list.")
            except Exception as e:
                logger.warning(f"Could not parse keywords '{keywords_str}': {e}")
        else:
            logger.info("No keywords provided, using default BFS strategy.")

        # --- Configure Strategy ---
        deep_crawl_strategy = crawl_strategy_class(
            max_depth=effective_max_depth,
            max_pages=effective_max_pages,
            include_external=effective_include_external,
            url_scorer=url_scorer,
            filter_chain=filter_chain  # Always pass the FilterChain
        )

        # --- Prepare Crawler Run Configuration ---
        config = CrawlerRunConfig(
            deep_crawl_strategy=deep_crawl_strategy,
            # Using default scraper for better JS handling
            verbose=False
        )
        logger.info(f"Instantiating crawler for {url} with strategy {type(deep_crawl_strategy).__name__} and config.")

        # --- Execute Crawl ---
        async with AsyncWebCrawler() as crawler:
            # arun returns list[CrawlResult] for deep crawls, or single CrawlResult for shallow
            results_or_result = await crawler.arun(url=url, config=config)

            # --- Process Result ---
            # Handle both single result (shallow crawl, depth=0) and list (deep crawl)
            results_list = []
            if isinstance(results_or_result, list):
                results_list = results_or_result
                logger.info(f"Deep crawl returned {len(results_list)} results.")
            elif results_or_result:  # Check if it's a single, non-None result
                results_list = [results_or_result]
                logger.info("Shallow crawl returned a single result.")
            else:
                logger.warning(f"Crawl for {url} returned None or empty result.")

            if results_list:
                all_markdown = []
                crawl_errors = []
                for res in results_list:
                    if hasattr(res, 'markdown') and res.markdown:
                        # Add URL header only if multiple pages were likely crawled
                        header = f"\n\n## Page: {res.url}\n\n" if len(results_list) > 1 else ""
                        all_markdown.append(f"{header}{res.markdown}")
                    if hasattr(res, 'error') and res.error:
                        crawl_errors.append(f"  - {res.url}: {str(res.error)[:200]}")  # Log snippet

                if crawl_errors:
                    logger.warning(f"Crawl for {url} encountered errors on {len(crawl_errors)} pages:\n" + "\n".join(crawl_errors))

                if all_markdown:
                    output_content = f"# Crawl Results for: {url}\n" + "\n\n---\n".join(all_markdown)
                    logger.info(f"Crawl aggregated for {url}. Final length: {len(output_content)}. Pages processed: {len(results_list)}")
                else:
                    # Crawled pages but no markdown extracted from any
                    logger.warning(f"Crawl completed for {url} ({len(results_list)} pages), but no markdown content extracted.")
                    output_content = f"# Warning: No Content Extracted\n\nCrawled {len(results_list)} pages for `{url}`, but no text content could be extracted from them."

            else:
                # No results in the list, implies nothing was crawled successfully (filtered out, empty site, etc.)
                logger.warning(f"Crawl for {url} returned no results. Filters might be too strict or site empty/inaccessible.")
                output_content = f"# Warning: No Pages Crawled\n\nNo pages matching the criteria were successfully crawled for `{url}`."

    except ImportError as e:
        logger.error(f"ImportError using crawl4ai components: {e}.")
        output_content = f"# Error: Library Import Failed\n\nCould not import required components: {e}."
    except TypeError as e:
        logger.exception(f"TypeError during crawl4ai configuration or execution for {url}: {e}")
        output_content = f"# Error: Configuration Error\n\nInvalid configuration passed to crawl4ai: {e}"
    except asyncio.TimeoutError:
        logger.error(f"Crawl operation timed out for {url}")
        output_content = f"# Error: Operation Timed Out\n\nThe crawl operation for `{url}` timed out."
    except Exception as e:
        logger.exception(f"An unexpected error occurred while running crawl4ai library for {url}: {e}")
        output_content = f"# Error: Unexpected Crawl Failure\n\nAn error occurred:\n```\n{traceback.format_exc()}\n```"

    # Final fallback
    if output_content is None:
        logger.error(f"run_crawl4ai logic completed for {url} but output_content is None.")
        output_content = "# Error: Unknown internal processing error during crawl."

    return output_content