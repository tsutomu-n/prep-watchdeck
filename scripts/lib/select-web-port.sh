#!/usr/bin/env bash

WATCHDECK_WEB_PORT_CANDIDATES=100

watchdeck_web_port_is_in_use() {
  local port="$1"

  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    return
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -H -ltn "sport = :$port" 2>/dev/null | grep -q .
    return
  fi

  echo "cannot detect web port conflicts: install lsof or ss" >&2
  return 2
}

select_watchdeck_web_port() {
  local requested_port="$1"
  if [[ ! "$requested_port" =~ ^[0-9]{1,5}$ ]] ||
    ((10#$requested_port < 1 || 10#$requested_port > 65535)); then
    echo "PORT must be an integer from 1 through 65535: $requested_port" >&2
    return 2
  fi

  requested_port=$((10#$requested_port))
  local last_candidate=$((requested_port + WATCHDECK_WEB_PORT_CANDIDATES - 1))
  if ((last_candidate > 65535)); then
    last_candidate=65535
  fi

  local candidate
  local in_use_status
  for ((candidate = requested_port; candidate <= last_candidate; candidate++)); do
    in_use_status=0
    watchdeck_web_port_is_in_use "$candidate" || in_use_status=$?
    case "$in_use_status" in
      0)
        ;;
      1)
        if ((candidate != requested_port)); then
          echo "warning: port $requested_port is in use; using $candidate" >&2
        fi
        printf '%s\n' "$candidate"
        return 0
        ;;
      *)
        return "$in_use_status"
        ;;
    esac
  done

  echo "no available web port found from $requested_port through $last_candidate" >&2
  return 3
}
