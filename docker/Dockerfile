FROM --platform=$BUILDPLATFORM node:20-alpine AS ui-builder
# Branch, tag or full commit hash of NSPanelManager-Web-UI to build, e.g. --build-arg WEB_UI_REF=devel.
ARG WEB_UI_REF=main
WORKDIR /ui-app

# Fetch the UI repo at WEB_UI_REF with BuildKit's git source. BuildKit resolves the ref to a commit
# and caches by it, so the UI build below reruns when the ref moves and is reused otherwise. This
# goes over git, not the GitHub REST API, so it is not subject to the API's unauthenticated rate
# limit (60 an hour per IP, shared by CI runners), which failed builds with "403" on load of the
# cache key.
ADD https://github.com/NSPManager/NSPanelManager-Web-UI.git#${WEB_UI_REF} .

# Install dependencies and build
RUN npm install
RUN npm run build

# Builds the React components into dist/ and templates/scripts.html, which are not committed.
# Only the package files are copied before npm ci, so editing the source reuses the dependency layer.
# Node 22 matches the CI workflows (Vite 8 needs ^22.12). The output is the same for any build
# platform, so this stage runs on the build host even for cross-platform images.
FROM --platform=$BUILDPLATFORM node:22-alpine AS react-builder
# rtttl.test.ts imports ../../../tests/rtttl_vectors.json and firmwareGithubModal.test.ts imports
# ../../../static/firmware_github.js, and tsc -b type-checks both, so the build needs those files at the
# same relative places: /ui/tests and /ui/static next to /ui/react-components.
WORKDIR /ui/react-components
COPY web/nspanelmanager/web/tests/rtttl_vectors.json /ui/tests/rtttl_vectors.json
COPY web/nspanelmanager/web/static/firmware_github.js /ui/static/firmware_github.js
COPY web/nspanelmanager/web/react-components/package.json web/nspanelmanager/web/react-components/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY web/nspanelmanager/web/react-components/ ./
RUN npm run build

# Builds MQTTManager for the release image. The devel target does not use this stage, so
# docker build --target devel skips it.
FROM --platform=$BUILDPLATFORM python:3.12.5-bookworm AS build
ARG TARGETPLATFORM
ARG BUILDPLATFORM
WORKDIR /MQTTManager
SHELL ["/bin/bash", "-c"]

# Update container
RUN apt-get update && apt-get -y upgrade

RUN echo "Running on $BUILDPLATFORM, building for $TARGETPLATFORM"
COPY build_scripts/ /build_scripts/
RUN bash /build_scripts/install_build_tools.sh no
COPY MQTTManager/ /MQTTManager/
# The Conan package cache (core.cache:storage_path in install_build_tools.sh) is a BuildKit cache
# mount, so rebuilds reuse the dependencies instead of compiling them from source again, and CI can
# save it between runs. Only /MQTTManager/build is copied out of this stage.
RUN --mount=type=cache,id=nspm-conan,target=/MQTTManager/conan_cache,sharing=locked \
    /bin/bash /MQTTManager/compile_mqttmanager.sh --target-platform "$TARGETPLATFORM" --strip

# What the devel and release images share. It contains no source, so editing the source
# does not invalidate it.
FROM python:3.12.5-bookworm AS runtime-base
WORKDIR /usr/src/app
SHELL ["/bin/bash", "-c"]

# Update container
RUN apt-get update && apt-get -y upgrade

# Install ImageMagick to be able to process images and send them to the NSPanel
RUN apt-get install -y nginx libmagick++-dev
COPY web/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

EXPOSE 8000
COPY --from=ui-builder /ui-app/dist /var/www/html/webapp

# Development image, built with --target devel (see docker-build_and_run_dev.sh). It has the
# tools to build MQTTManager but no source: web/, MQTTManager/, HMI_files/ and the nginx
# files are mounted in at runtime.
FROM runtime-base AS devel
# Install software needed to build the manager. This also runs npm install for the react
# components, which only needs their package files.
COPY build_scripts/ /build_scripts/
COPY web/nspanelmanager/web/react-components/package.json web/nspanelmanager/web/react-components/package-lock.json /usr/src/app/nspanelmanager/web/react-components/
RUN bash /build_scripts/install_build_tools.sh yes
CMD ["/bin/bash", "./runserver_devel.sh"]

# Release image. This must stay the last stage: it is what a plain docker build, and the
# Home Assistant builder in release.yml, build.
FROM runtime-base AS release
COPY web/ /usr/src/app/
COPY --from=react-builder /ui/react-components/dist/ /usr/src/app/nspanelmanager/web/react-components/dist/
COPY --from=react-builder /ui/react-components/templates/ /usr/src/app/nspanelmanager/web/react-components/templates/
COPY nginx/sites-enabled/ /etc/nginx/sites-enabled/
COPY nginx/sites-templates/ /etc/nginx/sites-templates/
COPY "HMI_files/terminal/" /usr/src/app/nspanelmanager/HMI_files/terminal/
COPY --from=build /MQTTManager/build /MQTTManager/build
CMD ["/bin/bash", "./run_uwsgi.sh"]
