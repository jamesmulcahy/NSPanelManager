#!/bin/bash
echo "==> Installing protobuf 29.6 x86_64."
PB_REL="https://github.com/protocolbuffers/protobuf/releases"
REMOTE_FILE="protoc-29.6-linux-x86_64.zip"
curl -LO $PB_REL/download/v29.6/"$REMOTE_FILE"

rm -rf temp/
mkdir temp/
unzip "$REMOTE_FILE" -d temp/ && rm "$REMOTE_FILE"
cp -r temp/bin/* /bin/
cp -r temp/include/* /usr/include/
rm -rf temp/
