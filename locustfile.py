
from locust import HttpUser, task, between
import random

class ScraperUser(HttpUser):
    wait_time = between(1, 5)  # Wait 1-5 seconds between tasks

    @task
    def scrape_task(self):
        # List of sample queries to test with
        queries = [
            "restaurants in New York",
            "cafes in Paris",
            "hotels in London",
            "tourist attractions in Tokyo",
            "gyms in Los Angeles"
        ]
        
        # Pick a random query
        random_query = random.choice(queries)
        
        self.client.get(
            f"/scrape-get?query={random_query}&max_places=10&extract_reviews=False",
            name="/scrape-get?query=[query]" # Group all requests under one name in the UI
        )
