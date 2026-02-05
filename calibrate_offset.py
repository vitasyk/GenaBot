"""Calibrate column offset by sliding window"""
import cv2
import numpy as np

def calibrate():
    local_path = "C:/Users/VITASYK/.gemini/antigravity/brain/3970b995-369c-40d2-a9f6-bf685615fc1e/uploaded_media_1770145870894.png"
    
    with open(local_path, "rb") as f:
        img_bytes = f.read()
    
    nparr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    table_contour = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(table_contour)
    
    crop_gray = gray[y:y+h, x:x+w]
    _, thresh_crop = cv2.threshold(crop_gray, 200, 255, cv2.THRESH_BINARY_INV)
    
    # Text-based target pattern (Queue 1.1)
    # 00-04 (4h) Blue -> 1
    # 04-07 (3h) White -> 0
    target_pattern = [1,1,1,1, 0,0,0, 1,1,1,1, 0,0,0,0,0, 1,1,1,1, 0,0,0,0]
    
    # 1. Get all vertical lines
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 20))
    v_lines = cv2.morphologyEx(thresh_crop, cv2.MORPH_OPEN, vertical_kernel, iterations=2)
    col_sum = np.sum(v_lines, axis=0)
    col_coords = [i for i, val in enumerate(col_sum) if val > h * 0.2 * 255] # Low threshold
    
    clean_cols = []
    if col_coords:
        clean_cols.append(col_coords[0])
        for c in col_coords[1:]:
            if c - clean_cols[-1] > 5:
                clean_cols.append(c)
                
    print(f"Total detected columns lines: {len(clean_cols)}")
    
    # 2. Get Rows
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    h_lines = cv2.morphologyEx(thresh_crop, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)
    row_sum = np.sum(h_lines, axis=1)
    row_coords = [i for i, val in enumerate(row_sum) if val > w * 0.5 * 255]
    
    clean_rows = []
    if row_coords:
        clean_rows.append(row_coords[0])
        for r in row_coords[1:]:
            if r - clean_rows[-1] > 10:
                clean_rows.append(r)

    # 3. Slide window
    best_offset = -1
    best_score = 0
    best_row_idx = -1
    
    # We need 25 lines to define 24 columns
    # Slide across all possible start indices
    max_start = len(clean_cols) - 25
    
    print(f"Sliding window from 0 to {max_start}...")
    
    for r_idx in range(len(clean_rows)-1):
        y1 = clean_rows[r_idx]
        y2 = clean_rows[r_idx+1]
        cy = int((y1+y2)/2)
        
        if (y2-y1) < 15: continue
        
        for start_idx in range(max_start + 1):
            window_lines = clean_cols[start_idx : start_idx+25]
            
            score = 0
            for i in range(24):
                cx = int((window_lines[i] + window_lines[i+1])/2)
                
                try:
                    pixel = img[y+cy, x+cx]
                    b, g, r_v = int(pixel[0]), int(pixel[1]), int(pixel[2])
                    
                    is_blue = (b > r_v + 30 and b > g)
                    is_white = (b > 200 and g > 200 and r_v > 200)
                    
                    val = 1 if (is_blue and not is_white) else 0
                    if val == target_pattern[i]: score += 1
                except: pass
            
            if score > best_score:
                best_score = score
                best_offset = start_idx
                best_row_idx = r_idx
                
                if score == 24: break
        if best_score == 24: break
        
    print(f"\nOptimization Result:")
    print(f"Best Score: {best_score}/24")
    print(f"Best Row Index: {best_row_idx}")
    print(f"Best Column Offset: {-1 * (len(clean_cols) - 25 - best_offset)} (from end) or {best_offset} (from start)")
    
    # Verify exact match
    if best_score == 24:
        print("✅ Found exact alignment!")
    else:
        print("❌ Could not align perfectly.")

if __name__ == "__main__":
    calibrate()
