from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from pyrogram import Client, enums
from pyrogram.types import LinkPreviewOptions
from motor.motor_asyncio import AsyncIOMotorClient
from bson.objectid import ObjectId
from contextlib import asynccontextmanager
import asyncio
import logging

from config import API_ID, API_HASH, BOT_TOKEN, MULTI_WORKER_TOKENS, DATABASE_URL, DATABASE_NAME

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Globals
db_client = None
db = None
stream_links_col = None

bot = None
workers = []
_worker_state = {"index": 0}

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_client, db, stream_links_col, bot, workers
    
    # Initialize MongoDB
    logger.info("Connecting to MongoDB...")
    db_client = AsyncIOMotorClient(DATABASE_URL, serverSelectionTimeoutMS=5000)
    db = db_client[DATABASE_NAME]
    stream_links_col = db["stream_links"]
    
    # Initialize Main Bot
    logger.info("Starting Main Telegram Bot...")
    bot = Client(
        "streamer_bot",
        API_ID,
        API_HASH,
        bot_token=BOT_TOKEN,
        parse_mode=enums.ParseMode.HTML,
        max_concurrent_transmissions=10,
        sleep_threshold=0,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        in_memory=True
    )
    await bot.start()
    
    # Initialize Workers
    if MULTI_WORKER_TOKENS:
        logger.info(f"Starting {len(MULTI_WORKER_TOKENS)} worker(s)...")
        for i, token in enumerate(MULTI_WORKER_TOKENS):
            try:
                worker = Client(
                    f"streamer_worker_{i}",
                    API_ID,
                    API_HASH,
                    bot_token=token,
                    parse_mode=enums.ParseMode.HTML,
                    max_concurrent_transmissions=10,
                    sleep_threshold=0,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                    in_memory=True
                )
                await worker.start()
                workers.append(worker)
            except Exception as e:
                logger.error(f"Failed to start worker {i}: {e}")

    logger.info("Streamer Server is ready!")
    yield
    
    # Teardown
    logger.info("Shutting down...")
    await bot.stop()
    for worker in workers:
        await worker.stop()
    db_client.close()


app = FastAPI(lifespan=lifespan)

def get_next_client():
    global _worker_state
    if workers:
        client = workers[_worker_state["index"] % len(workers)]
        _worker_state["index"] += 1
        return client
    return bot

@app.get("/stream/{link_id}")
async def stream_file(request: Request, link_id: str):
    client = get_next_client()
    
    try:
        link_data = await stream_links_col.find_one({"_id": ObjectId(link_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid link ID format")

    if not link_data:
        raise HTTPException(status_code=404, detail="Link not found in database")
        
    chat_id = link_data["chat_id"]
    message_id = link_data["message_id"]
    
    try:
        message = await client.get_messages(chat_id, message_id)
    except Exception as e:
        logger.error(f"Telegram API Error fetching message: {e}")
        raise HTTPException(status_code=404, detail="Message not found in Telegram (or bot lacks access)")
        
    media = message.document or message.video or message.audio or message.photo
    if not media:
        raise HTTPException(status_code=404, detail="No media found in message")

    file_size = getattr(media, "file_size", 0)
    
    range_header = request.headers.get("Range", "")
    start = 0
    end = file_size - 1
    
    if range_header:
        parts = range_header.replace("bytes=", "").split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
        
    limit = end - start + 1
    
    async def file_sender():
        try:
            async for chunk in client.stream_media(message, offset=start, limit=limit):
                yield chunk
        except Exception as e:
            logger.error(f"Streaming error: {e}")

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(limit),
        "Content-Disposition": f'inline; filename="{getattr(media, "file_name", "file")}"'
    }
    
    return StreamingResponse(
        file_sender(),
        headers=headers,
        status_code=206 if range_header else 200
    )

@app.get("/ping")
async def ping():
    return {"status": "ok", "message": "Telegram Streamer API is running"}
