"""
啟動入口：初始化所有元件並啟動 Webhook 伺服器
"""
import logging
import sys
import os

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

from config import load_config
from discord_bot import DiscordBot
from orchestrator import Orchestrator
from github_webhook import app, init_webhook
from health_monitor import HealthMonitor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

if __name__ == "__main__":
    config = load_config()

    discord_bot = DiscordBot(config)
    orchestrator = Orchestrator(config, discord_bot)
    init_webhook(config, orchestrator)

    health_monitor = HealthMonitor(config, discord_bot)
    health_monitor.start()

    port = int(os.environ.get("PORT", 8080))   # 8080 = Flask webhook; 8765 reserved for api_server
    app.run(host="0.0.0.0", port=port)
