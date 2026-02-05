"""Debug script to check what timeline the parser generates"""
import asyncio
import logging
from datetime import datetime
from bot.services.schedule_parser import ScheduleParser

logging.basicConfig(level=logging.INFO)

async def debug_timeline():
    parser = ScheduleParser()
    
    print("\n=== Fetching Outage Timeline for Queue 1.1 ===")
    timeline = await parser.get_outage_timeline(queue="1.1")
    
    if not timeline:
        print("❌ No timeline fetched!")
        return
    
    print(f"\n✅ Timeline has {len(timeline)} entries:")
    
    # Group by date
    by_date = {}
    for dt in timeline:
        d = dt.date()
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(dt.hour)
    
    for d in sorted(by_date.keys()):
        hours = sorted(by_date[d])
        print(f"\n📅 {d.strftime('%d.%m.%Y')}:")
        print(f"   Hours: {hours}")
        print(f"   Total: {len(hours)} hours")
        
        # Detect blocks
        blocks = []
        if hours:
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
        
        print(f"   Blocks: {blocks}")

if __name__ == "__main__":
    asyncio.run(debug_timeline())
