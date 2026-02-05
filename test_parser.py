"""Test script for ScheduleParser"""
import asyncio
import cv2
import logging
from bot.services.schedule_parser import ScheduleParser
from bot.config import config

# Configure logging
logging.basicConfig(level=logging.INFO)

async def test_parser():
    parser = ScheduleParser()
    
    # Path to the image user uploaded (Use absolute path from metadata)
    # C:/Users/VITASYK/.gemini/antigravity/brain/3970b995-369c-40d2-a9f6-bf685615fc1e/uploaded_media_1770141336439.png
    local_image_path = r"C:/Users/VITASYK/.gemini/antigravity/brain/3970b995-369c-40d2-a9f6-bf685615fc1e/uploaded_media_1770145870894.png"
    
    print("\n=== TEST 1: Parsing Local Image (Known Data) ===")
    try:
        # Read file as bytes
        with open(local_image_path, "rb") as f:
            img_bytes = f.read()
            
        hours = parser.parse_image(img_bytes, queue="1.1")
        print(f"Detected Outage Hours: {hours}")
        print(f"Total Hours: {len(hours)}")
        print(f"Expected: 12 hours (0-3, 7-10, 16-19)")
        
    except FileNotFoundError:
        print(f"⚠️ Local image not found at {local_image_path}")
    except Exception as e:
        print(f"❌ Local parsing failed: {e}")

    print("\n=== TEST 2: Fetching LIVE Image from HOE.com.ua ===")
    try:
        hours = await parser.get_today_outages(queue="1.1")
        if hours:
            print(f"✅ Fetched & Parsed Successfully!")
            print(f"Image URL: {parser.last_image_url}")
            print(f"Detected Outage Hours: {hours}")
            print(f"Total Hours: {len(hours)}")
        else:
            print("⚠️ Parsed 0 hours or failed to fetch (Site might have no interruptions today)")
            
    except Exception as e:
        print(f"❌ Live fetch failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_parser())
