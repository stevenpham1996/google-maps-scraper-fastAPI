### **High-Level Goal**

Integrate the scraping of `open_hours`, `images`, and `user_reviews` into the existing Python/FastAPI application by adapting the proven extraction logic from the Go project.

### **Technical Strategy**

1.  **Leverage Initial JSON:** For `open_hours` and `images`, we will add new extractor functions that parse the main JSON data blob, using the index paths identified from the Go project.
2.  **Replicate RPC for Reviews:** For `user_reviews`, we will replicate the Go project's efficient strategy of making direct API-like calls to a hidden Google RPC endpoint (`listugcposts`). This avoids brittle UI scrolling and is significantly faster.
3.  **Maintain Modularity:** All new data parsing logic will reside in `gmaps_scraper_server/extractor.py`, while the control flow and browser/network interactions will be updated in `gmaps_scraper_server/scraper.py`.

---

## **Technical Implementation Plan**

### Phase 1: Add `open_hours` and `images` Extraction

This is the most straightforward task. We'll add new functions to `extractor.py` to parse data that is already present in the JSON blob we're fetching.

**File to Modify:** `gmaps_scraper_server/extractor.py`

[x] **1.1. Create the `get_open_hours` function:**
Based on the Go project's `getHours` function (which uses index path `[34][1]`), create a Python equivalent.

*Add this function to `extractor.py`:*
```python
def get_open_hours(data):
    """Extracts the opening hours for each day."""
    # Path based on Go project: darray[34][1]
    hours_list = safe_get(data, 34, 1)
    if not isinstance(hours_list, list):
        return None
    
    open_hours = {}
    for item in hours_list:
        if isinstance(item, list) and len(item) >= 2:
            day = safe_get(item, 0)
            times = safe_get(item, 1)
            if day and isinstance(times, list):
                open_hours[day] = times
    
    return open_hours if open_hours else None
```

[x] **1.2. Create the `get_images` function:**
The Go project extracts images from path `[171][0]`. Each image item then has a title and a URL at specific sub-indices.

*Add this function to `extractor.py`:*
```python
def get_images(data):
    """Extracts a list of images with their titles."""
    # Path based on Go project: darray[171][0]
    images_list = safe_get(data, 171, 0)
    if not isinstance(images_list, list):
        return None
        
    images = []
    for item in images_list:
        # Go project logic: getLinkSource with source:[2] and link:[3,0,6,0]
        title = safe_get(item, 2)
        url = safe_get(item, 3, 0, 6, 0)
        if title and url:
            images.append({"title": title, "image": url})
            
    return images if images else None
```

[x] **1.3. Update `extract_place_data` to include the new fields:**
Integrate the new functions into the main orchestration function.

*Modify the `place_details` dictionary inside the `extract_place_data` function:*
```python
def extract_place_data(html_content, all_reviews=None): # Add new all_reviews parameter
    """
    High-level function to orchestrate extraction from HTML content.
    """
    json_str = extract_initial_json(html_content)
    if not json_str:
        print("Failed to extract JSON string from HTML.")
        return None

    data_blob = parse_json_data(json_str)
    if not data_blob:
        print("Failed to parse JSON data or find expected structure.")
        return None

    # Now extract individual fields using the helper functions
    place_details = {
        "name": get_main_name(data_blob),
        "place_id": get_place_id(data_blob),
        "coordinates": get_gps_coordinates(data_blob),
        "address": get_complete_address(data_blob),
        "rating": get_rating(data_blob),
        "reviews_count": get_reviews_count(data_blob),
        "categories": get_categories(data_blob),
        "website": get_website(data_blob),
        "phone": get_phone_number(data_blob),
        "thumbnail": get_thumbnail(data_blob),
        # --- NEW FIELDS ---
        "open_hours": get_open_hours(data_blob),
        "images": get_images(data_blob),
        "user_reviews": parse_user_reviews(all_reviews if all_reviews else safe_get(data_blob, 52)), # Use all_reviews if available
    }

    # Filter out None values if desired
    place_details = {k: v for k, v in place_details.items() if v is not None}

    return place_details if place_details else None
```

### Phase 2: Implement User Review Extraction (RPC Method)

This is the most significant change. We will add logic to fetch all reviews via RPC and parse them.

**Files to Modify:** `gmaps_scraper_server/scraper.py`, `gmaps_scraper_server/extractor.py`, `gmaps_scraper_server/main_api.py`.

[x] **2.1. Add a new API parameter to enable/disable review scraping:**
This is an intensive operation, so it should be optional.

*In `gmaps_scraper_server/main_api.py`, add `extract_reviews` to both `run_scrape` and `run_scrape_get` endpoints:*
```python
# In run_scrape
async def run_scrape(
    # ... existing parameters
    extract_reviews: bool = Query(False, description="Set to true to extract all user reviews (slower).")
):
    # ...
    results = await scrape_google_maps(
        # ... existing arguments
        extract_reviews=extract_reviews
    )
    # ...

# In run_scrape_get
async def run_scrape_get(
    # ... existing parameters
    extract_reviews: bool = Query(False, description="Set to true to extract all user reviews (slower).")
):
    # ...
    results = await scrape_google_maps(
        # ... existing arguments
        extract_reviews=extract_reviews
    )
    # ...
```

[x] **2.2. Create the review parsing logic in `extractor.py`:**
This function will parse the raw review data we get from the RPC calls. The Go project provides the exact index paths.

