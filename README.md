ical2redmine
============

A tool to keep your redmine time entries updated directly from an ical exportable calendar.
This tool will create, update and delete time entries on your redmine installation based on ical events from a feed of ical events.

How to install:
 1. You don't, basically you have to build the pyactiveresource dependency by first navigating into the folder:

    cd pyactiveresource

and then building the library, running:

    python setup.py build

 2. Now copy the settings.example.json file to some other file like settings.json and start filling in the blank ___'s. Please consult the example file and source-code for details on the values of the parameters.

It has only been tested with Redmine 1.4.6 but I would expect it to work from Redmine 1.4.4 (as it depends the http://www.redmine.org/issues/11112 bugfix).

The process that the processor goes through:
 1. Fetch the ical feed of events.
 2. Fetch all time entries in the Redmine service.
 3. Loop through all entries that have been created by the ical2redmine tool to check them for changes in the commens, spent_on and hours fields. Update them with the newest information from the ical feed. If the event was deleted from the ical feed, the time entry will be as well.
 4. Loop through all remaining events from the ical feed, and create time entries for any event in the past.

