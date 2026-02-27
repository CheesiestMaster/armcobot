#! /bin/bash

rm -f ./terminate.flag
rm -f ./update.flag
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
        reexec=false
        repip=false
        # check if there is a difference on ./start.sh against upstream
        if ! git diff --quiet HEAD..@{u} -- "$0"; then
            echo "start.sh has changed, reexecuting..."
            reexec=true
        fi

        if ! git diff --quiet HEAD..@{u} -- requirements.txt; then
            echo "requirements.txt has changed, reinstalling..."
            repip=true
        fi
        
        git pull
        if [ "$repip" = true ]; then
            pip install -r requirements.txt
        fi
        if [ "$reexec" = true ]; then
            exec "$0" "$@"
        fi
        echo "Updated"
    fi
    echo "Restarting..."
    sleep 1
done

deactivate
unset LOOP_ACTIVE
