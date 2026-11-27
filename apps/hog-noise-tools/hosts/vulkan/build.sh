#!/usr/bin/env sh
# HogNoise tools: build vulkan_host, the Vulkan host harness, with g++ against the Vulkan loader (Ubuntu:
# libvulkan-dev; lavapipe is mesa-vulkan-drivers). The binary is gitignored.
set -eu
here=$(dirname "$0")
g++ -std=c++17 -O2 -Wall -Wextra -Werror -o "$here/vulkan_host" "$here/vulkan_host.cpp" -lvulkan
