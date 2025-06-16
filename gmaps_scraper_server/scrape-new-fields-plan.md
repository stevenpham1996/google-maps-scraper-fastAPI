### Part 3: Detailed Technical Plan & Code Modifications

This plan outlines the precise changes needed to implement the review datetime extraction feature. The sole focus will be on modifying the `gmaps_scraper_server/extractor.py` file.

#### **Task 1: Implement Datetime Extraction in `parse_user_reviews`**

You will replace the placeholder logic in `gmaps_scraper_server/extractor.py` with code that fetches and formats the date components, mirroring the Go implementation.

**File to Modify:** `gmaps_scraper_server/extractor.py`

**Function to Modify:** `parse_user_reviews`

**Instructions:**

1.  Locate the `parse_user_reviews` function.
2.  Find the block of code responsible for handling the review date (currently a placeholder).
3.  Replace the existing placeholder block with the new, improved implementation provided below.

**Current Code (Before Modification):**
```python
        # ... inside the for loop of parse_user_reviews ...
        
        # Date extraction is complex, using relative time is a good start
        # The Go code formats a date from multiple fields: [2, 2, 0, 1, 21, 6, 8]
        # For simplicity, we can use a placeholder or extract what's available
        when = "N/A" # Placeholder

        # Extract review images
        # ...
```

**New Code (After Modification):**
```python
        # ... inside the for loop of parse_user_reviews ...
        
        # --- Datetime Extraction ---
        # This logic is based on the Go project's successful extraction path.
        # It retrieves a list like [year, month, day, ...] and formats it.
        date_parts = safe_get(review, 2, 2, 0, 1, 21, 6, 8)
        when = "N/A"  # Default value
        if isinstance(date_parts, list) and len(date_parts) >= 3:
            try:
                # Ensure parts are integers before formatting for safety
                year, month, day = int(date_parts[0]), int(date_parts[1]), int(date_parts[2])
                # Format to YYYY-MM-DD, zero-padding month and day for ISO 8601 standard.
                when = f"{year}-{month:02d}-{day:02d}"
            except (ValueError, TypeError):
                # If parts are not valid integers, fallback to the default "N/A"
                pass
        
        # Extract review images
        # ...
```

**Explanation of Changes:**
1.  **`date_parts = safe_get(...)`**: We use your existing `safe_get` helper with the exact index path `(review, 2, 2, 0, 1, 21, 6, 8)` discovered from the Go project to retrieve the list of date components.
2.  **`when = "N/A"`**: We establish a safe default value.
3.  **`if isinstance(...) and len(...)`**: This is a crucial validation step. We ensure that we received a list and that it contains at least the three components (year, month, day) we need, preventing `IndexError`.
4.  **`try...except` block**: This adds robustness. It attempts to convert the date parts to integers. If any part is not a number (which is unlikely but possible), it catches the error and gracefully uses the default `when` value instead of crashing.
5.  **`f"{year}-{month:02d}-{day:02d}"`**: This f-string formats the date into a standard `YYYY-MM-DD` format. The `:02d` specifier ensures that single-digit months and days are padded with a leading zero (e.g., `5` becomes `05`), which is best practice for date strings.
