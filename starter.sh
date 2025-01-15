#!/bin/sh

# Let's check if DB container connected to cost-net network. Connect it if it isn't.
name=`sudo docker network inspect cost-net -f '{{ range.Containers}}{{.Name}}{{end}}' 2> /dev/null`
if [ $? -eq 0 ]; then
  if [ "$name" = "pg_db" ]; then
    echo "DB is up"
  else
    sudo docker network connect cost-net pg_db 
  fi
else
  echo "ERROR: Network cost-net may not exist!"
fi

container_id=`sudo docker ps -a | awk '/cost-tracker/ {print $1}'`
LOG_PATH=`sudo docker inspect "$container_id" | awk -F':' '/app.install.path/{gsub(" ","",$0); gsub("\"", "", $0); print $2}'`
LOG_FILE="$LOG_PATH/cost.cron.log"

sudo docker start -a cost-tracker 2>&1 | tee $LOG_FILE
container_id=`sudo docker ps -a | awk '/cost-tracker/ {print $1}'`
TOKEN=`grep TOKEN .telegram_bot_token | sed 's/TOKEN=//' | sed 's/\"//g'`
CHAT_ID=`grep CHAT_ID .telegram_bot_token | sed 's/CHAT_ID=//' | sed 's/\"//g'`
exit_code=`sudo docker inspect "$container_id" --format='{{.State.ExitCode}}'`
if [ "$exit_code" -eq 0 ]; then
    status="OK"
else
    status="NOK"
    export LOG=`cat $LOG_FILE`
    curl -i -X POST -H 'Content-Type: application/json' \
         -d '{"username":"statistic", "text":"cost-tracker launch has failed", "attachments":[{"pretext":"Here is a log file", "text":"'"$LOG"'"}]}' \
         https://chat.ptsecurity.com/hooks/jhy9yuanatrxme3hweineb8doa > /dev/null 2>&1
    # https://linuxscriptshub.com/send-telegram-message-linux-scripts/
    curl -s -X POST https://api.telegram.org/bot$TOKEN/sendMessage -d chat_id=$CHAT_ID -d text="cost-tracker launch has failed" > /dev/null
fi
echo "Exit status: $status"
logs=`cat $LOG_FILE`
timestamp=`date '+%Y-%m-%d %H:%M:%S'`
psql -h localhost -p 5433 -U root -d leadtime -c "update yac_log set update_date='$timestamp', status='$status', log='$logs' where id = 'cloud'"

