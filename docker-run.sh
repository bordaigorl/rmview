#!/bin/bash
set -e

CONFIG_DIR=$HOME/.config/rmview
mkdir -p $CONFIG_DIR
xhost local:root
docker build -t rmview .
docker run \
  --env DISPLAY=$DISPLAY \
  --network host \
  --volume $CONFIG_DIR:/root/.config \
  --volume /tmp/.X11-unix:/tmp/.X11-unix \
  rmview
