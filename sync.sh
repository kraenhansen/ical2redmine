#!/bin/bash
DIR=$(cd "$(dirname "$0")"; pwd)
cd $DIR
python ical2redmine.py --settings settings.json --log debug
