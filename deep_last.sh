#!/bin/bash

# Ensure the script exits on any error
set -e

# Directory containing audio files
LOG_DIR="./src/audio_log"

# Check if the directory exists and is not empty
if [ ! -d "$LOG_DIR" ] || [ -z "$(ls -A "$LOG_DIR")" ]; then
    echo "No files found in $LOG_DIR"
    exit 1
fi

# Get the last file by modification time
LAST_FILE=$(ls -t "$LOG_DIR" | head -n 1)
FULL_PATH="$LOG_DIR/$LAST_FILE"

# Check if the DEEPGRAM_API_KEY environment variable is set
if [ -z "$DEEPGRAM_API_KEY" ]; then
    echo "DEEPGRAM_API_KEY is not set. Please set it in your environment."
    exit 1
fi

# Send the file to Deepgram's API and output the result to stdout
curl -s -X POST \
    -H "Authorization: Token $DEEPGRAM_API_KEY" \
    -H "Content-Type: audio/wav" \
    --data-binary @"$FULL_PATH" \
    "https://api.deepgram.com/v1/listen?sentiment=true&model=nova-2" | jq
