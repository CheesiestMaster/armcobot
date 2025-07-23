#! /bin/bash

rm -f ./terminate.flag
rm -f ./update.flag
# clear the PID file
echo "" > ./PID

source .venv/bin/activate
export LOOP_ACTIVE=true

while true; do
    "$(realpath main.py)"
    if [ -f ./terminate.flag ]; then
        echo "Terminating..."
        break
    fi
    if [ -f ./update.flag ]; then
        echo "Updating..."
        git fetch
        # check if there is a difference on ./start.sh
        if [ "$(git diff ./start.sh)" != "" ]; then
            echo "start.sh has changed, reexecuting..."
            git pull
            exec "$0" "$@"
        fi
        git pull
        echo "Updated"
    fi
    echo "Restarting..."
    sleep 1
done

deactivate
unset LOOP_ACTIVE
