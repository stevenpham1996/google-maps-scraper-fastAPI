
import asyncio
import logging
from unittest.mock import MagicMock, AsyncMock, patch

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Mock objects before importing browser_manager if possible, 
# but browser_manager imports playwright at top level. 
# We can patch it in the script.

async def run_test():
    # Patch asyncio.sleep to be faster or just rely on logic
    # Patch main_api's browser_manager or just instance
    
    # We need to test the browser_manager instance from the module
    # or create a new one. The module creates one at the end.
    
    with patch('gmaps_scraper_server.browser_manager.async_playwright') as mock_playwright_fn:
        # Setup mocks
        mock_playwright_obj = MagicMock() # The playwright object itself is not awaitable, but its methods might be
        mock_browser = MagicMock()
        mock_context = MagicMock() # context object
        
        # async_playwright().start() is awaited.
        # So async_playwright() returns a ContextManager... wait. 
        # Actually in the code: await async_playwright().start()
        # So async_playwright() returns something that has a start() method which is awaitable.
        
        mock_playwright_context_manager = MagicMock()
        mock_playwright_fn.return_value = mock_playwright_context_manager
        
        # .start() returns the actual playwright instance
        mock_playwright_instance = MagicMock()
        mock_playwright_context_manager.start = AsyncMock(return_value=mock_playwright_instance)
        # Mock stop() as well
        mock_playwright_instance.stop = AsyncMock()
        
        # self.playwright.chromium.launch()
        mock_browser_instance = MagicMock()
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser_instance)
        
        # browser.new_context()
        mock_context_instance = AsyncMock() # Used as object with methods but also need to be returned
        # Actually browser.new_context() is awaited.
        mock_browser_instance.new_context = AsyncMock(return_value=mock_context_instance)
        mock_browser_instance.is_connected.return_value = True
        mock_browser_instance.close = AsyncMock()
        
        mock_context_instance.close = AsyncMock()
        
        from gmaps_scraper_server.browser_manager import browser_manager
        
        # Reset any state if needed (it's a singleton in the module)
        browser_manager.browser = None
        browser_manager.playwright = None
        
        logging.info("Starting browser (mocked)...")
        await browser_manager.start_browser()
        
        async def simulate_restart():
            logging.info("Triggering browser restart...")
            # Simulate some delay in restart to widen the race window
            original_stop = browser_manager._stop_browser
            original_start = browser_manager._start_browser
            
            async def slow_stop():
                await asyncio.sleep(0.1)
                await original_stop()
            
            async def slow_start(headless=True):
                await asyncio.sleep(0.1)
                await original_start(headless)

            # Inject delays into the private methods for testing purpose? 
            # Or just rely on the existing lock to handle it.
            # The issue was that restart called stop (clearing browser) then start.
            # In between, get_context could be called.
            
            await browser_manager.restart_browser()
            logging.info("Browser restart complete.")

        async def simulate_request(i):
            try:
                # logging.info(f"Request {i}: Attempting to get context...")
                context = await browser_manager.get_context()
                # logging.info(f"Request {i}: Context acquired.")
            except Exception as e:
                logging.error(f"Request {i}: Failed with error: {e}")
                # Re-raise to fail the test if we want strict check
                raise e

        logging.info("Starting race condition test with MOCKS...")
        
        tasks = []
        # Launch requests and restart concurrent
        # High concurrency to catch the race
        
        # We want restart to happen WHILE get_context checks are happening.
        
        tasks.append(asyncio.create_task(simulate_restart()))
        
        for i in range(50):
            tasks.append(asyncio.create_task(simulate_request(i)))
            await asyncio.sleep(0.005) # Stagger slightly
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        failures = [r for r in results if isinstance(r, Exception)]
        
        if failures:
            logging.error(f"Test FAILED. {len(failures)} requests failed.")
            for f in failures:
                logging.error(f"Error: {f}")
            exit(1)
        else:
            logging.info("Test PASSED. All requests handled safely (or waited).")

if __name__ == "__main__":
    try:
        asyncio.run(run_test())
    except ImportError:
        # Fallback if dependencies not fully present, though we strive to use what's there
        print("Could not import modules. Ensure you are running with `uv run python -m ...`")
        exit(1)
