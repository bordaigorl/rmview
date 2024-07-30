FROM python:3.12-slim
RUN apt-get update
RUN apt-get install -y \
  libdbus-1-3 \
  libfontconfig \
  libgl1-mesa-glx \
  libglib2.0-0 \
  libxcb-icccm4 \
  libxcb-image0 \
  libxkbcommon-x11-0
RUN apt-get clean

WORKDIR /rmview
COPY pyproject.toml build.py setup.py poetry.lock assets bin src README.md ./
RUN pip install .[tunnel]

CMD rmview
