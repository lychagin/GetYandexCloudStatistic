#!/bin/sh

sudo docker ps -a | awk '/cost-tracker/{print $1}' | xargs sudo docker rm && sudo docker image rm cost-tracker
