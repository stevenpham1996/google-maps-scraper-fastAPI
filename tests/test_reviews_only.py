import asyncio
import json
import httpx
from gmaps_scraper_server.main_api import app
from asgi_lifespan import LifespanManager

async def test_reviews_endpoint():
    print("Starting integration test for /reviews endpoint...")
    
    # URLs for testing: one full ESB URL, one short link for Starbucks ESB
    test_urls = [
        "https://www.google.com/maps/place/Starbucks/@40.7484405,-73.9856644,17z/data=!3m1!4b1!4m6!3m5!1s0x89c259a9b3117469:0xd134e199a405a163!8m2!3d40.7484405!4d-73.9856644!16s%2Fg%2F1td0v_19?entry=ttu",
        "https://maps.app.goo.gl/ViRpRQyv56MzQHsXA"
    ]
    
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            print(f"Sending request to /reviews with {len(test_urls)} URLs...")
            response = await client.post("/reviews", json={"urls": test_urls, "lang": "en"})
            
            if response.status_code == 200:
                results = response.json()
                print(f"Successfully received response with {len(results)} results.")
                
                for res in results:
                    url = res.get("link")
                    status = res.get("status")
                    reviews = res.get("user_reviews", [])
                    print(f"URL: {url}")
                    print(f"Status: {status}")
                    print(f"Reviews count: {len(reviews)}")
                    
                    if reviews:
                        print(f"Sample review from {reviews[0].get('name')}:")
                        print(f"  Rating: {reviews[0].get('rating')}")
                        print(f"  Description: {reviews[0].get('description')[:100]}...")
                    else:
                        print("No reviews found for this URL.")
            else:
                print(f"Request failed with status {response.status_code}")
                print(response.text)

if __name__ == "__main__":
    try:
        import asgi_lifespan
        import httpx
    except ImportError:
        print("Required libraries (httpx, asgi-lifespan) not found. Please install them.")
        exit(1)
        
    asyncio.run(test_reviews_endpoint())
