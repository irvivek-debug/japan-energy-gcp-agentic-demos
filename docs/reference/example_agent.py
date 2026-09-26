import os
from google.adk.agents import LlmAgent
from .datastore import STORE
MODEL = os.getenv("MODEL_BALANCED", "gemini-3.6-flash")

def get_daily_price_stats(date: str) -> dict:
    """Return JEPX Tokyo-area spot price statistics (JPY/kWh) for one delivery date (YYYY-MM-DD).

    Args:
      date: Delivery date, ISO format YYYY-MM-DD.
    """
    rows = STORE.query("SELECT ROUND(AVG(price_jpy_kwh),2) AS avg_price, MAX(price_jpy_kwh) AS max_price, MIN(price_jpy_kwh) AS min_price, COUNT(*) AS slots FROM {t:jepx_spot} WHERE date=@date", date=date)
    r = rows[0] if rows else {}
    if not r or not r.get("slots"):
        return {"status": "not_found", "date": date, "source": "jepx_spot"}
    return {"status": "ok", "date": date, **r, "source": "jepx_spot"}

def get_peak_slot(date: str) -> dict:
    """Return the most expensive 30-minute slot (1-48) and its price for a delivery date (YYYY-MM-DD).

    Args:
      date: Delivery date, ISO format YYYY-MM-DD.
    """
    rows = STORE.query("SELECT slot, price_jpy_kwh FROM {t:jepx_spot} WHERE date=@date ORDER BY price_jpy_kwh DESC LIMIT 1", date=date)
    return {"status": "ok", **rows[0], "source": "jepx_spot"} if rows else {"status": "not_found"}

root_agent = LlmAgent(
    name="price_analyst",
    model=MODEL,
    instruction=("You analyse JEPX Tokyo-area spot prices. Always call tools; never estimate numbers. "
                 "Quote figures exactly as returned, with units JPY/kWh, and name the source table in brackets like [jepx_spot]."),
    tools=[get_daily_price_stats, get_peak_slot],
)
