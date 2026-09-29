from fastapi import FastAPI, HTTPException, Query
from typing import Optional, List, Dict, Any
import logging
from contextlib import asynccontextmanager
import os
import asyncio
import random
from pydantic import BaseModel

# Import the browser manager and scraper function
try:
    from gmaps_scraper_server.browser_manager import browser_manager
    from gmaps_scraper_server.scraper import scrape_google_maps, scrape_reviews_only
    from gmaps_scraper_server import extractor
except ImportError:
    logging.error("Could not import modules from gmaps_scraper_server.")
    # Define dummy functions and objects to allow API to start, but fail on call
    class DummyBrowserManager:
        async def start_browser(self, *args, **kwargs): pass
        async def stop_browser(self, *args, **kwargs): pass
        async def get_context(self, *args, **kwargs): pass
    browser_manager = DummyBrowserManager()
    def scrape_google_maps(*args, **kwargs):
        raise ImportError("Scraper function not available.")
    def scrape_reviews_only(*args, **kwargs):
        raise ImportError("Scraper function not available.")
    class DummyExtractor:
        REVIEW_SELECTION_COUNT = 100
        REVIEW_CANDIDATE_POOL_SIZE = 300
    extractor = DummyExtractor()

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the application's lifespan.
    Starts the browser when the app starts, and closes it when the app stops.
    """
    # Get headless mode from environment variable, default to True
    headless_mode = os.environ.get("HEADLESS", "true").lower() == "true"
    await browser_manager.start_browser(headless=headless_mode)
    yield
    await browser_manager.stop_browser()

app = FastAPI(
    title="Google Maps Scraper API",
    description="API to trigger Google Maps scraping based on a query.",
    version="0.3.0", # Version bump for reviews-only support
    lifespan=lifespan
)

class ReviewsRequest(BaseModel):
    urls: List[str]
    lang: str = "en"
    max_reviews: Optional[int] = None

@app.post("/reviews", response_model=List[Dict[str, Any]])
async def run_reviews_scrape(request: ReviewsRequest):
    """
    Triggers the reviews-only scraping process for a list of Google Maps URLs.
    Optimized for performance by skipping full place details and blocking assets.
    """
    logging.info(f"Received reviews scrape request for {len(request.urls)} URLs.")
    
    # Calculate effective max_reviews (default 100, capped at REVIEW_CANDIDATE_POOL_SIZE = 300)
    raw_max = request.max_reviews or extractor.REVIEW_SELECTION_COUNT
    effective_max_reviews = min(max(1, raw_max), extractor.REVIEW_CANDIDATE_POOL_SIZE)

    # Use a semaphore to limit concurrency
    # Optimized for 48 threads / 64GB RAM: 16 is a safe high-performance default, configurable via env
    concurrency_env = os.environ.get("REVIEW_SCRAPE_CONCURRENCY", "8")
    try:
        CONCURRENCY_LIMIT = max(1, int(concurrency_env))
    except ValueError:
        CONCURRENCY_LIMIT = 8
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    
    async def process_url(url, idx):
        # Stagger task initiation slightly (150-350ms) to avoid simultaneous burst detection
        if idx > 0:
            await asyncio.sleep(min(idx * 0.2, 2.0) + random.uniform(0.05, 0.15))
        async with semaphore:
            context = None
            try:
                # Get an isolated context for each URL (start with block_resources=True for performance)
                context = await browser_manager.get_context(lang=request.lang, block_resources=True)
                # We don't need the semaphore inside scrape_reviews_only anymore as we handle it here
                return await scrape_reviews_only(context, url, asyncio.Semaphore(1), max_reviews=effective_max_reviews, lang=request.lang)
            finally:
                if context:
                    await context.close()

    try:
        # Process URLs concurrently with isolated contexts
        tasks = [process_url(url, i) for i, url in enumerate(request.urls)]
        results = await asyncio.gather(*tasks)
        
        logging.info(f"Reviews scraping finished. Processed {len(results)} URLs.")
        return results
        
    except Exception as e:
        logging.error(f"An error occurred during reviews scraping: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred during scraping: {str(e)}")

@app.post("/scrape", response_model=List[Dict[str, Any]])
async def run_scrape(
    query: str = Query(..., description="The search query for Google Maps (e.g., 'restaurants in New York')"),
    max_places: Optional[int] = Query(None, description="Maximum number of places to scrape. Scrapes all found if None."),
    lang: str = Query("en", description="Language code for Google Maps results (e.g., 'en', 'es')."),
    extract_reviews: bool = Query(True, description="Set to true to extract all user reviews (slower)."),
    max_reviews: Optional[int] = Query(None, description="Maximum number of reviews to extract per place (defaults to 100, capped at 300).")
):
    """
    Triggers the Google Maps scraping process for the given query.
    """
    logging.info(f"Received scrape request for query: '{query}', max_places: {max_places}, lang: {lang}, extract_reviews: {extract_reviews}, max_reviews: {max_reviews}")
    try:
        results = await scrape_google_maps(
            query=query,
            max_places=max_places,
            lang=lang,
            extract_reviews=extract_reviews,
            max_reviews=max_reviews
        )
        logging.info(f"Scraping finished for query: '{query}'. Found {len(results)} results.")
        return results
    except ImportError as e:
         logging.error(f"ImportError during scraping for query '{query}': {e}")
         raise HTTPException(status_code=500, detail="Server configuration error: Scraper not available.")
    except Exception as e:
        logging.error(f"An error occurred during scraping for query '{query}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred during scraping: {str(e)}")

@app.get("/scrape-get", response_model=List[Dict[str, Any]])
async def run_scrape_get(
    query: str = Query(..., description="The search query for Google Maps (e.g., 'restaurants in New York')"),
    max_places: Optional[int] = Query(None, description="Maximum number of places to scrape. Scrapes all found if None."),
    lang: str = Query("en", description="Language code for Google Maps results (e.g., 'en', 'es')."),
    extract_reviews: bool = Query(True, description="Set to true to extract all user reviews (slower)."),
    max_reviews: Optional[int] = Query(None, description="Maximum number of reviews to extract per place (defaults to 100, capped at 300).")
):
    """
    Triggers the Google Maps scraping process for the given query via GET request.
    """
    logging.info(f"Received GET scrape request for query: '{query}', max_places: {max_places}, lang: {lang}, extract_reviews: {extract_reviews}, max_reviews: {max_reviews}")
    try:
        results = await scrape_google_maps(
            query=query,
            max_places=max_places,
            lang=lang,
            extract_reviews=extract_reviews,
            max_reviews=max_reviews
        )
        logging.info(f"Scraping finished for query: '{query}'. Found {len(results)} results.")
        return results
    except ImportError as e:
         logging.error(f"ImportError during scraping for query '{query}': {e}")
         raise HTTPException(status_code=500, detail="Server configuration error: Scraper not available.")
    except Exception as e:
        logging.error(f"An error occurred during scraping for query '{query}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred during scraping: {str(e)}")


# Basic root endpoint for health check or info
@app.get("/")
async def read_root():
    return {"message": "Google Maps Scraper API is running."}

# Example for running locally (uvicorn main_api:app --reload)
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)