"""Lightweight heartbeat-only stamp (no analysis, no Gemini, no Telegram).
Run hourly by cron so the cloud can detect local liveness quickly.
"""
from app.heartbeat import write_heartbeat
if __name__ == "__main__":
    write_heartbeat()
    print("heartbeat stamped")
