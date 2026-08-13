#!/bin/bash
cd /home/Fantasy-Football-Isle-of-Man
source venv/bin/activate
set -a && source .env && set +a
python run.py > /home/fantasy-iom-dev.log 2>&1
