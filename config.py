import os
from typing import List

# Read directly from environment for Render/Docker deployments
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MULTI_WORKER_TOKENS = os.environ.get("MULTI_WORKER_TOKENS", "").split(",") if os.environ.get("MULTI_WORKER_TOKENS") else []

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DATABASE_NAME = os.environ.get("DATABASE_NAME", "mltb")
PORT = int(os.environ.get("PORT", "8080"))

# Ensure no empty strings in token list
MULTI_WORKER_TOKENS = [t.strip() for t in MULTI_WORKER_TOKENS if t.strip()]
