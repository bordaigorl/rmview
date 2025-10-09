FROM python:3.9-slim-buster
RUN sed -i 's|deb.debian.org|archive.debian.org|g' /etc/apt/sources.list \
    && sed -i 's|security.debian.org|archive.debian.org|g' /etc/apt/sources.list \
    && echo "Acquire::Check-Valid-Until false;" > /etc/apt/apt.conf.d/99no-check-valid-until
RUN apt-get update && apt-get install -y \
  libdbus-1-3 \
  libfontconfig \
  libgl1-mesa-glx \
  libglib2.0-0 \
  libxcb-icccm4 \
  libxcb-image0 \
  libxkbcommon-x11-0 \
  && apt-get clean
RUN apt-get clean
WORKDIR /rmview
COPY resources.qrc setup.cfg setup.py ./
COPY assets ./assets
COPY bin ./bin
COPY src ./src
RUN pip install --upgrade pip
# TODO: setup.py could to be fixed to include install_requires
#       see also: https://stackoverflow.com/q/21915469/543875
RUN pip install pyqt5==5.14.2 paramiko twisted
RUN pip install .[tunnel]
RUN pip cache purge
CMD rmview
