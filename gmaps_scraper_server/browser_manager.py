# gmaps_scraper_server/browser_manager.py
from playwright.async_api import async_playwright, Browser, Playwright
import asyncio

class BrowserManager:
    def __init__(self):
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None

    async def start_browser(self, headless=True):
        """Initializes Playwright and launches a persistent browser instance."""
        if self.browser and self.browser.is_connected():
            print("Browser is already running.")
            return
        
        print("Starting browser...")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=headless)
        print("Browser started successfully.")

    async def stop_browser(self):
        """Closes the browser and stops Playwright."""
        if self.browser and self.browser.is_connected():
            print("Closing browser...")
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self.browser = None
        self.playwright = None
        print("Browser stopped.")

    async def get_context(self, lang="en"):
        """
        Provides a new, isolated browser context for a single request.
        This is much faster than creating a new browser.
        """
        if not self.browser or not self.browser.is_connected():
            raise Exception("Browser is not running. Please start it first.")
        
        context = await self.browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            java_script_enabled=True,
            accept_downloads=False,
            locale=lang,
        )
        return context

# Create a single, shared instance of the browser manager.
# This instance will be imported by other modules.
browser_manager = BrowserManager()
