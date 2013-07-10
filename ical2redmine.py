import sys
import argparse
import urllib2
from icalendar import Calendar, Event
import json
import re
import logging
import datetime
import pytz
import os
import dateutil.parser

# Loading the custom pyactiveresource library.
# Removing any packaged .eggs from the system path.
for p in sys.path:
	if "pyactiveresource" in p and ".egg" in p:
		print "Removing the pyactiveresource package (%s) from the system path." % p
		sys.path.remove(p)
# Adding the custom build package.
if "build" in os.listdir("./pyactiveresource"):
	pyactiveresource_path="./pyactiveresource/build/%s" % os.listdir("./pyactiveresource/build")[0]
	sys.path.append(pyactiveresource_path)
else:
	print "Error: You have to build the pyactiveresource lib, before you run the tool."
	print "Simply navigate into the pyactiveresource directory and execute 'python setup.py build'."
	sys.exit(-1)

from pyactiveresource.activeresource import ActiveResource
from pyactiveresource import formats

log = logging.getLogger(__name__)
logging.getLogger('pyactiveresource').setLevel(logging.WARNING)

class RedmineActiveResource(ActiveResource):
	_site = None
	_user = None
	def get_custom_field_value(self, custom_field_id, raiseExceptionIfNoCustomField = True):
		if "custom_fields" in self.to_dict().keys():
			for field in self.custom_fields:
				#print type(field.attributes)
				if int(field.id) == int(custom_field_id):
					return field.value
		if raiseExceptionIfNoCustomField:
			raise Exception("Cannot get the ical_uid, because the 'ical2redmine_uid' custom field was not present.")
		else:
			return None

class TimeEntries(RedmineActiveResource):
	_singular = 'time_entry'
	_since = None
	
	# Changing the default values.
	def to_xml(self, root=None, header=True, pretty=False, dasherize=False):
		return super(TimeEntries, self).to_xml(root=root, header=header, pretty=pretty, dasherize=dasherize)

	def is_ical2redmine(self, custom_time_entry_field_id):
		return self.get_custom_field_value(custom_time_entry_field_id, False) is not None

	def update_from_ical(self, event, issue_id, custom_field_id, activity_id = None):
		assert issue_id, "issue_id cannot be None."

		comments = unicode(event.get('DESCRIPTION')).replace("\n", " ")
		start = event.get('DTSTART').dt
		end = event.get('DTEND').dt
		duration = end - start
		hours = duration.total_seconds() / (60 * 60)

		if start > datetime.datetime.now(pytz.UTC):
			# We want bother with events in the future.
			if self.id:
				log.info("[-] Deleting entry #%s because the event was moved to the future.", self.id)
				self.destroy()
				return
			else:
				log.info("[ ] Skipping creating an entry because the event was in the future.")
				return

		if self._since and self._since > start:
			# We want bother with events too long into the past.
			if self.id:
				log.info("[-] Deleting entry #%s because the event was too old.", self.id)
				self.destroy()
				return
			else:
				log.info("[ ] Skipping creating an entry because the event was too old.")
				return

		spent_on = start.date().isoformat()

		# For the comparison to be fair.
		if self.id and self.comments == None:
			self.comments = ""

		if self.id:
			# Check if something has changed.
			has_changed = \
				self.hours != str(hours) or \
				self.spent_on != spent_on or \
				self.comments != comments or \
				self.issue != str(issue_id) or \
				(activity_id != None and self.activity.id != str(activity_id))
		else:
			has_changed = True

		if has_changed:
			if self.id:
				log.info("[*] Some things have changed, saving time entry #%s", self.id)
				self._update({
					"hours": str(hours),
					"spent_on": spent_on,
					"issue_id": str(issue_id),
					#"activity_id": str(activity_id),
					"comments": comments
				})
				self.save()
			else:
				log.info("[+] This will be created.")
				self._update({
					"hours": str(hours),
					"spent_on": spent_on,
					"comments": comments,
					"issue_id": str(issue_id),
					#"activity_id": str(activity_id),
					"custom_fields": [{
						"id": str(custom_field_id),
						"value": unicode(event.get('UID'))
					}]
				})
				self.save()
		else:
			log.debug("[ ] Nothing has changed: Skipping.")

class Users(RedmineActiveResource):
	_singular = 'user'
	

