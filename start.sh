#! /bin/bash

rm -f ./terminate.flag
rm -f ./update.flag
rm -f ./pending.flag
# clear the PID file
echo "" > ./PID

source .venv/bin/activate
export LOOP_ACTIVE=true

count=0

while true; do
    touch ./pending.flag
    "$(realpath main.py)"
    if [ -f ./terminate.flag ]; then
        echo "Terminating..."
        break
    fi

    if [ -f ./pending.flag ]; then
        count=$((count+1))
        echo "Restart count: $count"
        if [ $count -gt 5 ]; then
            echo "Too many restarts without a successful init, terminating..."
            break
        fi
    else
        count=0
    fi
    rm -f ./pending.flag

    if [ -f ./update.flag ]; then
        echo "Updating..."
        rm -f ./update.flag
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
