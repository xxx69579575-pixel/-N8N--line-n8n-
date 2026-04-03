import os
from dataclasses import dataclass


@dataclass
class Config:
    # GitHub
    github_token: str
    opencalw_github_token: str  # 用於發 PR Review（避免自己審自己）
    github_repo: str          # e.g. "xxx69579575-pixel/-N8N--line-n8n-"
    webhook_secret: str

    # Discord
    discord_token: str        # ClaudeCode bot token
    opencalw_token: str       # OpenCalw Astra bot token
    discord_channel_id: int   # 1487718765717098526
    discord_agent_hub_id: int
    discord_logs_channel_id: int
    discord_review_queue_id: int

    # Bot identities
    claudecode_bot_id: int    # ClaudeCode#6623
    opencalw_bot_id: int      # OpenCalw Astra

    # Thresholds
    handoff_timeout_seconds: int = 300   # 5 min → trigger OpenCalw handoff
    max_auto_fix_retries: int = 3
    pr_review_timeout_hours: int = 48
    escalation_timeout_hours: int = 4
    thread_archive_minutes: int = 10

    # Local service restart
    api_server_project_root: str = r"D:/n8n/CLAUDE 實做/本地AI企業問答助理"
    api_server_port: int = 8765

    # Health Monitor
    health_check_interval_seconds: int = 300   # 每 5 分鐘檢查一次
    health_check_ports: list[int] | None = None # 預設 [8765]（api_server）
    n8n_health_url: str = "http://127.0.0.1:5678/healthz"  # n8n health endpoint

    # Auto-merge
    auto_merge_enabled: bool = True
    auto_merge_safe_paths: tuple[str, ...] = (  # 這些路徑變更視為低風險
        "workflows/",
        "config/",
        "docs/",
        ".md",
    )

    def __post_init__(self):
        if self.health_check_ports is None:
            self.health_check_ports = [8765]


def load_config() -> Config:
    return Config(
        github_token=os.environ["GITHUB_TOKEN"],
        opencalw_github_token=os.environ.get("OPENCALW_GITHUB_TOKEN", os.environ["GITHUB_TOKEN"]),
        github_repo=os.environ.get("GITHUB_REPO", "xxx69579575-pixel/-N8N--line-n8n-"),
        webhook_secret=os.environ["GITHUB_WEBHOOK_SECRET"],

        discord_token=os.environ["DISCORD_BOT_TOKEN"],
        opencalw_token=os.environ["OPENCALW_BOT_TOKEN"],
        discord_channel_id=int(os.environ.get("DISCORD_CHANNEL_ID", "1487718765717098526")),
        discord_agent_hub_id=int(os.environ["DISCORD_AGENT_HUB_ID"]),
        discord_logs_channel_id=int(os.environ["DISCORD_LOGS_CHANNEL_ID"]),
        discord_review_queue_id=int(os.environ["DISCORD_REVIEW_QUEUE_ID"]),

        claudecode_bot_id=int(os.environ["CLAUDECODE_BOT_ID"]),
        opencalw_bot_id=int(os.environ["OPENCALW_BOT_ID"]),

        api_server_project_root=os.environ.get(
            "API_SERVER_PROJECT_ROOT",
            r"D:/n8n/CLAUDE 實做/本地AI企業問答助理",
        ),
        api_server_port=int(os.environ.get("API_SERVER_PORT", "8765")),

        health_check_interval_seconds=int(os.environ.get("HEALTH_CHECK_INTERVAL", "300")),
        n8n_health_url=os.environ.get("N8N_HEALTH_URL", "http://127.0.0.1:5678/healthz"),
        auto_merge_enabled=os.environ.get("AUTO_MERGE_ENABLED", "true").lower() == "true",
    )
