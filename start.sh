#! /bin/bash

rm ./terminate.flag
# clear the PID file
echo "" > ./PID

source .venv/bin/activate
export LOOP_ACTIVE=true

while true; do
    $(realpath main.py)
    if [ -f ./terminate.flag ]; then
        echo "Terminating..."
        break
    fi
    echo "Restarting..."
    sleep 1
done

deactivate
unset LOOP_ACTIVE
