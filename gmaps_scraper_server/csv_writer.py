
import csv

import os

import json

import logging

import sys

import time

import fcntl

import ast



# Configure logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')



class FileLock:

    """

    A cross-platform file locking mechanism using fcntl (Linux/Mac) or msvcrt (Windows).

    Uses a separate lock file to avoid interfering with the data file.

    """

    def __init__(self, filename, timeout=10):

        self.lockfile = filename + ".lock"

        self.timeout = timeout

        self.fd = None



    def __enter__(self):

        start_time = time.time()

        # Open the lock file in append mode to avoid truncating if we ever wanted to read it,

        # but 'w' is fine for a pure lock file.

        self.fd = open(self.lockfile, 'w')

        while True:

            try:

                if sys.platform == 'win32':

                    import msvcrt

                    # Lock the first byte

                    msvcrt.locking(self.fd.fileno(), msvcrt.LK_NBLCK, 1)

                else:

                    # Exclusive, non-blocking lock

                    fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

                return self

            except (IOError, OSError):

                if time.time() - start_time > self.timeout:

                    raise Exception(f"Could not acquire lock on {self.lockfile}")

                time.sleep(0.1)



    def __exit__(self, exc_type, exc_val, exc_tb):

        if self.fd:

            try:

                if sys.platform == 'win32':

                    import msvcrt

                    msvcrt.locking(self.fd.fileno(), msvcrt.LK_UNLCK, 1)

                else:

                    fcntl.flock(self.fd, fcntl.LOCK_UN)

            except Exception as e:

                logging.error(f"Error releasing lock: {e}")

            finally:

                self.fd.close()



def calculate_completeness_score(record):

    """

    Calculates a weighted score based on field importance.

    """

    score = 0

    # Weights for different fields

    weights = {

        'place_id': 10,

        'name': 5,

        'address': 5,

        'phone': 3,

        'website': 3,

        'rating': 3,

        'reviews_count': 3,

        'latitude': 5,

        'longitude': 5,

        'categories': 3,

        'open_hours': 10,  # Dynamic data, high value

        'thumbnail': 2,

        'images': 5,       # Dynamic data

        'about': 3,

        'attributes': 3,

        'user_reviews': 20, # Very high value, often missed

        'price_range': 2,

        'description': 2

    }

    

    for key, weight in weights.items():

        val = record.get(key)

        if val:

            if isinstance(val, (list, dict)):

                if len(val) > 0:

                    score += weight

                    # Bonus for quantity in list fields

                    if isinstance(val, list):

                        score += min(len(val), 10) # Up to 10 bonus points

            elif isinstance(val, str):

                if val.strip() and val.lower() not in ['null', 'none', '']:

                    score += weight

            elif isinstance(val, (int, float)):

                 score += weight

    return score



def parse_complex_field(value):



    """Parses stringified lists/dicts from CSV (e.g. from str() or JSON)."""



    if not value or not isinstance(value, str):



        return value



    



    stripped = value.strip()



    if ((stripped.startswith('[') and stripped.endswith(']')) or 



        (stripped.startswith('{') and stripped.endswith('}'))):



        try:



            return ast.literal_eval(stripped)



        except (ValueError, SyntaxError):



            try:



                return json.loads(stripped)



            except:



                return value



    return value



def merge_records(old, new):

    """

    Deep merges two records. new_record generally overrides old, 

    BUT for lists (reviews, images), we try to keep the 'better' one.

    """

    merged = old.copy()

    

    for key, new_val in new.items():

        old_val = old.get(key)

        

        # If new value is empty, keep old

        if not new_val:

            continue

            

        # If old value is empty, take new

        if not old_val:

            merged[key] = new_val

            continue

            

        # Conflict Resolution

        if key == 'user_reviews':

            # Keep the one with MORE reviews

            if isinstance(new_val, list) and isinstance(old_val, list):

                if len(new_val) >= len(old_val):

                     merged[key] = new_val

                # Else keep old (it has more reviews)

            elif isinstance(new_val, list) and not isinstance(old_val, list):

                merged[key] = new_val

            continue

            

        if key == 'open_hours':

             # Prefer dict over empty or smaller dict

             if isinstance(new_val, dict) and isinstance(old_val, dict):

                 if len(new_val) >= len(old_val):

                     merged[key] = new_val

             elif isinstance(new_val, dict):

                 merged[key] = new_val

             continue

        

        # For reviews_count, ignore placeholder '10112' if old value is valid

        if key == 'reviews_count':

            if str(new_val) == '10112' and str(old_val) != '10112':

                continue



        # Default: New overwrites Old (assuming correction/update)

        merged[key] = new_val

        

    return merged



def save_to_csv(data_list, filename="scraped_data.csv"):

    """

    Saves a list of dictionaries to a CSV file, merging with existing data.

    Thread-safe implementation using FileLock.

    """

    if not data_list:

        logging.info("No data to save.")

        return



    try:

        with FileLock(filename):

            records_dict = {}

            file_exists = os.path.isfile(filename)

            

            # 1. Read existing data

            if file_exists:

                try:

                    with open(filename, mode='r', encoding='utf-8') as f:

                        reader = csv.DictReader(f)

                        for row in reader:

                            pid = row.get('place_id')

                            if pid:

                                # Parse complex fields back to objects for merging

                                parsed_row = {}

                                for k, v in row.items():

                                    parsed_row[k] = parse_complex_field(v)

                                records_dict[pid] = parsed_row

                except Exception as e:

                    logging.error(f"Error reading existing CSV: {e}")



            # 2. Merge new data

            new_count = 0

            updated_count = 0

            

            for item in data_list:

                pid = item.get('place_id')

                if not pid:

                     logging.warning(f"Item found without place_id: {item.get('name')}")

                     # If no ID, we can't reliably merge. Strategy: Append if not exact dupe?

                     # For now, simplistic approach: require place_id

                     continue



                if pid in records_dict:

                    # Merge

                    old_record = records_dict[pid]

                    merged_record = merge_records(old_record, item)

                    records_dict[pid] = merged_record

                    updated_count += 1

                else:

                    # New

                    records_dict[pid] = item

                    new_count += 1



            if updated_count == 0 and new_count == 0:

                logging.info("No changes to save.")

                return



            # 3. Write all data back

            # Determine fieldnames

            all_keys = set()

            for record in records_dict.values():

                all_keys.update(record.keys())

            

            priority_fields = ['place_id', 'name', 'address', 'phone', 'website', 'rating', 'reviews_count', 'latitude', 'longitude', 'categories', 'open_hours', 'description', 'link', 'status']

            fieldnames = [f for f in priority_fields if f in all_keys] + sorted([k for k in all_keys if k not in priority_fields])



            try:

                with open(filename, mode='w', newline='', encoding='utf-8') as f:

                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')

                    writer.writeheader()

                    writer.writerows(records_dict.values())

                     

                logging.info(f"Saved {len(records_dict)} records to {filename} ({new_count} new, {updated_count} merged/updated).")

                

            except Exception as e:

                logging.error(f"Error writing to CSV: {e}")



    except Exception as e:

        logging.error(f"Failed to acquire lock or write data: {e}")



