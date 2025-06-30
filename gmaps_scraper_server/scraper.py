import json
import asyncio # Changed from time
import re
import random
from urllib.parse import quote
import os
import base64
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError # Changed to async
from urllib.parse import urlencode

# Import the extraction functions from our helper module
from . import extractor

# --- Constants ---
BASE_URL = "https://www.google.com/maps/search/"
DEFAULT_TIMEOUT = 30000  # 30 seconds for navigation and selectors
SCROLL_PAUSE_TIME = 1.5  # Pause between scrolls
MAX_SCROLL_ATTEMPTS_WITHOUT_NEW_LINKS = 5 # Stop scrolling if no new links found after this many scrolls

# --- Helper Functions ---
def create_search_url(query, lang="en", geo_coordinates=None, zoom=None):
    """Creates a Google Maps search URL."""
    params = {'q': query, 'hl': lang}
    # Note: geo_coordinates and zoom might require different URL structure (/maps/@lat,lng,zoom)
    # For simplicity, starting with basic query search
    return BASE_URL + "?" + urlencode(params)

def generate_random_id(length):
    """Generates a URL-safe random ID, mimicking the Go implementation."""
    num_bytes = (length * 6 + 7) // 8
    random_bytes = os.urandom(num_bytes)
    encoded = base64.urlsafe_b64encode(random_bytes).decode('utf-8')
    return encoded.replace('=', '')[:length]

async def fetch_all_reviews(page, place_link):
    """
    Fetches all user reviews by simulating the internal 'listugcposts' RPC call.
    This is more robust and efficient than UI scrolling.
    """
    place_id_match = re.search(r'!1s([^!]+)', place_link)
    if not place_id_match:
        print("Could not extract place ID for reviews RPC.")
        return []

    place_id = place_id_match.group(1)
    
    rpc_base_url = "https://www.google.com/maps/rpc/listugcposts"

    all_reviews_data = []
    
    # --- CHANGE 1: Start with an empty page token, not '0'. ---
    # This correctly signals to the API to start from the beginning.
    next_page_token = ""
    
    page_num = 0
    max_pages = 20 # Safety break to avoid infinite loops

    # It will correctly stop when the token is an empty string ("") or None.
    # The initial empty string will be handled by the first iteration.
    while True:
        request_id = generate_random_id(21)
        
        # Construct the 'pb' parameter to match the Go project's structure
        pb_components = [
            f"!1m6!1s{quote(place_id)}",
            "!6m4!4m1!1e1!4m1!1e3",
            f"!2m2!1i20!2s{quote(next_page_token)}", # Page size 20
            f"!5m2!1s{request_id}!7e81",
            "!8m9!2b1!3b1!5b1!7b1!12m4!1b1!2b1!4m1!1e1!11m0!13m1!1e1",
        ]
        pb_param = "".join(pb_components)
        
        # Manually construct the URL to prevent '!' from being URL-encoded.
        full_url = f"{rpc_base_url}?authuser=0&hl=en&pb={pb_param}"
        
        try:
            response = await page.request.get(full_url)
            if response.status != 200:
                print(f"Error fetching reviews page {page_num+1}: Status {response.status}")
                break

            content = await response.body()
            json_str = content.decode('utf-8').lstrip(")]}'")
            data = json.loads(json_str)

            # Reviews are in the list at index 2
            reviews_list = extractor.safe_get(data, 2)
            if isinstance(reviews_list, list):
                all_reviews_data.extend(reviews_list)
                print(f"Fetched {len(reviews_list)} reviews. Total: {len(all_reviews_data)}")

            # The next page token is the string at index 1.
            # If it's missing or an empty string, the loop will terminate.
            next_page_token = extractor.safe_get(data, 1)
            
            # explicit exit condition for loop ---
            if not next_page_token or page_num >= max_pages or len(all_reviews_data) > 300:
                break
                
            page_num += 1
            await asyncio.sleep(random.uniform(0.8, 1.8))

        except Exception as e:
            print(f"An exception occurred while fetching reviews: {e}")
            break
            
    return all_reviews_data

