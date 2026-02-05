"""Simple test to check what hours the parser detects from uploaded image"""
import cv2
import sys

# Path to your uploaded schedule image
img_path = r"C:/Users/VITASYK/.gemini/antigravity/brain/3970b995-369c-40d2-a9f6-bf685615fc1e/uploaded_media_1770145870894.png"

# Read image
with open(img_path, "rb") as f:
    img_bytes = f.read()

# Import parser
sys.path.insert(0, r"C:\Users\VITASYK\ANTIGRAVITY\GenaBot")
from bot.services.schedule_parser import ScheduleParser

parser = ScheduleParser()
hours = parser.parse_image(img_bytes, queue="1.1")

print(f"Detected hours for queue 1.1: {hours}")
print(f"Total: {len(hours)} hours")

# Analyze blocks
if hours:
    blocks = []
    block_start = hours[0]
    block_end = hours[0]
    
    for h in hours[1:]:
        if h == block_end + 1:
            block_end = h
        else:
            blocks.append((block_start, block_end + 1))
            block_start = h
            block_end = h
    blocks.append((block_start, block_end + 1))
    
    print(f"\nDetected blocks:")
    for start, end in blocks:
        print(f"  {start:02d}:00 - {end:02d}:00")