class ICal2RedmineProcessor:
	# Fields related to configurations.
	settings = {
		"redmine_url": None,
		"update_existing_entries": False,
		"insert_future_events": False,
		"custom_time_entry_field_id": None,
		"custom_user_field_id": None,
		"since": None,
		"subscriptions": []
	}

	redmine_entries = None
	
	def __init__(self, custom_settings = dict()):
		log.debug("===== Initializing =====")
		self.settings.update(custom_settings)

		self.sanity_check_settings()

		# Compiling the regular expressions of the mappings.
		self.compile_regular_expressions()

		if self.settings["since"]:
			self.settings["since"] = datetime.datetime.strptime(self.settings["since"], "%m/%d/%Y").replace(tzinfo=pytz.UTC)
			log.info("Any event before %s will be skipped.", self.settings["since"].ctime())

		# Setting up active resources.
		RedmineActiveResource._site = self.settings["redmine_url"]
		TimeEntries._since = self.settings["since"]

	def process(self):
		log.debug("===== Processing iCal subscriptions =====")
		processed_event_uids = []
		parsed_user_ids = []

		for subscription in self.settings["subscriptions"]:
			result = self.process_subscription(subscription["user_id"], subscription["api_key"])
			if result != None and result != False:
				processed_event_uids.extend(result)
				parsed_user_ids.append(subscription["user_id"])

		log.info("A total of %u iCal events was found when parsing the subscriptions.", len(processed_event_uids))

		if self.settings["update_existing_entries"]:
			log.debug("===== Processing Redmine Time entries =====")
			for uid, entry in self.redmine_entries.items():
				if uid not in processed_event_uids:
					# Found a ical2redmine time entry which was not touched duing the iCal parsing.
					# Does this belong to a user which was parsed?
					if int(entry.user.id) in parsed_user_ids:
						spent_on = dateutil.parser.parse(entry.spent_on)
						# And is it within the time period we are interested in?
						if self.settings["since"] == None or self.settings["since"].replace(tzinfo=None) <= spent_on:
							log.debug("[-] Removing an ical2redmine time entry (#%u) which was removed from the iCal feed.", int(entry.id))
							entry.destroy()


	def process_subscription(self, user_id, api_key):
		log.debug("Processing user #%u using API key: %s", user_id, api_key)
		# Update the active resources
		RedmineActiveResource._user = api_key
		# Get this users real name
		users = Users.find(user_id = user_id)
		for user in users:
			if user.id == str(user_id):
				# Found the one
				return self.process_user(user)
		log.error("No user with this id (%u) was found on the redmine web service.", user_id)

	def process_user(self, user):
		log.info("----- Processing %s %s (%u) -----", user.firstname, user.lastname, int(user.id))
		processed_event_uids = []

		if self.redmine_entries == None:
			log.debug("Starting by fetching all existing redmine time entries.")
			self.redmine_entries = self.fetch_redmine_time_entries()

		log.debug("Loading iCal feed and performing sanity checks:")
		ical_url = user.get_custom_field_value(self.settings["custom_user_field_id"])
		if ical_url == None or ical_url == "":
			log.info("It seems that %s, hasn't specified an iCal feed URL on his Redmine profile.", user.firstname)
		else:
			ical_events = self.fetch_ical_events(ical_url)
			for event_uid, event in ical_events.items():
				summary = unicode(event.get('SUMMARY'))
				match = self.settings["pattern"].match(summary)
				if match != None:
					# We've got a relevant iCal event
					try:
						issue_id = match.group('issue_id')
					except Exception as e:
						log.error("Make sure to have an issue_id named group in the pattern.")
						return False
					log.debug("iCal event '%s' (%s) matches issue id #%u", summary, event_uid, int(issue_id))
					self.process_event(event, int(issue_id))
					processed_event_uids.append(event_uid)
		return processed_event_uids

	def process_event(self, event, issue_id):
		uid = str(event.get('UID'))
		if uid in self.redmine_entries.keys():
			entry = self.redmine_entries[uid]
		else:
			entry = TimeEntries()
		entry.update_from_ical(event, issue_id, self.settings["custom_time_entry_field_id"])

	def sanity_check_settings(self):
		# redmine_url
		assert self.settings["redmine_url"], "The redmine_url parameter was not sat."
		log.debug("Redmine URL: %s", self.settings["redmine_url"])
		# subscriptions
		assert self.settings["subscriptions"], "The subscriptions parameter was not sat."
		log.debug("Processing with %u API key(s):", len(self.settings["subscriptions"]))
		for user_number, entry in enumerate(self.settings["subscriptions"]):
			assert entry["user_id"], "An entry in the subscriptions list had no user_id value."
			assert entry["api_key"], "An entry in the subscriptions list had no api_key value."
			log.debug("[%u/%u] User #%u: %s", user_number+1, len(self.settings["subscriptions"]), entry["user_id"], entry["api_key"])
		# custom_time_entry_field_id
		assert self.settings["custom_time_entry_field_id"], "The custom_time_entry_field_id was not sat."
		log.debug("Using the time entry custom field with id = %u", self.settings["custom_time_entry_field_id"])
		self.settings["custom_time_entry_field_id"] = int(self.settings["custom_time_entry_field_id"])
		# custom_user_field_id
		assert self.settings["custom_user_field_id"], "The custom_user_field_id was not sat."
		log.debug("Using the user custom field with id = %u", self.settings["custom_user_field_id"])
		self.settings["custom_user_field_id"] = int(self.settings["custom_user_field_id"])

	def compile_regular_expressions(self):
		self.settings["pattern"] = re.compile(self.settings["pattern"])
		assert self.settings["pattern"], "The pattern didn't compile."

	def fetch_ical_events(self, ical_url):
		try:
			ical_handle = urllib2.urlopen(ical_url)
			ical_string = ical_handle.read()
			ical_feed = Calendar.from_ical(ical_string)

			name = ical_feed.get("X-WR-CALNAME")
			description = ical_feed.get("X-WR-CALDESC")
			if name and description:
				log.debug("Succeeded: Loaded '%s' (%s).", name, description)
			elif name:
				log.debug("Succeeded: Loaded '%s'.", name)
			else:
				log.debug("Succeeded: Loaded an unnamed calendar.")

			# Inserting events into a dictionary.
			ical_events = dict()
			for event in ical_feed.walk("VEVENT"):
				ical_events[str(event.get('UID'))] = event
			
			log.debug("Found %u ical events.", len(ical_events))
			return ical_events

		except Exception as e:
			log.error("Failed to fetch ical feed (%s): %s", ical_url, e)
			sys.exit(-1)

	def fetch_redmine_time_entries(self):
		log.info("Fetching all time entries from Redmine")
		redmine_entries = dict()
		offset = 0
		temp_entries = TimeEntries.find()
		while len(temp_entries) > 0:
			log.debug("Finding time entries with offset = %u", offset)
			for entry in temp_entries:
				if entry.is_ical2redmine(self.settings["custom_time_entry_field_id"]):
					entry_uid = entry.get_custom_field_value(self.settings["custom_time_entry_field_id"])
					if entry_uid in redmine_entries.keys():
						log.warning("Doublicate time entry in Redmine #%s represents %s, which is already represented by Redmine #%s.", entry.id, entry_uid, self.redmine_entries[entry_uid].id)
						# TODO: Consider that this might just be a sumptom of a recurring event.
					else:
						redmine_entries[entry_uid] = entry
				offset += 1
			temp_entries = TimeEntries.find(offset = offset)
		log.debug("Found %u ical2redmine time entries on Redmine.", len(redmine_entries))
		return redmine_entries

	'''
	def iterate_entries(self):
		log.info("Iterating Redmine time entries:")
		for uid, entry in self.redmine_entries.items():
			log.debug("\tProcessing Redmine time entry %s", uid)
			if uid in self.ical_events.keys():
				event = self.ical_events[uid]
				# Update this entry from the ical information.
				mapping = self.determine_mapping(event)
				if mapping == None:
					log.info("\t[-] No mapping matches this entry (%s): It will be deleted.", uid)
					entry.destroy()
				else:
					log.info("\t[+] A mapping matches this entry (%s): It will be updated.", uid)
					entry.update_from_ical(event, mapping["issue"], mapping["activity"], mapping["prepend_comments"])
			else:
				log.info("\t[-] This entry (%s) in no longer in the ical feed: It will be deleted.", uid)
				entry.destroy()
	'''
	'''
	def iterate_events(self):
		log.info("Iterating ical events (%u left):", len(self.ical_events))
		# TODO: Remember the self.insert_future_events option.
		for uid, event in self.ical_events.items():
			log.debug("\tProcessing ical event %s", uid)
			mapping = self.determine_mapping(event)
			if mapping:
				log.info("\t[+] A mapping matches this event (%s): Maybe it should be created?", uid)

	'''

