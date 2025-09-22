#!/bin/bash
gunicorn frozen_back.wsgi --bind 0.0.0.0:$PORT