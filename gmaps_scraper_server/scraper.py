import json
import asyncio
import re
import random
from urllib.parse import quote
import os
import base64
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from urllib.parse import urlencode

# Import the extraction functions and the browser manager
from . import extractor
from .browser_manager import browser_manager

# --- Constants ---
BASE_URL = "https://www.google.com/maps/search/"
SCROLL_PAUSE_TIME = 1.5
MAX_SCROLL_ATTEMPTS_WITHOUT_NEW_LINKS = 5

# --- Helper Functions ---
def create_search_url(query, lang="en", geo_coordinates=None, zoom=None):
    """Creates a Google Maps search URL."""
    params = {'q': query, 'hl': lang}
    return BASE_URL + "?" + urlencode(params)

def generate_random_id(length):
    """Generates a URL-safe random ID, mimicking the Go implementation."""
    num_bytes = (length * 6 + 7) // 8
    random_bytes = os.urandom(num_bytes)
    encoded = base64.urlsafe_b64encode(random_bytes).decode('utf-8')
    return encoded.replace('=', '')[:length]

async def fetch_all_reviews(page, place_link, place_id=None):
    """
    Fetches all user reviews by simulating the internal 'listugcposts' RPC call.
    If place_id is not provided, it attempts to extract it from the place_link.
    """
    if not place_id:
        place_id_match = re.search(r'!1s([^!]+)', place_link)
        if not place_id_match:
            place_id_match = re.search(r'ftid=([^&]+)', place_link)
            
        if place_id_match:
            place_id = place_id_match.group(1)
        else:
            print("Could not extract place ID for reviews RPC from link.")
            # Fallback: Try to extract from page content if available
            try:
                content = await page.content()
                json_str = extractor.extract_initial_json(content)
                if json_str:
                    initial_data = json.loads(json_str)
                    basic_info = extractor.get_basic_info_from_initial_json(initial_data)
                    place_id = basic_info.get("place_id")
            except Exception as e:
                print(f"Error during fallback place_id extraction: {e}")

    if not place_id:
        print("Failed to resolve place ID. Cannot fetch reviews.")
        return []

    print(f"  - Using place_id for reviews: {place_id}")
    rpc_base_url = "https://www.google.com/maps/rpc/listugcposts"
    all_reviews_data = []
    next_page_token = ""
    page_num = 0
    max_pages = 20

    while True:
        request_id = generate_random_id(21)
        pb_components = [
            f"!1m6!1s{quote(place_id)}",
            "!6m4!4m1!1e1!4m1!1e3",
            f"!2m2!1i10!2s{quote(next_page_token)}",
            f"!5m2!1s{request_id}!7e81",
            "!8m9!2b1!3b1!5b1!7b1!12m4!1b1!2b1!4m1!1e1!11m4!1e3!2e1!6m1!1i2!13m1!1e1",
        ]
        pb_param = "".join(pb_components)
        full_url = f"{rpc_base_url}?authuser=0&hl=en&pb={pb_param}"
        
        try:
            response = await page.request.get(full_url)
            if response.status != 200:
                print(f"Error fetching reviews page {page_num+1}: Status {response.status}")
                break

            content = await response.body()
            json_str = content.decode('utf-8').lstrip(")]}'")
            data = json.loads(json_str)

            reviews_list = extractor.safe_get(data, 2)
            if isinstance(reviews_list, list):
                all_reviews_data.extend(reviews_list)

            next_page_token = extractor.safe_get(data, 1)
            
            if not next_page_token or page_num >= max_pages or len(all_reviews_data) > 300:
                break
                
            page_num += 1
            await asyncio.sleep(random.uniform(0.8, 1.8))

        except Exception as e:
            print(f"An exception occurred while fetching reviews: {e}")
            break
            
    return all_reviews_data

# --- Main Scraping Logic ---
async def scrape_reviews_only(context, link, semaphore):
    """
    Scrapes ONLY user reviews for a single place link.
    Optimized for performance by skipping full place details extraction and blocking assets.
    """
    async with semaphore:
        page = None
        try:
            page = await context.new_page()
            print(f"Processing link for reviews only: {link}")
            
            # Navigate and follow redirects. 'load' is safer for session initialization.
            await page.goto(link, wait_until='load', timeout=60000)
            
            resolved_url = page.url
            print(f"  - Resolved URL: {resolved_url}")
            
            all_reviews = await fetch_all_reviews(page, resolved_url)
            
            # Process and select high-quality reviews
            # Note: We run this in a thread to avoid blocking the event loop
            user_reviews = await asyncio.to_thread(extractor.process_and_select_reviews, all_reviews)
            
            return {
                "link": link,
                "resolved_url": resolved_url,
                "user_reviews": user_reviews or [],
                "status": "success"
            }

        except PlaywrightTimeoutError:
            print(f"  - Timeout processing: {link}")
            return {"link": link, "status": "timeout", "error": "Timeout navigating to the link."}
        except Exception as e:
            print(f"  - Error processing {link}: {e}")
            return {"link": link, "status": "error", "error": str(e)}
        finally:
            if page:
                await page.close()

async def scrape_google_maps(query, max_places=None, lang="en", extract_reviews=False):
    """
    Scrapes Google Maps for places based on a query using a shared browser context.
    """
    results = []
    place_links = set()
    scroll_attempts_no_new = 0
    context = None

    try:
        # Use a single page for the initial search and link gathering
        context = await browser_manager.get_context(lang=lang)
        page = await context.new_page()
        if not page:
            raise Exception("Failed to create a new browser page.")

        search_url = create_search_url(query, lang)
        print(f"Navigating to search URL: {search_url}")
        await page.goto(search_url, wait_until='domcontentloaded')
        await asyncio.sleep(2)

        await handle_consent(page)

        print("Scrolling to load places...")
        feed_selector = '[role="feed"]'
        try:
            await page.wait_for_selector(feed_selector, state='visible', timeout=25000)
        except PlaywrightTimeoutError:
            if "/maps/place/" in page.url:
                print("Detected single place page.")
                place_links.add(page.url)
            else:
                print(f"Error: Feed element '{feed_selector}' not found. Taking screenshot.")
                await page.screenshot(path='feed_not_found_screenshot.png')
                return []

        if await page.locator(feed_selector).count() > 0:
            # Scrolling logic remains the same
            last_height = await page.evaluate(f'document.querySelector(\'{feed_selector}\').scrollHeight')
            while True:
                await page.evaluate(f'document.querySelector(\'{feed_selector}\').scrollTop = document.querySelector(\'{feed_selector}\').scrollHeight')
                await asyncio.sleep(SCROLL_PAUSE_TIME)

                current_links_list = await page.locator(f'{feed_selector} a[href*="/maps/place/"]').evaluate_all('elements => elements.map(a => a.href)')
                current_links = set(current_links_list)
                new_links_found = len(current_links - place_links) > 0
                place_links.update(current_links)
                print(f"Found {len(place_links)} unique place links so far...")

                if max_places is not None and len(place_links) >= max_places:
                    print(f"Reached max_places limit ({max_places}).")
                    place_links = set(list(place_links)[:max_places])
                    break

                new_height = await page.evaluate(f'document.querySelector(\'{feed_selector}\').scrollHeight')
                if new_height == last_height:
                    end_marker_xpath = "//span[contains(text(), \"You've reached the end of the list.\")]"
                    if await page.locator(end_marker_xpath).count() > 0:
                        print("Reached the end of the results list.")
                        break
                    else:
                        if not new_links_found:
                            scroll_attempts_no_new += 1
                            if scroll_attempts_no_new >= MAX_SCROLL_ATTEMPTS_WITHOUT_NEW_LINKS:
                                print("Stopping scroll due to lack of new links.")
                                break
                        else:
                            scroll_attempts_no_new = 0
                else:
                    last_height = new_height
                    scroll_attempts_no_new = 0
        
        await page.close() # Close the initial search page

        # --- Scraping Individual Places Concurrently ---
        if place_links:
            print(f"\nScraping details for {len(place_links)} places concurrently...")
            CONCURRENCY_LIMIT = 15
            semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

            tasks = [scrape_place_details(context, link, extract_reviews, semaphore) for link in place_links]
            scraped_data_list = await asyncio.gather(*tasks)
            results = [data for data in scraped_data_list if data is not None]

    except Exception as e:
        print(f"An error occurred during scraping: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if context:
            await context.close()

    print(f"\nScraping finished. Found details for {len(results)} places.")
    return results

async def scrape_place_details(context, link, extract_reviews, semaphore):
    """Scrapes details for a single place link."""
    async with semaphore:
        page = None
        try:
            page = await context.new_page()
            print(f"Processing link: {link}")
            await page.goto(link, wait_until='domcontentloaded')
            
            # Wait for main content to ensure semantic attributes are rendered
            try:
                await page.wait_for_selector('div[role="main"]', timeout=5000)
            except:
                pass
            
            all_reviews = None
            if extract_reviews:
                print(f"  - Extracting all user reviews for: {link}")
                all_reviews = await fetch_all_reviews(page, link)

            html_content = await page.content()
            place_data = await asyncio.to_thread(extractor.extract_place_data, html_content, all_reviews)

            if place_data:
                place_data['link'] = link
                return place_data
            else:
                print(f"  - Failed to extract data for: {link}")
                return None

        except PlaywrightTimeoutError:
            print(f"  - Timeout navigating to or processing: {link}")
            return None
        except Exception as e:
            print(f"  - Error processing {link}: {e}")
            return None
        finally:
            if page:
                await page.close()


async def handle_consent(page):
    """Handles the consent form if it appears."""
    consent_button_locator = page.locator("//button[.//span[contains(text(), 'Accept all') or contains(text(), 'Reject all')]]")
    feed_locator = page.locator('[role="feed"]')
    combined_locator = consent_button_locator.or_(feed_locator)

    max_consent_retries = 3
    initial_consent_timeout = 5000

    for attempt in range(max_consent_retries):
        timeout = initial_consent_timeout * (2 ** attempt)
        print(f"Consent/Feed Check, Attempt {attempt + 1}/{max_consent_retries} (Timeout: {timeout/1000}s)...")
        
        try:
            await combined_locator.first.wait_for(state='visible', timeout=timeout)

            if await consent_button_locator.is_visible():
                print("Consent form detected. Clicking it...")
                await consent_button_locator.first.click()
                await page.wait_for_load_state('networkidle', timeout=5000)
                return

            elif await feed_locator.is_visible():
                print("Main feed detected. No consent form shown.")
                return

        except PlaywrightTimeoutError:
            print(f"Timeout on attempt {attempt + 1}.")
            if attempt == max_consent_retries - 1:
                print("Max retries reached. Failed to find consent form or load main feed.")
                await page.screenshot(path='consent_failure_screenshot.png')
                raise Exception("Fatal: Could not handle consent or verify main content.")