"""Debug script for parser logic"""
import cv2
import numpy as np
from bot.services.schedule_parser import ScheduleParser

# Override parse_image to print debug info
def debug_parse(self, image_bytes, queue="1.1"):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    # ... (Copying relevant parts of simple detection) ...
    # Let's use the exact same logic as service but print values
    
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 20))
    
    h_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)
    v_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, vertical_kernel, iterations=2)
    
    table_mask = cv2.addWeighted(h_lines, 0.5, v_lines, 0.5, 0.0)
    contours, _ = cv2.findContours(table_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    table_contour = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(table_contour)
    
    table_img = img[y:y+h, x:x+w]
    gray_table = cv2.cvtColor(table_img, cv2.COLOR_BGR2GRAY)
    _, thresh_table = cv2.threshold(gray_table, 200, 255, cv2.THRESH_BINARY_INV)
    
    h_lines_t = cv2.morphologyEx(thresh_table, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)
    row_sum = np.sum(h_lines_t, axis=1)
    row_coords = [i for i, val in enumerate(row_sum) if val > w * 0.5 * 255]
    
    clean_row_coords = []
    if row_coords:
        clean_row_coords.append(row_coords[0])
        for r in row_coords[1:]:
            if r - clean_row_coords[-1] > 10:
                clean_row_coords.append(r)
    
    print(f"Found {len(clean_row_coords)} rows (Expected ~13)")
    
    target_row_idx = 1
    if len(clean_row_coords) > target_row_idx + 1:
        row_top = clean_row_coords[target_row_idx]
        row_bottom = clean_row_coords[target_row_idx+1]
        row_height = row_bottom - row_top
        print(f"Target Row {target_row_idx} Height: {row_height}px (Top: {row_top})")
    else:
        print("❌ Not enough rows found!")
        return

    v_lines_t = cv2.morphologyEx(thresh_table, cv2.MORPH_OPEN, vertical_kernel, iterations=2)
    col_sum = np.sum(v_lines_t, axis=0)
    col_coords = [i for i, val in enumerate(col_sum) if val > h * 0.5 * 255]
    
    clean_col_coords = []
    if col_coords:
        clean_col_coords.append(col_coords[0])
        for c in col_coords[1:]:
            if c - clean_col_coords[-1] > 10:
                clean_col_coords.append(c)
                
    print(f"Found {len(clean_col_coords)} columns (Expected >26)")
    
    start_col_idx = 2
    if len(clean_col_coords) < 26: 
         start_col_idx = 0
         print("Warning: Low column count, starting at 0")

    print("\nVisualizing Geometry-Based Grid (Right 85% of table):")
    print("Legend: 🟦=Blue, ⬜=White")
    print("Row | " + "".join([f"{h%10}" for h in range(24)]))
    print("-" * 35)

    # Geometry assumptions
    # Header is roughly top 1/13th? Or explicit header row?
    # Let's try dividing height evenly into 13 rows (Header + 12 data)
    est_row_height = h / 13.0
    
    # Hours are roughly right 85% of width
    # hours_width = w * 0.85
    # hours_start_x = w * 0.15
    # Actually, from screenshot, columns 1&2 are wider. 
    # Let's try skipping first 15% pixels.
    hours_x_start = int(x + w * 0.145) # Tunable offset
    hours_width = int(w * 0.855)
    
    cell_w = hours_width / 24.0
    cell_h = est_row_height
    
    for r in range(13): # 0 is likely header, 1-12 are queues
        row_str = f"{r:<3} | "
        
        # Center Y for this row
        cy = int(y + (r * cell_h) + (cell_h * 0.5))
        
        for ch in range(24):
            # Center X for this hour
            cx = int(hours_x_start + (ch * cell_w) + (cell_w * 0.5))
            
            try:
                pixel = img[cy, cx] # Use original img, coords are global
                b, g, r_val = int(pixel[0]), int(pixel[1]), int(pixel[2])
                
                # Check Blue
                is_blue = (b > r_val + 20) and (b > g)
                is_white = (b > 200 and g > 200 and r_val > 200)
                
                if is_blue and not is_white:
                    row_str += "🟦"
                else:
                    row_str += "⬜"
            except:
                row_str += "❌"
        
        print(row_str)

local_image_path = r"C:/Users/VITASYK/.gemini/antigravity/brain/3970b995-369c-40d2-a9f6-bf685615fc1e/uploaded_media_1770141336439.png"

with open(local_image_path, "rb") as f:
    img_bytes = f.read()
    
# Monkey patch
ScheduleParser.debug_parse = debug_parse
parser = ScheduleParser()
parser.debug_parse(img_bytes)
