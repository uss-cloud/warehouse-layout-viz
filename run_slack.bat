@echo off
cd /d C:\Users\lalasweet\Desktop\project\frozen_layout\frozen_layout
python collector.py >> collector_log.txt 2>&1
python slack_notify.py >> slack_log.txt 2>&1