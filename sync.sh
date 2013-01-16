#!/bin/bash
#cd pyactiveresource;python setup.py build;cd ..;
export PYTHONPATH=".:pyactiveresource/build/lib.linux-x86_64-2.7/"
python ical2redmine.py --settings settings.json --log debug
