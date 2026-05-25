#!/bin/bash
# Simple UCI simulator - works with set key=value format
CONFIG_DIR="/etc/config"
QUIET=0
[ "$1" = "-q" ] && { QUIET=1; shift; }

cmd="$1"; shift

case "$cmd" in
    get)
        # Support both: "uci get config.section.option" and "uci get config section option"
        if [ -n "$3" ]; then
            # Format: uci get config section option
            config="$1"; section="$2"; option="$3"
        elif echo "$1" | grep -q "\." ; then
            # Format: uci get config.section.option
            arg="$1"
            config="${arg%%.*}"
            rest="${arg#*.}"
            if echo "$rest" | grep -q "\." ; then
                section="${rest%%.*}"
                option="${rest#*.}"
            else
                section="$rest"
                option=""
            fi
        fi

        file="${CONFIG_DIR}/${config}"
        [ ! -f "$file" ] && exit 1

        if [ -n "$option" ]; then
            # Get specific option value
            key="${config}.${section}.${option}"
            line=$(grep "^set ${key}=" "$file" 2>/dev/null | head -1)
            if [ -n "$line" ]; then
                echo "$line" | cut -d= -f2-
                exit 0
            fi
        else
            # Get section type
            key="${config}.${section}"
            line=$(grep "^set ${key}=" "$file" 2>/dev/null | head -1)
            if [ -n "$line" ]; then
                echo "$line" | cut -d= -f2-
                exit 0
            fi
        fi
        exit 1
        ;;
    set)
        # Support: "uci set config.section.option=value" or "uci set config.section=type"
        # or "uci set config section option value"
        arg="$1"
        if echo "$arg" | grep -q "=" ; then
            # Format: config.section.option=value or config.section=type
            key="${arg%%=*}"
            val="${arg#*=}"
            config="${key%%.*}"
            echo "set ${key}=${val}" >> "${CONFIG_DIR}/${config}.pending"
        elif [ -n "$3" ]; then
            # Format: uci set config section option value
            config="$1"
            echo "set ${config}.${2}=${3}" >> "${CONFIG_DIR}/${config}.pending"
        else
            # Format: uci set config section=type
            echo "set ${1}=${2}" >> "${CONFIG_DIR}/$(echo $1 | cut -d. -f1).pending"
        fi
        ;;
    commit)
        config="$1"
        pending="${CONFIG_DIR}/${config}.pending"
        file="${CONFIG_DIR}/${config}"
        if [ -f "$pending" ]; then
            while IFS= read -r line; do
                case "$line" in
                    "set "*)
                        set_key=$(echo "$line" | sed 's/^set //;s/=.*//')
                        set_val=$(echo "$line" | sed 's/^[^=]*=//')
                        if [ -f "$file" ] && grep -q "^set ${set_key}=" "$file" 2>/dev/null; then
                            sed -i "s|^set ${set_key}=.*|set ${set_key}=${set_val}|" "$file"
                        else
                            echo "set ${set_key}=${set_val}" >> "$file"
                        fi
                        ;;
                    "delete "*)
                        del_key=$(echo "$line" | sed 's/^delete //')
                        if [ -f "$file" ]; then
                            sed -i "/^set ${del_key}=/d; /^set ${del_key}\./d" "$file" 2>/dev/null || true
                        fi
                        ;;
                esac
            done < "$pending"
            rm -f "$pending"
        fi
        ;;
    delete)
        # Format: uci delete config.section or uci delete config.section.option
        config=$(echo "$1" | cut -d. -f1)
        echo "delete $1" >> "${CONFIG_DIR}/${config}.pending"
        ;;
    show)
        # Format: uci show config
        arg="$1"
        if echo "$arg" | grep -q "\." ; then
            # Show specific section: wifidog_v3.settings
            config="${arg%%.*}"
            rest="${arg#*.}"
            file="${CONFIG_DIR}/${config}"
            if [ -f "$file" ]; then
                grep "^set ${config}\.${rest}" "$file" 2>/dev/null || true
            fi
        else
            file="${CONFIG_DIR}/${arg}"
            [ -f "$file" ] && cat "$file"
        fi
        ;;
    batch)
        while IFS= read -r batch_cmd; do
            /usr/local/bin/uci -q $batch_cmd 2>/dev/null || true
        done
        ;;
    *)
        echo "Usage: uci [get|set|delete|commit|show] ..." >&2
        exit 1
        ;;
esac
