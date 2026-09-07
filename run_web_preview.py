"""Local preview runner for the web server. Not used in production."""
import asyncio, logging, os

# Honour the port the preview harness assigns.
os.environ.setdefault("WEB_PORT", os.environ.get("PORT", "3000"))
logging.basicConfig(level=logging.INFO)

from models.mongo_leaderboard_manager import MongoLeaderboardManager
from models.donation_manager import DonationManager
from web.server import RikoWebServer


class StubBot:
    def __init__(self):
        self.leaderboard_manager = MongoLeaderboardManager()
        self.donation_manager = DonationManager(self.leaderboard_manager.db)
        self.donation_controller = None
        self.loop = None

    def is_ready(self):
        return True


async def main():
    server = RikoWebServer(StubBot())
    await server.start()  # honours WEB_PORT
    print("preview running on http://127.0.0.1:3000")
    await asyncio.Event().wait()

asyncio.run(main())
