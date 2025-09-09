import os
import multiprocessing

# Server socket
bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")

# Worker processes
# The recommendation is (2 * number_of_cores) + 1.
# However, given that each worker might run a heavy browser instance,
# we'll start with a more conservative default of the number of cores.
# This can be overridden with the GUNICORN_WORKERS environment variable.
default_workers = multiprocessing.cpu_count()
workers = int(os.environ.get("GUNICORN_WORKERS", default_workers))

# Worker class
# Use uvicorn's worker class for asyncio compatibility.
worker_class = "uvicorn.workers.UvicornWorker"

# Worker timeout
# Long timeout to allow for long-running scraping tasks.
# Consider adjusting based on typical scrape times.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 120))

# Logging
accesslog = "-"
errorlog = "-"
