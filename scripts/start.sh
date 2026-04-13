#!/bin/bash

# start API
uvicorn app.main:app --host 0.0.0.0 --port 8000 &

# start worker
python -c "from app.worker import worker_loop; worker_loop()" &

# start telegram bot
python -c "from app.telegram_bot import run_bot; run_bot()"