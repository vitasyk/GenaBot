"""
Manual calibration tool to find exact pixel coordinates for queue 1.1 row
and hour columns in the schedule image
"""
import cv2
import numpy as np

# Load the image
img_path = r"C:/Users/VITASYK/.gemini/antigravity/brain/3970b995-369c-40d2-a9f6-bf685615fc1e/uploaded_media_1770145870894.png"
img = cv2.imread(img_path)

# Expected hours for queue 1.1 based on visual inspection
expected_1_1 = [0, 3, 4, 5, 6, 11, 12, 14, 18, 19, 21, 22, 23]

print("Image shape:", img.shape)
h, w = img.shape[:2]

# Step 1: Find table region
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
_, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
table_contour = max(contours, key=cv2.contourArea)
x, y, w_table, h_table = cv2.boundingRect(table_contour)

print(f"\nTable bounds: x={x}, y={y}, w={w_table}, h={h_table}")

# Crop to table
crop = img[y:y+h_table, x:x+w_table]
crop_h, crop_w = crop.shape[:2]

print(f"Cropped table size: {crop_w} x {crop_h}")

# Step 2: Sample queue 1.1 row at different Y positions to find the right one
# Try Y positions from 40% to 60% of table height
print("\n=== Testing different Y positions for Queue 1.1 ===")

for y_pct in range(40, 61, 2):
    y_test = int(crop_h * y_pct / 100.0)
    
    # Sample pixels across the row using geometric column estimate
    hour_start_x = int(crop_w * 0.25)
    hour_width = int(crop_w * 0.68)
    stride = hour_width / 24.0
    
    detected_hours = []
    for h_idx in range(24):
        x_sample = int(hour_start_x + (h_idx + 0.5) * stride)
        if x_sample >= crop_w:
            continue
            
        pixel = crop[y_test, x_sample]
        b, g, r = int(pixel[0]), int(pixel[1]), int(pixel[2])
        
        # Blue check
        is_blue = (b > r + 30) and (b > g)
        is_white = (b > 200 and g > 200 and r > 200)
        
        if is_blue and not is_white:
            detected_hours.append(h_idx)
    
    # Compare with expected
    matches = len(set(detected_hours) & set(expected_1_1))
    total_expected = len(expected_1_1)
    
    if matches >= total_expected * 0.7:  # 70% match threshold
        print(f"Y={y_pct}%: Found {detected_hours}, matches={matches}/{total_expected}")

print("\n=== Testing different X start positions ===")
# Fix Y at best estimate (let's try 48%)
y_test = int(crop_h * 0.48)

for x_start_pct in range(22, 28):
    hour_start_x = int(crop_w * x_start_pct / 100.0)
    hour_width = int(crop_w * 0.68)
    stride = hour_width / 24.0
    
    detected_hours = []
    for h_idx in range(24):
        x_sample = int(hour_start_x + (h_idx + 0.5) * stride)
        if x_sample >= crop_w:
            continue
            
        pixel = crop[y_test, x_sample]
        b, g, r = int(pixel[0]), int(pixel[1]), int(pixel[2])
        
        is_blue = (b > r + 30) and (b > g)
        is_white = (b > 200 and g > 200 and r > 200)
        
        if is_blue and not is_white:
            detected_hours.append(h_idx)
    
    matches = len(set(detected_hours) & set(expected_1_1))
    total_expected = len(expected_1_1)
    
    if matches >= total_expected * 0.6:
        print(f"X_start={x_start_pct}%: Found {detected_hours}, matches={matches}/{total_expected}")
