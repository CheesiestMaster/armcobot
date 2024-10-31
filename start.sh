#! /bin/bash

rm ./terminate.flag

source .venv/bin/activate
export LOOP_ACTIVE=true

while true; do
    python3 main.py
    if [ -f ./terminate.flag ]; then
        break
    fi
    sleep 1
done

deactivate
unset LOOP_ACTIVE