*Add this new function to `gmaps_scraper_server/extractor.py`:*
```python
def parse_user_reviews(reviews_data):
    """Parses a list of raw review data from the RPC response."""
    if not isinstance(reviews_data, list):
        return None

    parsed_reviews = []
    for review in reviews_data:
        # Paths based on Go project's parseReviews function
        author_name = safe_get(review, 0, 1)
        profile_picture_url = safe_get(review, 0, 2)
        review_text = safe_get(review, 3)
        rating = safe_get(review, 4)
        relative_time = safe_get(review, 1) # e.g., "a week ago"
        
        # The Go project extracts more, but this is a solid start.
        # You can expand this by inspecting the `review` object.
        # For example, to get review photos:
        photos = [safe_get(photo, 6, 0) for photo in safe_get(review, 14) or [] if safe_get(photo, 6, 0)]

        if author_name and rating is not None:
            parsed_reviews.append({
                "name": author_name,
                "profile_picture": profile_picture_url,
                "rating": rating,
                "description": review_text,
                "when": relative_time,
                "images": photos
            })
    return parsed_reviews if parsed_reviews else None
```
> **Note:** The Go project gets initial reviews from `darray[175][9][0][0]` and extended reviews from the RPC call. The structure of the RPC response is slightly different. The `safe_get(data_blob, 52)` path I added in step 1.3 is a common location for the initial ~8 reviews. The `parse_user_reviews` function above is tailored for the RPC response (`listugcposts`), which is the superior method we're implementing.

[x] **2.3. Implement the RPC fetching logic in `scraper.py`:**
This is the core of the review extraction. We will create a new async helper function to manage the RPC calls.

*First, add necessary imports at the top of `gmaps_scraper_server/scraper.py`:*
```python
import random
import string
from urllib.parse import quote
```

*Next, add the new helper function `fetch_all_reviews` to `gmaps_scraper_server/scraper.py`:*
```python
async def fetch_all_reviews(page, place_link):
    """
    Fetches all user reviews by simulating the internal RPC call.
    This is more robust and efficient than UI scrolling.
    """
    # Regex to find the place ID from the URL (e.g., !1s<ID>)
    place_id_match = re.search(r'!1s([^!]+)', place_link)
    if not place_id_match:
        print("Could not extract place ID for reviews RPC.")
        return []

    place_id = place_id_match.group(1)
    
    # This is the base for the RPC call
    rpc_base_url = "https://www.google.com/maps/preview/reviews"

    all_reviews = []
    next_page_token = '0' # Start with 0
    page_num = 0
    max_pages = 10 # Safety break to avoid infinite loops

    while next_page_token and page_num < max_pages:
        # Construct the RPC URL. The parameters are specific and mimic the browser's request.
        # Go project has a more complex pb param, but this simpler preview/reviews often works.
        # If this fails, the pb param from the Go project needs to be constructed.
        params = {
            'authuser': '0',
            'hl': 'en',
            'gl': 'us',
            'pb': f'!1s{place_id}!2i{next_page_token}!3i10!4i0!5m2!1s{page_num+1}!2i10!6i1', # Simplified pb
        }
        
        try:
            response = await page.request.get(rpc_base_url, params=params)
            if response.status != 200:
                print(f"Error fetching reviews page {page_num+1}: Status {response.status}")
                break

            content = await response.body()
            # The response is prefixed with a security token `)]}'` which must be removed.
            json_str = content.decode('utf-8').lstrip(")]}'")
            data = json.loads(json_str)

            # The reviews are typically in the second element of the main list
            reviews_list = safe_get(data, 2)
            if isinstance(reviews_list, list):
                all_reviews.extend(reviews_list)
                print(f"Fetched {len(reviews_list)} reviews. Total: {len(all_reviews)}")

            # The next page token is the second element of the first element
            next_page_token = safe_get(data, 1, 1)
            page_num += 1
            await asyncio.sleep(random.uniform(0.5, 1.5)) # Be a good citizen

        except Exception as e:
            print(f"An exception occurred while fetching reviews: {e}")
            break
            
    return all_reviews
```

[x] **2.4. Integrate the review fetching into the main `scrape_google_maps` function:**

*Modify `gmaps_scraper_server/scraper.py` and `gmaps_scraper_server/main_api.py` to pass the `extract_reviews` parameter:*

```python
# In scraper.py
async def scrape_google_maps(query, max_places=None, lang="en", headless=True, extract_reviews=False): # Add extract_reviews
    # ... (existing code) ...
            # --- Scraping Individual Places ---
            print(f"\nScraping details for {len(place_links)} places...")
            count = 0
            for link in place_links:
                count += 1
                print(f"Processing link {count}/{len(place_links)}: {link}")
                try:
                    await page.goto(link, wait_until='domcontentloaded')

                    all_reviews = None
                    if extract_reviews:
                        print("  - Extracting all user reviews...")
                        all_reviews = await fetch_all_reviews(page, link)

                    html_content = await page.content()
                    # Pass the fetched reviews to the extractor
                    place_data = extractor.extract_place_data(html_content, all_reviews)

                    if place_data:
                        place_data['link'] = link
                        results.append(place_data)
                    else:
                        print(f"  - Failed to extract data for: {link}")

                except PlaywrightTimeoutError:
                    print(f"  - Timeout navigating to or processing: {link}")
                except Exception as e:
                    print(f"  - Error processing {link}: {e}")
                await asyncio.sleep(0.5)

            await browser.close()
    # ... (rest of the function) ...
```
