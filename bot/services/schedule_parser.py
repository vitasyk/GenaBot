import cv2
import numpy as np
import aiohttp
import logging
import re
from typing import List, Optional
from datetime import datetime, date, time, timedelta
from bot.config import config
import ssl
import certifi

class ScheduleParser:
    """Parses power outage schedules from HOE.com.ua images"""
    
    def __init__(self):
        self.last_image_url = None
        
    async def _fetch_available_schedules(self) -> List[tuple[datetime, bytes]]:
        """Scrape site to find and download schedules for today and tomorrow"""
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            schedules = []
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(config.HOE_SCHEDULE_URL) as response:
                    if response.status != 200:
                        logging.error(f"Failed to load HOE page: {response.status}")
                        return []
                    html = await response.text()
                
                # Find all img tags to check src and alt
                img_tags = re.findall(r'<img[^>]+>', html)
                
                today = datetime.now().date()
                tomorrow = today + timedelta(days=1)
                
                # Priority: Look for today, then tomorrow
                # We want to find the BEST match for each date
                # Filenames often contain dates like 20260205 or 05.02.26
                
                dates_to_find = {
                    today: [today.strftime("%Y%m%d"), today.strftime("%d.%m.%y"), today.strftime("%d.%m.%Y")],
                    tomorrow: [tomorrow.strftime("%Y%m%d"), tomorrow.strftime("%d.%m.%y"), tomorrow.strftime("%d.%m.%Y")]
                }
                
                found_data = {} # date -> (url, bytes)

                for img_tag in img_tags:
                    src_match = re.search(r'src="(/Content/Uploads/[^"]+\.png)"', img_tag)
                    if not src_match:
                        continue
                        
                    url = src_match.group(1)
                    alt_match = re.search(r'alt="([^"]+)"', img_tag)
                    alt_text = alt_match.group(1) if alt_match else ""
                    
                    full_url = f"https://hoe.com.ua{url}"
                    
                    # Search priority: Alt text > URL (Filename)
                    # Because filename often contains upload date (e.g. 20260205) while content is for next day (06.02)
                    
                    assigned = False
                    
                    # 1. Check Alt Text first
                    if alt_text:
                        lower_alt = alt_text.lower()
                        for d_obj, formats in dates_to_find.items():
                            if d_obj in found_data: continue
                            
                            if any(f in lower_alt for f in formats):
                                # Found match in Alt
                                async with session.get(full_url) as img_resp:
                                    if img_resp.status == 200:
                                        img_bytes = await img_resp.read()
                                        found_data[d_obj] = (full_url, img_bytes)
                                        self.last_image_url = full_url
                                        logging.info(f"Fetched schedule for {d_obj} (by Alt): {full_url}")
                                        assigned = True
                                        break
                    
                    if assigned: continue

                    # 2. Check URL if no Alt match
                    lower_url = url.lower()
                    for d_obj, formats in dates_to_find.items():
                        if d_obj in found_data: continue
                        
                        if any(f in lower_url for f in formats):
                            # Found match in URL
                            async with session.get(full_url) as img_resp:
                                if img_resp.status == 200:
                                    img_bytes = await img_resp.read()
                                    found_data[d_obj] = (full_url, img_bytes)
                                    self.last_image_url = full_url
                                    logging.info(f"Fetched schedule for {d_obj} (by URL): {full_url}")
                                    assigned = True
                                    break
                
                # Convert back to list
                for d, (u, b) in found_data.items():
                    schedules.append((datetime.combine(d, time.min), b))
                
                # Fallback: if absolutely nothing found for today, 
                # just pick the first Uploads image as it's likely the current one
                if not schedules:
                    first_img = re.search(r'src="(/Content/Uploads/[^"]+\.png)"', html)
                    if first_img:
                        url = first_img.group(1)
                        full_url = f"https://hoe.com.ua{url}"
                        async with session.get(full_url) as img_resp:
                            if img_resp.status == 200:
                                logging.info(f"Fallback: Fetching first available image {full_url}")
                                schedules.append((datetime.combine(today, time.min), await img_resp.read()))

            return schedules
        except Exception as e:
            logging.error(f"Error fetching schedules: {e}")
            return []

    async def get_schedules_data(self, queue: str = "1.1") -> List[tuple[date, List[int], bytes]]:
        """
        Fetches and parses schedules, returning a list of (date, hours_list, image_bytes) tuples.
        """
        schedules = await self._fetch_available_schedules()
        results = []
        
        for d_obj, img_bytes in schedules:
            hours = self.parse_image(img_bytes, queue=queue)
            if hours:
                results.append((d_obj, hours, img_bytes))
        
        return results

    async def get_outage_timeline(self, queue: str = "1.1") -> List[datetime]:
        """
        Returns a list of datetime objects (on the hour) when outages are scheduled,
        merged from today and tomorrow. (Kept for backward compatibility)
        """
        data = await self.get_schedules_data(queue=queue)
        timeline = []
        
        for d_obj, hours, img_bytes in data:
            for h in hours:
                dt = datetime.combine(d_obj, time(h, 0))
                timeline.append(dt)
        
        return sorted(list(set(timeline)))

    async def fetch_latest_schedule_image(self) -> Optional[bytes]:
        """Deprecated? Keep for backward compatibility but use get_outage_timeline instead."""
        schedules = await self._fetch_available_schedules()
        if not schedules: return None
        # Return today's if available, otherwise first found
        today = datetime.now().date()
        for d, b in schedules:
            if d == today: return b
        return schedules[0][1]

    def parse_image(self, image_bytes: bytes, queue: str = "1.1") -> List[int]:
        """
        Process image with OpenCV to find outage hours for queue
        Returns list of hours (0-23) where outage is detected (blue color)
        """
        try:
            # Convert bytes to cv2 image
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if img is None:
                raise ValueError("Failed to decode image")

            # 1. Isolate Table
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if not contours:
                raise ValueError("No contours found")
                
            table_contour = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(table_contour)
            
            crop_gray = gray[y:y+h, x:x+w]
            crop_color = img[y:y+h, x:x+w]
            
            # 2. Grid Detection (Morphology)
            # Find vertical lines
            _, thresh_crop = cv2.threshold(crop_gray, 200, 255, cv2.THRESH_BINARY_INV)
            vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 20))
            v_lines = cv2.morphologyEx(thresh_crop, cv2.MORPH_OPEN, vertical_kernel, iterations=2)
            
            col_sum = np.sum(v_lines, axis=0)
            col_coords = [i for i, val in enumerate(col_sum) if val > h * 0.3 * 255]
            
            clean_cols = []
            if col_coords:
                clean_cols.append(col_coords[0])
                for c in col_coords[1:]:
                    if c - clean_cols[-1] > 10:
                        clean_cols.append(c)
            
            # Find horizontal lines
            horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 1))
            h_lines = cv2.morphologyEx(thresh_crop, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)
            
            # Additional morphological closing to strengthen weak lines
            h_lines = cv2.morphologyEx(h_lines, cv2.MORPH_CLOSE, horizontal_kernel, iterations=1)
            
            # Lower threshold to 2% of width to catch really faint lines
            row_sum = np.sum(h_lines, axis=1)
            row_coords = [i for i, val in enumerate(row_sum) if val > w * 0.02 * 255]
            
            clean_rows = []
            if row_coords:
                clean_rows.append(row_coords[0])
                for r in row_coords[1:]:
                    if r - clean_rows[-1] > 5:
                        clean_rows.append(r)
            
            logging.info(f"Row detection: found {len(clean_rows)} horizontal lines")

            # 4. Filter Rows & Fallback
            header_height_threshold = h / 40.0 # ~10px
            final_data_rows = []
            
            # Try to identify rows from grid
            for r_idx in range(len(clean_rows)-1):
                y1 = clean_rows[r_idx]
                y2 = clean_rows[r_idx+1]
                h_px = y2 - y1
                
                # Filter noise and likely header blocks
                if h_px > header_height_threshold and h_px < h * 0.2:
                    final_data_rows.append((y1, y2))
            
            # GEOMETRY FALLBACK if grid detection failed (e.g. only header found)
            if len(final_data_rows) < 5:
                 logging.warning(f"Weak row detection ({len(final_data_rows)} rows, {len(clean_rows)} clean lines), using dynamic geometry")
                 
                 # 1. Find actual data start
                 # Heuristic: 3rd horizontal line (index 2) is usually the start of queue 1.1
                 # (Line 0: top, Line 1: bottom of date, Line 2: bottom of hours/top of data)
                 if len(clean_rows) >= 3:
                     start_y = clean_rows[2]
                     logging.info(f"Using 3rd line as start_y: {start_y}")
                 else:
                     # Traditional variance search
                     gray_crop = cv2.cvtColor(crop_color, cv2.COLOR_BGR2GRAY)
                     row_variance = []
                     window_size = 3
                     for y in range(0, h - window_size, 2):
                         window = gray_crop[y:y+window_size, :]
                         var = np.var(window)
                         row_variance.append((y, var))
                     
                     start_search = int(h * 0.25)
                     start_y = int(h * 0.40)  # default fallback
                     
                     for y, var in row_variance:
                         if y > start_search and var < 1000:
                             start_y = y
                             break
                 
                 # 2. Estimate Row Height
                 gaps = []
                 for i in range(len(clean_rows)-1):
                     g = clean_rows[i+1] - clean_rows[i]
                     if g > 15 and g < h * 0.2: # Valid data row height
                         gaps.append(g)
                 
                 if gaps:
                     row_h = np.median(gaps)
                 else:
                     row_h = (h * 0.55) / 12.0
                 
                 logging.info(f"Geometric fallback: start_y={start_y}, row_height={row_h:.1f}")
                         
                 # Generate 12 rows
                 final_data_rows = []
                 for i in range(12):
                     # If we found a start line, assum it's the TOP of row 0? 
                     # Or the line between Header and Row 0? 
                     # Usually line separates Header and Row 1.1.
                     y1 = int(start_y + i * row_h)
                     y2 = int(start_y + (i+1) * row_h)
                     
                     # Check bounds
                     if y2 < h:
                         final_data_rows.append((y1, y2))
            
            # Queue 1.1 is likely the first row here.
            target_idx = 0
            if queue == "1.2": target_idx = 1
            if queue == "2.1": target_idx = 2
            
            if target_idx >= len(final_data_rows):
                target_idx = len(final_data_rows) - 1
                
            y1, y2 = final_data_rows[target_idx]
            # Refine center: simple middle
            cy = int((y1+y2)/2)
            
            # Columns: Intelligent Selection
            # We likely have extra columns at the end (Duration, %)
            # Strategy: Find a sequence of 24 intervals with consistent width
            
            hours_lines = []
            
            if len(clean_cols) >= 25:
                # Calculate widths of intervals
                widths = []
                for i in range(len(clean_cols)-1):
                    distances = clean_cols[i+1] - clean_cols[i]
                    widths.append(distances)
                
                best_start = -1
                min_std = float('inf')
                
                # Slide window of 24 intervals
                # We expect 24 hour columns. The rightmost columns might be wider.
                # Valid scan requires 24 intervals (25 lines)
                
                # Check from End to Start? Usually 24 hours are before the last 2 cols.
                # Max start index = len(widths) - 24
                
                max_start = len(widths) - 24
                for s in range(max_start + 1):
                    window = widths[s : s+24]
                    std_dev = np.std(window)
                    avg_w = np.mean(window)
                    
                    # Heuristic: Hour width should be reasonably small?
                    # And consistent (low std_dev)
                    if std_dev < min_std:
                        min_std = std_dev
                        best_start = s
                
                if best_start != -1:
                    # Found best standard deviation
                    # But verify if it makes sense (e.g. not catching 1px noise)
                    chosen_window = widths[best_start : best_start+24]
                    if np.mean(chosen_window) > 10:
                        start_line_idx = best_start
                        hours_lines = clean_cols[start_line_idx : start_line_idx + 25]
                        logging.info(f"Grid detected at Col Index {start_line_idx}, AvgW={np.mean(chosen_window):.1f}, Std={min_std:.2f}")

            # Fallback if intelligent selection failed OR if we are in geometry fallback for rows (image likely noisy/blurry)
            use_geometry_cols = (len(hours_lines) != 25)
            
            # If we had to guess rows, we should probably guess columns too to be safe (avoid mixing detected cols with guessed rows)
            if len(clean_rows) < 5: 
                use_geometry_cols = True
                logging.warning("Forcing geometry columns because row detection was weak")

            if use_geometry_cols:
                 # Geometric Column Fallback
                 # Standard HOE layout:
                 # Queue (Left ~25%) | Hours (Middle ~68%) | Totals (Right ~7%)
                 
                 # More precise measurements from actual table
                 # Hours start at roughly 25% and span 68% of width
                 hour_width = w * 0.68
                 hour_start_x = w * 0.25
                 stride = hour_width / 24.0
                 
                 hours_lines = [int(hour_start_x + stride*i) for i in range(25)]
                 logging.info(f"Geometric columns: start={hour_start_x:.1f}, width={hour_width:.1f}, stride={stride:.1f}")
            
            # 5. Sample Colors
            outage_hours = []
            
            # Debug info: Log sampling coordinates
            if len(hours_lines) > 0:
                h_start = hours_lines[0]
                h_end = hours_lines[-1]
                h_stride = (hours_lines[1] - hours_lines[0]) if len(hours_lines) > 1 else 0
                logging.info(f"Sampling Colors. Row Y-center: {cy}. X range: {h_start}-{h_end}. Avg Hour Width: {h_stride}")
            
            for h_idx in range(24):
                if h_idx >= len(hours_lines)-1: break
                
                x1 = hours_lines[h_idx]
                x2 = hours_lines[h_idx+1]
                cx = int((x1+x2)/2)
                
                try:
                    pixel = crop_color[cy, cx]
                    b, g, r_v = int(pixel[0]), int(pixel[1]), int(pixel[2])
                    
                    # Exact color match from user image: 
                    # Blue: R=134, G=164, B=219 (approx)
                    # White: R=255, G=255, B=255
                    
                    # Flexible Blue Check
                    is_blue = (b > r_v + 30) and (b > g)
                    # Flexible White Check (Brightness)
                    is_white = (b > 200 and g > 200 and r_v > 200)
                    
                    if is_blue and not is_white:
                        outage_hours.append(h_idx)
                except IndexError:
                    pass
                    
            return outage_hours

        except Exception as e:
            logging.error(f"Image parsing failed: {e}")
            return []

    async def get_today_outages(self, queue: str = "1.1") -> List[int]:
        """Public API to get hours"""
        img_bytes = await self.fetch_latest_schedule_image()
        if not img_bytes:
            return []
        
        return self.parse_image(img_bytes, queue)
