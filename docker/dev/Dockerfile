# Image for the dev stack (compose.yaml). Unlike ../Dockerfile it contains no source: the
# stack mounts web/, MQTTManager/, HMI_files/ and the nginx templates in at runtime. So the
# image only changes when the packages it installs change, and editing the source never
# rebuilds it. Its file list is in Dockerfile.dockerignore.

FROM node:20-alpine AS ui-builder
WORKDIR /ui-app
RUN apk add --no-cache git
# Fetching the commit main points at reruns the clone and build only when the UI repo changes.
ADD https://api.github.com/repos/NSPManager/NSPanelManager-Web-UI/git/refs/heads/main /ui-version.json
RUN git clone https://github.com/NSPManager/NSPanelManager-Web-UI.git .
RUN npm install
RUN npm run build

FROM python:3.12.5-bookworm
WORKDIR /usr/src/app
SHELL ["/bin/bash", "-c"]

RUN apt-get update && apt-get -y upgrade

# The same tools as the devel build of ../Dockerfile. install_build_tools.sh also runs npm
# install for the react components, which needs their package files.
COPY build_scripts/ /build_scripts/
COPY web/nspanelmanager/web/react-components/package.json web/nspanelmanager/web/react-components/package-lock.json /usr/src/app/nspanelmanager/web/react-components/
RUN bash /build_scripts/install_build_tools.sh yes

RUN apt-get install -y nginx libmagick++-dev
COPY web/requirements.txt /tmp/requirements.txt
# CPUCOUNT=1 builds uWSGI on one thread. Its parallel build can fail to start a compiler
# ("OSError: [Errno 14] Bad address: '/bin/sh") on some hosts, then fails to link.
RUN CPUCOUNT=1 pip install --no-cache-dir -r /tmp/requirements.txt

COPY nginx/sites-enabled/ /etc/nginx/sites-enabled/
COPY --from=ui-builder /ui-app/dist /var/www/html/webapp

EXPOSE 8000
