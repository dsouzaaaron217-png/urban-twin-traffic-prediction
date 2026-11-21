import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SYNTHETIC_DEMO_CSV = DATA_DIR / "synthetic_demo_traffic.csv"

def generate_synthetic_demo_dataset():
    roads = [
        {
            "city": "Pune",
            "area": "Central Pune",
            "latitude": 18.5204,
            "longitude": 73.8567,
            "free_flow_speed_kmh": 40.0,
            "base_travel_time": 600,
        },
        {
            "city": "Pune",
            "area": "Hinjawadi",
            "latitude": 18.5913,
            "longitude": 73.7389,
            "free_flow_speed_kmh": 60.0,
            "base_travel_time": 450,
        },
    ]

    # Generate 7 days of 15-minute observations
    now_local = datetime.now(ZoneInfo("Asia/Kolkata"))
    end_time = now_local.replace(minute=(now_local.minute // 15) * 15, second=0, microsecond=0)
    start_time = end_time - timedelta(days=7)

    records = []
    current = start_time
    while current <= end_time:
        hour = current.hour + current.minute / 60.0
        is_weekend = current.weekday() >= 5

        for r in roads:
            ff = r["free_flow_speed_kmh"]
            # Rush hour modeling
            if is_weekend:
                # Milder afternoon and evening peak
                if 12.0 <= hour <= 15.0:
                    congestion = 30.0 + 10.0 * (1.0 - abs(hour - 13.5) / 1.5)
                elif 17.0 <= hour <= 21.0:
                    congestion = 35.0 + 15.0 * (1.0 - abs(hour - 19.0) / 2.0)
                else:
                    congestion = 5.0 + (hour / 24.0) * 10.0
            else:
                # Morning rush 8:30 - 10:30
                if 8.0 <= hour <= 11.0:
                    congestion = 45.0 + 35.0 * (1.0 - abs(hour - 9.5) / 1.5)
                # Evening rush 17:30 - 20:30
                elif 17.0 <= hour <= 21.0:
                    congestion = 50.0 + 35.0 * (1.0 - abs(hour - 19.0) / 2.0)
                elif 23.0 <= hour or hour <= 5.0:
                    congestion = 2.0 + (hour % 6) * 0.5
                else:
                    congestion = 15.0 + ((hour - 11.0) / 6.0) * 10.0

            # Deterministic small variation based on road and minute
            h_val = int(current.timestamp() // 900) + (100 if r["area"] == "Hinjawadi" else 0)
            var = ((h_val % 100) / 100.0 - 0.5) * 4.0
            congestion = round(max(0.0, min(100.0, congestion + var)), 1)
            speed = round(max(5.0, ff * (1.0 - congestion / 100.0)), 1)
            travel_time = round(r["base_travel_time"] * (ff / speed))

            records.append({
                "timestamp": current.isoformat(),
                "city": r["city"],
                "area": r["area"],
                "latitude": r["latitude"],
                "longitude": r["longitude"],
                "current_speed_kmh": speed,
                "free_flow_speed_kmh": ff,
                "current_travel_time_seconds": travel_time,
                "free_flow_travel_time_seconds": r["base_travel_time"],
                "confidence": 0.95,
                "congestion_percent": congestion,
                "source": "synthetic_demo",
                "quality": "synthetic_demo",
            })
        current += timedelta(minutes=15)

    df = pd.DataFrame(records)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(SYNTHETIC_DEMO_CSV, index=False)
    return df

if __name__ == "__main__":
    df = generate_synthetic_demo_dataset()
    print(f"Generated {len(df)} synthetic demo records in {SYNTHETIC_DEMO_CSV}.")
