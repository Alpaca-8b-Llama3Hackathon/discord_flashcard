# Use an official Python runtime as a parent image
FROM python:3.9.18-bullseye

# Set the working directory in the container
WORKDIR /mugpt

# update the system and add git
RUN apt-get -y update && apt-get -y upgrade 
RUN apt-get install git gcc libc-dev libffi-dev

# Copy the current directory contents into the container
COPY ./requirements.txt /mugpt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install --upgrade pip
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install -r requirements.txt

# copy project
COPY . /mugpt
# Install any needed packages specified in requirements.txt
# Ensure you have a requirements.txt file with discord.py listed in it
# RUN pip install --no-cache-dir -r requirements.txt

# Run kanom-bot.py when the container launches
CMD ["python", "./src/bot.py"]
