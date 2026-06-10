#!/usr/bin/env bash
# build.sh — Render build script
# Runs automatically on every deploy.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate