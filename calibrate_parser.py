"""Calibrate column detection by scanning pixel intensity"""
import cv2
import numpy as np
import logging

def calibrate():
    local_image_path = r"C:/Users/VITASYK/.gemini/antigravity/brain/3970b995-369c-40d2-a9f6-bf685615fc1e/uploaded_media_1770141336439.png"
    
    with open(local_image_path, "rb") as f:
        img_bytes = f.read()
        
    nparr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    h, w = gray.shape
    
    # 1. Find Table Box first (to avoid scraping text outside)
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    table_contour = max(contours, key=cv2.contourArea)
    x, y, table_w, table_h = cv2.boundingRect(table_contour)
    
    print(f"Table box: x={x}, y={y}, w={table_w}, h={table_h}")
    
    # Crop to proper table
    crop = gray[y:y+table_h, x:x+table_w]
    
    # 2. Grid Lines via Morphology
    # Invert (Lines become white on black)
    _, thresh = cv2.threshold(crop, 200, 255, cv2.THRESH_BINARY_INV)
    
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 20))
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    
    v_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, vertical_kernel, iterations=2)
    h_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)
    
    # Project Vertical
    col_sum = np.sum(v_lines, axis=0) # Sum of white pixels in each col
    
    # Find peaks (columns)
    # Threshold: height * 0.5 * 255 (at least 50% of column height is line)
    col_coords = [i for i, val in enumerate(col_sum) if val > table_h * 0.3 * 255]
    
    # Clean duplicates
    clean_cols = []
    if col_coords:
        clean_cols.append(col_coords[0])
        for c in col_coords[1:]:
            if c - clean_cols[-1] > 10:
                clean_cols.append(c)
                
    print(f"Found {len(clean_cols)} vertical lines: {clean_cols}")
    
    if len(clean_cols) < 25:
        print("❌ Not enough columns!")
        # Fallback: Geometry based on edges
        return 

    # Assume last 25 lines are the hours grid (24 intervals)
    hours_lines = clean_cols[-25:]
    
    print("\nCalculated Hour Columns Centers:")
    hour_centers = []
    for i in range(24):
        x1 = hours_lines[i]
        x2 = hours_lines[i+1]
        center = int((x1 + x2) / 2)
        hour_centers.append(center)
        print(f"Hour {i}: {center}")
        
    # Project Horizontal
    row_sum = np.sum(h_lines, axis=1)
    row_coords = [i for i, val in enumerate(row_sum) if val > table_w * 0.3 * 255]
    
    clean_rows = []
    if row_coords:
        clean_rows.append(row_coords[0])
        for r in row_coords[1:]:
            if r - clean_rows[-1] > 5:
                clean_rows.append(r)
                
    print(f"\nFound {len(clean_rows)} horizontal lines: {clean_rows}")
    
    # Analyze alignment
    # If we have e.g. 17 lines -> 16 rows.
    # Row 0 is header. Row 1 is 1.1?
    
    print("\nSampling colors at centers:")
    print("Row | " + "".join([f"{h%10}" for h in range(24)]))
    
    for r_idx in range(len(clean_rows)-1):
        y1 = clean_rows[r_idx]
        y2 = clean_rows[r_idx+1]
        cy = int((y1+y2)/2)
        
        row_str = f"{r_idx:<3} | "
        
        for h_idx in range(24):
            cx = hour_centers[h_idx]
            
            # Sample from crop (original color)
            # Need strict coordinates relative to crop
            pixel = img[y+cy, x+cx]
            b, g, r_v = int(pixel[0]), int(pixel[1]), int(pixel[2])
            
            is_blue = (b > r_v + 20 and b > g)
            is_white = (b > 200 and g > 200 and r_v > 200)
            
            if is_blue and not is_white: row_str += "🟦"
            else: row_str += "⬜"
            
        print(row_str)

if __name__ == "__main__":
    calibrate()