if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument('-s', '--settings', help='The settings to use for creating time entries.', required=True)
	parser.add_argument('-l', '--log', help='Set the log level to debug.', default='WARNING')
	args = parser.parse_args()

	numeric_level = getattr(logging, args.log.upper(), None)
	if not isinstance(numeric_level, int):
		raise ValueError('Invalid log level: %s' % args.log)
	logging.basicConfig(format='%(levelname)s\t%(message)s', level=numeric_level)

	print " _             _  ______                  _       _             "
	print "(_)           | |(_____ \                | |     (_)            "
	print " _  ____ _____| |  ____) ) ____ _____  __| |____  _ ____  _____ "
	print "| |/ ___|____ | | / ____/ / ___) ___ |/ _  |    \| |  _ \| ___ |"
	print "| ( (___/ ___ | || (_____| |   | ____( (_| | | | | | | | | ____|"
	print "|_|\____)_____|\_)_______)_|   |_____)\____|_|_|_|_|_| |_|_____) v.0.2\n"
	log.info("Loading settings from: %s", args.settings)
	try:
		settings_handle = open(args.settings, 'r')
		settings = json.loads(settings_handle.read())
	except Exception as e:
		log.error("Couldn't load settings file: %s" % e)
		sys.exit(-1)

	processor = ICal2RedmineProcessor(settings)
	processor.process()

