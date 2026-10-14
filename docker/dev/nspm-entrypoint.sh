#!/bin/bash
# Starts NSPanelManager in the dev stack (see compose.yaml). Seeds a fresh database, then
# runs the devel web server, which starts MQTTManager. If this stack has not built
# MQTTManager yet, that build runs in the background so the web UI is up meanwhile, and
# starts MQTTManager when it finishes.

cd /usr/src/app/nspanelmanager || exit 1
python manage.py migrate --noinput || exit 1
python manage.py shell </dev-stack/seed.py || exit 1

if [ ! -x /MQTTManager/build/nspm_mqttmanager ]; then
  echo "--> MQTTManager has not been built in this stack yet. Building it in the background; without a shared Conan cache the first build also builds all dependencies and is slow."
  (
    if /MQTTManager/compile_mqttmanager.sh; then
      until curl -fsS -o /dev/null http://localhost:8000/api/restart_mqtt_manager; do sleep 2; done
      echo "--> MQTTManager built and started."
    else
      echo "--> MQTTManager build FAILED. Fix the error and run: nspm-dev rebuild"
    fi
  ) &
fi

cd /usr/src/app || exit 1
exec bash ./runserver_devel.sh
