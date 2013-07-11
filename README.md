ical2redmine
============

A tool to keep your redmine time entries updated directly from an ical exportable calendar.
This tool will create, update and delete time entries on your redmine installation based on ical events from a feed of ical events (such as Google Calendar).

How to install:
 1. Clone the Github repo onto your local machine or server, running ```git clone https://github.com/kraenhansen/ical2redmine.git``` on a unix/linux machine.
 2. Fetch the pyactiveresource dependency submodule by navigating into your newly cloned ical2redmine directory and run ```git submodule init``` followed by ```git submodule update```
 3. You have to build the pyactiveresource dependency by first navigating into the folder: ```cd pyactiveresource``` and then building the library, running: ```python setup.py build```, navigate back to the ical2redmine directory.
 4. You have to create two custom variables on your Redmine installation.
  * Login to your redmine installation, using an administrative account.
  * Navigate to _Administration > Custom fields_
  * Under the tab titled _Spent time_ click the _New custom field_ link, enter a name such as _iCal UID_ and hit the _Save_ button (leaving _Text_ as _Type_ and _Required_ unchecked).
    * Click the name of the newly created custom field in the table and examine the URL of the page you get sent to, it has the format _/custom_fields/[integer]/edit_ where _[integer]_ is the id of the newly created field, hang onto this as the _custom time entry field id_.
  * Under the tab titled _Users_ create another customfield named _iCal Time Entry URL_ and follow the same procedure as above. Remember it's id as the _custom user field id_.
 5. Now copy the settings.example.json file to some other file like settings.json (```cp settings.example.json settings.json```) and start filling in the blank ___'s. Please consult the example file and source-code for details on the values of the parameters.
  * __redmine_url__: The URL to the redmine installation, into which iCal events should be imported.
  * __pattern__: A [reqular expression pattern](http://docs.python.org/2/howto/regex.html) for the summary(/title) of the iCal events
  * __update_existing_entries__: A boolean value true/false, telling the tool if it should update and delete redmine time entries or if it should just create (Note: Only time entries created by the tool will be affected).
  * __custom_time_entry_field id__: The _id_ of the field created in 4.3
  * __custom_user_field id__: The _user_ of the field created in 4.4
  * __since__: A mm/dd/yyyy formatted lower bound on the iCal events to consider when reading the iCal feed and when considering Redmine time entries for update or deletion.
  * __subscriptions__: A list of objects (one pr. user that the tool should handle) with two fields,
    * __user_id__: The ID of the user: This is visible from the URL when clicking a users name on the _/users_ Redmine page.
    * __api_key__: The API key of that particular user. This is visible on the _My account_ (link in the top-right corner) page, when clicking the _Show_ link below _API access key_ on the light hand side.
 6. The final step is to add the URL of the iCal feed to your users account: Again on the _My account_ page add the URL in the newly created _iCal Time Entry URL_ custom field. If you are importing from Google Calendar, follow [this guide](https://support.google.com/calendar/answer/37111?hl=en&ref_topic=1672003) to obtain your private iCal URL. Instead of downloading the .ical file, copy the link. Please note that sharing this link on the Redmine installation will enable administrators to see and change your calendar, so consider using a seperate calendar for this.
 7. Now create events in the calendar, whereever you would like to report time entries. Using the standard pattern provided in the example settings file, the summary(/title) should contain _(#n)_ where _n_ is an integer referring to an issue id, on which to report time.
 8. Now run the tool by executing the following command: ```python ical2redmine.py --settings settings.json```.
 9. Consider setting this up as a periotic [cron job](http://www.adminschoice.com/crontab-quick-reference/) so you don't have to run the tool manually.

It has only been tested with Redmine 1.4.6 but I would expect it to work from Redmine 1.4.4 (as it depends the http://www.redmine.org/issues/11112 bugfix).

The process that the processor goes through:
 1. Fetch the ical feed of events.
 2. Fetch all time entries in the Redmine service.
 3. Loop through all iCal events from the ical feed:
   * Create time entries for any event in the past (lower bounded by the value of _since_) which does not already have a time entry.
   * If the _update_existing_entries_ flag is set in the settings: Update or delete any time entry, created by the tool, which is related to a particular iCal event.
 4. If the _update_existing_entries_ flag is set in the settings: Loop through all entries that has been created by the ical2redmine tool to check if they have been passed in the processing of iCal events, if not; They need to be deleted.

