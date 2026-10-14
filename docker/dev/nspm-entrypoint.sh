#!/bin/bash
# Starts NSPanelManager in the dev stack (see compose.yaml). Seeds a fresh database, builds
# MQTTManager if this stack has not built it yet, then runs the devel web server, which
# starts MQTTManager.

cd /usr/src/app/nspanelmanager || exit 1
python manage.py migrate --noinput || exit 1
python manage.py shell </dev-stack/seed.py || exit 1

if [ ! -x /MQTTManager/build/nspm_mqttmanager ]; then
  echo "--> MQTTManager has not been built in this stack yet. Building it; the first build also builds all Conan dependencies and is slow."
  if ! /MQTTManager/compile_mqttmanager.sh; then
    echo "--> MQTTManager build FAILED. Starting the web server anyway; fix the error and run: nspm-dev rebuild"
  fi
fi

cd /usr/src/app || exit 1
exec bash ./runserver_devel.sh
