#!/bin/bash

IS_DEVEL="$1"
if [ -z "${IS_DEVEL}" ]; then
    echo "Did not provide IS_DEVEL. Will default to 'no'."
    IS_DEVEL="no"
fi

# Install tools needed for building MQTTManager
apt-get install -y --no-install-recommends cmake build-essential gdb curl npm postgresql-client curl inotify-tools net-tools build-essential protobuf-c-compiler
pip install conan conan-check-updates && conan profile detect --force
# Conan before 2.9 defaults to center.conan.io, which was frozen in 2024: newer recipes (such as
# paho-mqtt-cpp/1.5.3) are only on center2. The devel image gets web/requirements.txt's conan==2.7.0,
# so name the remote explicitly instead of relying on the version's default.
conan remote update conancenter --url https://center2.conan.io
echo 'core.cache:storage_path=/MQTTManager/conan_cache/' > ~/.conan2/global.conf
sed -i "s|cppstd=.*|cppstd=gnu23|g" /root/.conan2/profiles/default
echo "alias ll='ls -lh --color=auto'" >> /etc/bash.bashrc

if [ "${IS_DEVEL}" == "yes" ]; then
    sed -i "s|build_type=.*|build_type=Debug|g" /root/.conan2/profiles/default
    npm install -g bun
else
    sed -i "s|build_type=.*|build_type=Release|g" /root/.conan2/profiles/default
fi



# We are running in dev mode and has therefore copied the react-components folder into the container
if [ "$IS_DEVEL" == "yes" ]; then
    echo "Install Node Version Manager (NVM)"
    touch /root/.bash_env
    echo '. "/root/.bash_env"' >> /etc/bash.bashrc
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.4/install.sh | PROFILE="/root/.bash_env" bash
    echo node > .nvmrc

    # Hot-load NVM
    source /root/.bash_env

    # Install NODE and Python


    echo "Installing Node.js via NVM"
    nvm install

    cd /usr/src/app/nspanelmanager/web/react-components/
    npm install

    npm install typescript
fi
