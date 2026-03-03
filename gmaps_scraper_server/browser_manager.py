# gmaps_scraper_server/browser_manager.py
from playwright.async_api import async_playwright, Browser, Playwright
import asyncio
import re

class BrowserManager:
    def __init__(self):
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.headless_config: bool = True
        self._lock = asyncio.Lock()

    async def start_browser(self, headless=True):
        """Initializes Playwright and launches a persistent browser instance."""
        async with self._lock:
            await self._start_browser(headless)

    async def _start_browser(self, headless=True):
        """Internal method to start browser without locking."""
        self.headless_config = headless
        if self.browser and self.browser.is_connected():
            print("Browser is already running.")
            return
        
        print("Starting browser...")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=headless)
        print("Browser started successfully.")

    async def restart_browser(self):
        """Restarts the browser instance safely."""
        print("Restarting browser instance...")
        async with self._lock:
            try:
                await self._stop_browser()
            except Exception as e:
                print(f"Error stopping browser during restart: {e}")
            await self._start_browser(headless=self.headless_config)

    async def stop_browser(self):
        """Closes the browser and stops Playwright."""
        async with self._lock:
            await self._stop_browser()

    async def _stop_browser(self):
        """Internal method to stop browser without locking."""
        if self.browser and self.browser.is_connected():
            print("Closing browser...")
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self.browser = None
        self.playwright = None
        print("Browser stopped.")

    async def get_context(self, lang="en", block_resources=False):
        """
        Provides a new, isolated browser context for a single request.
        This is much faster than creating a new browser.
        """
        async with self._lock:
            if not self.browser or not self.browser.is_connected():
                # Try to auto-recover if browser claims to be disconnected, 
                # though usually better to raise or handle via restart logic.
                # For now, we raise as before, but the lock ensures we don't 
                # hit this mid-restart if restart is holding the lock.
                raise Exception("Browser is not running. Please start it first.")
            
            context = await self.browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                java_script_enabled=True,
                accept_downloads=False,
                locale=lang,
            )
            
            if block_resources:
                # Block only images to save bandwidth while keeping CSS/Fonts for stability
                await context.route(
                    re.compile(r"\.(jpg|jpeg|png|gif|svg|ico)$"), 
                    lambda route: route.abort()
                )
                
            return context

# Create a single, shared instance of the browser manager.
# This instance will be imported by other modules.
browser_manager = BrowserManager()