# --- Main Scraping Logic ---
async def scrape_google_maps(query, max_places=None, lang="en", headless=True, extract_reviews=False): # Added async
    """
    Scrapes Google Maps for places based on a query.

    Args:
        query (str): The search query (e.g., "restaurants in New York").
        max_places (int, optional): Maximum number of places to scrape. Defaults to None (scrape all found).
        lang (str, optional): Language code for Google Maps (e.g., 'en', 'es'). Defaults to "en".
        headless (bool, optional): Whether to run the browser in headless mode. Defaults to True.
        extract_reviews (bool, optional): Whether to extract all user reviews. Defaults to False.

    Returns:
        list: A list of dictionaries, each containing details for a scraped place.
              Returns an empty list if no places are found or an error occurs.
    """
    results = []
    place_links = set()
    scroll_attempts_no_new = 0

    async with async_playwright() as p: # Changed to async
        try:
            browser = await p.chromium.launch(headless=headless) # Added await
            context = await browser.new_context( # Added await
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                java_script_enabled=True,
                accept_downloads=False,
                # Consider setting viewport, locale, timezone if needed
                locale=lang,
            )
            page = await context.new_page() # Added await
            if not page:
                await browser.close() # Close browser before raising
                raise Exception("Failed to create a new browser page (context.new_page() returned None).")
            # Removed problematic: await page.set_default_timeout(DEFAULT_TIMEOUT)
            # Removed associated debug prints

            search_url = create_search_url(query, lang)
            print(f"Navigating to search URL: {search_url}")
            await page.goto(search_url, wait_until='domcontentloaded') # Added await
            await asyncio.sleep(2) # Changed to asyncio.sleep, added await

            # --- Handle potential consent forms (Optimized with Retry Logic) ---
            consent_button_locator = page.locator("//button[.//span[contains(text(), 'Accept all') or contains(text(), 'Reject all')]]")
            feed_locator = page.locator('[role="feed"]')
            combined_locator = consent_button_locator.or_(feed_locator)

            max_consent_retries = 3
            initial_consent_timeout = 5000  # Start with a 5-second timeout

            consent_handled = False
            for attempt in range(max_consent_retries):
                # Exponentially increase timeout: 5s, 10s, 20s
                timeout = initial_consent_timeout * (2 ** attempt)
                print(f"Consent/Feed Check, Attempt {attempt + 1}/{max_consent_retries} (Timeout: {timeout/1000}s)...")
                
                try:
                    # Wait for either the consent button OR the main feed to become visible
                    await combined_locator.first.wait_for(state='visible', timeout=timeout)

                    # If we reach here, one of the selectors is visible. Check which one.
                    if await consent_button_locator.is_visible():
                        print("Consent form detected. Clicking it...")
                        # Using first to be safe, though there should only be one.
                        await consent_button_locator.first.click()
                        # Wait for the page to process the click and settle
                        await page.wait_for_load_state('networkidle', timeout=5000)
                        consent_handled = True
                        break  # Success, exit retry loop

                    # If it wasn't the consent button, it must be the feed.
                    elif await feed_locator.is_visible():
                        print("Main feed detected. Assuming no consent form was shown. Proceeding.")
                        consent_handled = True
                        break  # Success, exit retry loop

                except PlaywrightTimeoutError:
                    print(f"Timeout on attempt {attempt + 1}. Neither consent form nor main feed loaded in time.")
                    if attempt == max_consent_retries - 1:
                        print("Max retries reached. Failed to find consent form or load main feed.")
                        # Optionally, take a screenshot for debugging before failing
                        await page.screenshot(path='consent_failure_screenshot.png')
                        # Re-raise the final timeout error to be caught by the outer handler
                        raise

            # This check ensures the loop was successfully exited
            if not consent_handled:
                # This state should ideally not be reached, but it's a good safeguard.
                raise Exception("Fatal: Could not handle consent or verify main content after all retries.")


            # --- Scrolling and Link Extraction ---
            print("Scrolling to load places...")
            feed_selector = '[role="feed"]'
            try:
                await page.wait_for_selector(feed_selector, state='visible', timeout=25000) # Added await
            except PlaywrightTimeoutError:
                 # Check if it's a single result page (maps/place/)
                if "/maps/place/" in page.url:
                    print("Detected single place page.")
                    place_links.add(page.url)
                else:
                    print(f"Error: Feed element '{feed_selector}' not found. Maybe no results? Taking screenshot.")
                    await page.screenshot(path='feed_not_found_screenshot.png') # Added await
                    await browser.close() # Added await
                    return [] # No results or page structure changed

            if await page.locator(feed_selector).count() > 0: # Added await
                last_height = await page.evaluate(f'document.querySelector(\'{feed_selector}\').scrollHeight') # Added await
                while True:
                    # Scroll down
                    await page.evaluate(f'document.querySelector(\'{feed_selector}\').scrollTop = document.querySelector(\'{feed_selector}\').scrollHeight') # Added await
                    await asyncio.sleep(SCROLL_PAUSE_TIME) # Changed to asyncio.sleep, added await

                    # Extract links after scroll
                    current_links_list = await page.locator(f'{feed_selector} a[href*="/maps/place/"]').evaluate_all('elements => elements.map(a => a.href)') # Added await
                    current_links = set(current_links_list)
                    new_links_found = len(current_links - place_links) > 0
                    place_links.update(current_links)
                    print(f"Found {len(place_links)} unique place links so far...")

                    if max_places is not None and len(place_links) >= max_places:
                        print(f"Reached max_places limit ({max_places}).")
                        place_links = set(list(place_links)[:max_places]) # Trim excess links
                        break

                    # Check if scroll height has changed
                    new_height = await page.evaluate(f'document.querySelector(\'{feed_selector}\').scrollHeight') # Added await
                    if new_height == last_height:
                        # Check for the "end of results" marker
                        end_marker_xpath = "//span[contains(text(), \"You've reached the end of the list.\")]"
                        if await page.locator(end_marker_xpath).count() > 0: # Added await
                            print("Reached the end of the results list.")
                            break
                        else:
                            # If height didn't change but end marker isn't there, maybe loading issue?
                            # Increment no-new-links counter
                            if not new_links_found:
                                scroll_attempts_no_new += 1
                                print(f"Scroll height unchanged and no new links. Attempt {scroll_attempts_no_new}/{MAX_SCROLL_ATTEMPTS_WITHOUT_NEW_LINKS}")
                                if scroll_attempts_no_new >= MAX_SCROLL_ATTEMPTS_WITHOUT_NEW_LINKS:
                                    print("Stopping scroll due to lack of new links.")
                                    break
                            else:
                                scroll_attempts_no_new = 0 # Reset if new links were found this cycle
                    else:
                        last_height = new_height
                        scroll_attempts_no_new = 0 # Reset if scroll height changed

                    # Optional: Add a hard limit on scrolls to prevent infinite loops
                    # if scroll_count > MAX_SCROLLS: break

            # --- Scraping Individual Places ---
            print(f"\nScraping details for {len(place_links)} places...")
            count = 0
            for link in place_links:
                count += 1
                print(f"Processing link {count}/{len(place_links)}: {link}") # Keep sync print
                try:
                    await page.goto(link, wait_until='domcontentloaded') # Added await
                    
                    all_reviews = None
                    if extract_reviews:
                        print("  - Extracting all user reviews...")
                        all_reviews = await fetch_all_reviews(page, link)

                    html_content = await page.content() # Added await
                    place_data = extractor.extract_place_data(html_content, all_reviews)

                    if place_data:
                        place_data['link'] = link # Add the source link
                        results.append(place_data)
                        # print(json.dumps(place_data, indent=2)) # Optional: print data as it's scraped
                    else:
                        print(f"  - Failed to extract data for: {link}")
                        # Optionally save the HTML for debugging
                        # with open(f"error_page_{count}.html", "w", encoding="utf-8") as f:
                        #     f.write(html_content)

                except PlaywrightTimeoutError:
                    print(f"  - Timeout navigating to or processing: {link}")
                except Exception as e:
                    print(f"  - Error processing {link}: {e}")
                await asyncio.sleep(0.5) # Changed to asyncio.sleep, added await

            await browser.close() # Added await

        except PlaywrightTimeoutError:
            print(f"Timeout error during scraping process.")
        except Exception as e:
            print(f"An error occurred during scraping: {e}")
            import traceback
            traceback.print_exc() # Print detailed traceback for debugging
        finally:
            # Ensure browser is closed if an error occurred mid-process
            if 'browser' in locals() and browser.is_connected(): # Check if browser exists and is connected
                await browser.close() # Added await

    print(f"\nScraping finished. Found details for {len(results)} places.")
    return results

# --- Example Usage ---
# (Example usage block removed as this script is now intended to be imported as a module)
