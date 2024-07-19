#!/bin/bash

# Replace 'YourBotTokenHere' with your actual Discord bot token.
# It's recommended to actually set this in a secure place and not hard-code it in your scripts.
BOT_TOKEN=""

# The name of your Docker image
IMAGE_NAME="discord-flashcard-v0.1"

# Custom name for your Docker container
CONTAINER_NAME="discord-flashcard-container-v0.1"

#Build Docker image
docker build -t discord-flashcard-v0.1 .
# Run the Docker container, passing in the BOT_TOKEN environment variable and assigning a name to the container
docker run -e BOT_TOKEN="$BOT_TOKEN" --name "$CONTAINER_NAME" $IMAGE_NAME