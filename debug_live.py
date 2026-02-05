"""Debug script to inspect LIVE image parsing (Mirrors ScheduleParser logic)"""
import asyncio
import cv2
import numpy as np
import aiohttp
import ssl
import certifi
import re
from datetime import datetime
from bot.config import config

async def download_and_debug():
    # TEST IMAGE from User
    local_path = "C:/Users/VITASYK/.gemini/antigravity/brain/3970b995-369c-40d2-a9f6-bf685615fc1e/uploaded_media_1770145870894.png"
    print(f"Analyzing Local Image: {local_path}")
    
    with open(local_path, "rb") as f:
        img_bytes = f.read()

    nparr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    print("\n--- Analysing Image ---")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    table_contour = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(table_contour)
    print(f"Table found: x={x}, y={y}, w={w}, h={h}")
    
    crop_gray = gray[y:y+h, x:x+w]
    _, thresh_crop = cv2.threshold(crop_gray, 200, 255, cv2.THRESH_BINARY_INV)
    
    # --- LOGIC FROM SERVICE STARTS HERE ---
    
    # Find vertical lines
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 20))
    v_lines = cv2.morphologyEx(thresh_crop, cv2.MORPH_OPEN, vertical_kernel, iterations=2)
    col_sum = np.sum(v_lines, axis=0)
    col_coords = [i for i, val in enumerate(col_sum) if val > h * 0.2 * 255]
    
    clean_cols = []
    if col_coords:
        clean_cols.append(col_coords[0])
        for c in col_coords[1:]:
            if c - clean_cols[-1] > 10:
                clean_cols.append(c)
                
    # Find horizontal lines
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 1))
    h_lines = cv2.morphologyEx(thresh_crop, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)
    # Lower threshold to 5% of width
    row_sum = np.sum(h_lines, axis=1)
    row_coords = [i for i, val in enumerate(row_sum) if val > w * 0.05 * 255]
    
    clean_rows = []
    if row_coords:
        clean_rows.append(row_coords[0])
        for r in row_coords[1:]:
            if r - clean_rows[-1] > 5:
                clean_rows.append(r)

    # 4. Filter Rows & Fallback
    header_height_threshold = h / 40.0 # ~10px
    final_data_rows = []
    
    for r_idx in range(len(clean_rows)-1):
        y1 = clean_rows[r_idx]
        y2 = clean_rows[r_idx+1]
        h_px = y2 - y1
        if h_px > header_height_threshold and h_px < h * 0.2:
            final_data_rows.append((y1, y2))
            
    if len(final_data_rows) < 5:
         print(f"Weak row detection ({len(final_data_rows)} rows), using dynamic geometry")
         # 1. Estimate Row Height
         gaps = []
         for i in range(len(clean_rows)-1):
             g = clean_rows[i+1] - clean_rows[i]
             if g > 15 and g < h * 0.2:
                 gaps.append(g)
         if gaps: row_h = np.median(gaps)
         else: row_h = (h * 0.65) / 12.0
         
         # 2. Reconstruct Grid
         start_y = int(h * 0.45) # Default
         for r in clean_rows:
             if r > h * 0.30: # If we find a line reasonably down
                 start_y = r
                 break
                 
         print(f"Using StartY={start_y}, RowH={row_h}")
         
         final_data_rows = []
         for i in range(12):
             y1 = int(start_y + i * row_h)
             y2 = int(start_y + (i+1) * row_h)
             if y2 < h: final_data_rows.append((y1, y2))

    # Columns: Use last 25 lines
    if len(clean_cols) < 25:
         print("Not enough columns, using geometry fallback")
         hour_width = w * 0.77
         hour_start_x = w * 0.23
         stride = hour_width / 24.0
         hours_lines = [int(hour_start_x + stride*i) for i in range(25)]
    else:
         hours_lines = clean_cols[-25:]

    # VISUALIZE
    print("\nVisualizing Final Grid:")
    for idx, (y1, y2) in enumerate(final_data_rows):
        cy = int((y1+y2)/2)
        row_str = f"{idx:<3} | "
        
        for h_idx in range(24):
             if h_idx >= len(hours_lines)-1: break
             x1 = hours_lines[h_idx]
             x2 = hours_lines[h_idx+1]
             cx = int((x1+x2)/2)
             
             try:
                 pixel = img[y+cy, x+cx]
                 b, g, r_v = int(pixel[0]), int(pixel[1]), int(pixel[2])
                 
                 is_blue = (b > r_v + 30) and (b > g)
                 is_white = (b > 200 and g > 200 and r_v > 200)
                 
                 if is_blue and not is_white: row_str += "🟦 "
                 else: row_str += "⬜ "
             except:
                 row_str += "XX "
                 
        print(row_str + f"(Y={y1}-{y2})")

if __name__ == "__main__":
    asyncio.run(download_and_debug())
