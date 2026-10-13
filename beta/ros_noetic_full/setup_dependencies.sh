#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
THIRD_PARTY="${ROOT_DIR}/catkin_ws/src/third_party"
mkdir -p "${THIRD_PARTY}"

clone_pinned() {
  local url="$1"
  local directory="$2"
  local commit="$3"
  if [[ ! -d "${directory}/.git" ]]; then
    git clone "${url}" "${directory}"
  fi
  git -C "${directory}" fetch --depth 1 origin "${commit}"
  git -C "${directory}" checkout --detach "${commit}"
}

clone_pinned \
  https://github.com/ros-agriculture/ublox_f9p.git \
  "${THIRD_PARTY}/ublox_f9p" \
  c903d54977ee003ca6c9c099639c7fb96b48ec39

clone_pinned \
  https://github.com/tilk/rtcm_msgs.git \
  "${THIRD_PARTY}/rtcm_msgs" \
  8d27ab5f4d4a581e1bb9c87d572994c25197f6d4

UBLOX_DIR="${THIRD_PARTY}/ublox_f9p"
PATCH_FILE="${ROOT_DIR}/patches/ublox_f9p_rtcm_dependency.patch"
if git -C "${UBLOX_DIR}" apply --reverse --check "${PATCH_FILE}"; then
  echo "u-blox RTCM dependency patch already applied"
elif git -C "${UBLOX_DIR}" apply --check "${PATCH_FILE}"; then
  git -C "${UBLOX_DIR}" apply "${PATCH_FILE}"
else
  echo "u-blox RTCM dependency patch cannot be applied cleanly" >&2
  exit 1
fi

NTRIP_EXAMPLE="${ROOT_DIR}/catkin_ws/src/rcboat_core/config/ntrip.env.example"
NTRIP_CONFIG="${ROOT_DIR}/catkin_ws/src/rcboat_core/config/ntrip.env"
if [[ ! -f "${NTRIP_CONFIG}" ]]; then
  cp "${NTRIP_EXAMPLE}" "${NTRIP_CONFIG}"
fi
chmod 600 "${NTRIP_CONFIG}"

echo "Dependencies are pinned inside ${THIRD_PARTY}"
