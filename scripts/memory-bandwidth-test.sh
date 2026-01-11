#!/bin/bash

set -e

apt update
apt install -y sysbench build-essential nasm lshw jq git
rm -rf bandwidth-benchmark || true
git clone https://github.com/romansavrulin/bandwidth-benchmark.git
cd bandwidth-benchmark/
make
