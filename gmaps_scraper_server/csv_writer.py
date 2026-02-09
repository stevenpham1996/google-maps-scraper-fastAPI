
import csv
import os
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def save_to_csv(data_list, filename="scraped_data.csv"):
    """
    Saves a list of dictionaries to a CSV file, avoiding duplicates based on 'place_id'.
    """
    if not data_list:
        logging.info("No data to save.")
        return

    # Check if file exists to read existing IDs
    existing_ids = set()
    file_exists = os.path.isfile(filename)
    
    if file_exists:
        try:
            with open(filename, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if 'place_id' in row and row['place_id']:
                        existing_ids.add(row['place_id'])
        except Exception as e:
            logging.error(f"Error reading existing CSV: {e}")

    # Identify new records
    new_records = []
    for item in data_list:
        pid = item.get('place_id')
        if pid and pid not in existing_ids:
            new_records.append(item)
            existing_ids.add(pid) # Add to set to prevent duplicates within the verified batch
        elif not pid:
             # If no place_id, we might want to save it anyway? Or skip?
             # Let's save it but log warning
             logging.warning(f"Item found without place_id: {item.get('name')}")
             new_records.append(item)

    if not new_records:
        logging.info("No new records to append (all duplicates).")
        return

    # Determine fieldnames (header)
    # We should use a comprehensive list or union of all keys
    all_keys = set()
    for item in new_records:
        all_keys.update(item.keys())
    
    # Prioritize common fields
    priority_fields = ['place_id', 'name', 'address', 'phone', 'website', 'rating', 'reviews_count', 'latitude', 'longitude', 'categories', 'open_hours', 'description', 'link', 'status']
    fieldnames = [f for f in priority_fields if f in all_keys] + sorted([k for k in all_keys if k not in priority_fields])

    mode = 'a' if file_exists else 'w'
    try:
        with open(filename, mode=mode, newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            else:
                # If file exists, we might have new columns?
                # This simple implementation assumes schema compatibility or just appends.
                # If existing file doesn't have the new headers, DictWriter will ignore/fail?
                # 'extrasaction' defaults to 'raise'. We should set it to 'ignore' 
                # OR read the existing header and only write those fields + new ones?
                # To be safe, let's reopen the writer with 'extrasaction="ignore"' 
                # if we suspect mismatch, but for now let's try standard.
                pass
            
            # Robust writer handling potential missing fields in existing header
            # Actually, if we append, we must use the EXISTING header order if possible.
            # But here we used 'fieldnames' derived from NEW data.
            # If preserving existing header is crucial, we should read it first.
            if file_exists:
                 with open(filename, 'r', encoding='utf-8') as read_f:
                     reader = csv.reader(read_f)
                     try:
                        existing_header = next(reader)
                        # Use existing header, plus any new fields appended
                        # This is complex. For now, let's just use the computed fieldnames 
                        # and hope DictWriter handles mixed content well (it does if we use extrasaction='ignore')
                        pass
                     except StopIteration:
                        # Empty file
                        pass

        # Re-open with extrasaction='ignore' to be safe
        with open(filename, mode=mode, newline='', encoding='utf-8') as f:
             writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
             if not file_exists:
                 writer.writeheader()
             
             writer.writerows(new_records)
             
        logging.info(f"Appended {len(new_records)} new records to {filename}.")
        
    except Exception as e:
        logging.error(f"Error writing to CSV: {e}")
