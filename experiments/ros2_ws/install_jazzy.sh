#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "\nInstallation stopped at line %s. Fix the reported error, then rerun this script.\n" "$LINENO" >&2' ERR
. /etc/os-release
if [[ "$ID" != ubuntu || "$VERSION_ID" != 24.04 ]]; then
  echo 'This script requires Ubuntu 24.04.' >&2
  exit 1
fi
export LANG=C.UTF-8
sudo -v
sudo apt-get -o APT::Update::Error-Mode=any update
sudo apt-get install -y curl ca-certificates software-properties-common python3
sudo add-apt-repository -y universe
tmp_dir=$(mktemp -d)
trap 'rm -rf -- "$tmp_dir"' EXIT
curl --fail --show-error --location --connect-timeout 15 --max-time 60 \
  https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest \
  -o "$tmp_dir/release.json"
version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tag_name"])' "$tmp_dir/release.json")
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
printf 'ros2-apt-source release: %s\n' "$version"
curl --fail --show-error --location --connect-timeout 15 --max-time 120 \
  "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${version}/ros2-apt-source_${version}.noble_all.deb" \
  -o "$tmp_dir/ros2-apt-source.deb"
sudo dpkg -i "$tmp_dir/ros2-apt-source.deb"
sudo apt-get -o APT::Update::Error-Mode=any update
sudo apt-get install -y ros-jazzy-desktop ros-dev-tools mesa-utils
if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
  sudo rosdep init
fi
rosdep update --rosdistro jazzy
echo 'ROS 2 Jazzy installed. Follow README.md to build and validate the workspace.'
