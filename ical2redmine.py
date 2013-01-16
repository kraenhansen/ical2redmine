import sys
sys.path.remove('/usr/local/lib/python2.7/dist-packages/pyactiveresource-1.0.2-py2.7.egg')

import argparse
import urllib2
from icalendar import Calendar, Event
from pyactiveresource.activeresource import ActiveResource
from pyactiveresource import formats
import json
import re
import logging
import datetime
import pytz

log = logging.getLogger(__name__)
logging.getLogger('pyactiveresource').setLevel(logging.WARNING)

class TimeEntries(ActiveResource):
	_site = None
	_user = None
	_singular = 'time_entry'
	
	# Changing the default values.
	def to_xml(self, root=None, header=True, pretty=False, dasherize=False):
		return super(TimeEntries, self).to_xml(root=root, header=header, pretty=pretty, dasherize=dasherize)

	def get_ical_uid(self, raiseExceptionIfNoCustomField = True):
		if "custom_fields" in self.to_dict().keys():
			for field in self.custom_fields:
				#print type(field.attributes)
				if field.name == "ical2redmine_uid":
					return field.value
		if raiseExceptionIfNoCustomField:
			raise Exception("Cannot get the ical_uid, because the 'ical2redmine_uid' custom field was not present.")
		else:
			return None

	def is_ical2redmine(self):
		return self.get_ical_uid(False) is not None

	def update_from_ical(self, event, issue_id, activity_id, user_id, prepend_comments = ""):
		assert issue_id, "issue_id cannot be None."
		assert activity_id, "activity_id cannot be None."
		assert user_id, "user_id cannot be None."
		assert prepend_comments != None, "prepend_comments cannot be None."

		comments = unicode(event.get('DESCRIPTION')).replace("\n", " ") + prepend_comments
		start = event.get('DTSTART').dt
		end = event.get('DTEND').dt
		duration = end - start
		hours = duration.total_seconds() / (60 * 60)

		if start > datetime.datetime.now(pytz.UTC):
			# We want bother with events in the future.
			if self.id:
				log.info("\t\tDeleting entry #%s because the event was moved to the future.", self.id)
				self.delete()
			else:
				log.info("\t\tSkipping creating an entry because the event was in the future.")
				return

		spent_on = start.date().isoformat()

		if self.id:
			# Check if something has changed.
			has_changed = self.hours != str(hours) or \
				self.spent_on != spent_on or \
				self.comments != comments
		else:
			has_changed = True

		if has_changed:
			if self.id:
				log.debug("\tSome things have changed, saving time entry #%s", self.id)
				self._update({
					"hours": str(hours),
					"spent_on": spent_on,
					"comments": comments
				})
				self.save()
			else:
				log.debug("\tThis will be created.")
				self._update({
					"hours": str(hours),
					"spent_on": spent_on,
					"comments": comments,
					"issue_id": str(issue_id),
					"activity_id": str(activity_id),
					"custom_fields": [{
						"id": str(ICal2RedmineProcessor.custom_field_id),
						"value": unicode(event.get('UID'))
					}]
				})
				self.save()
		else:
			log.debug("\tNothing has changed: Skipping.")

class ICal2RedmineProcessor:
	ical_url = None
	redmine_url = None
	redmine_api_key = None
	update_existing_entries = False
	insert_future_events = False
	custom_field_id = None
	mappings = list()

	ical = None
	redmine_entries = None
	ical_events = None
	
	def __init__(self, settings = dict()):
		self.__dict__.update(settings)
		ICal2RedmineProcessor.custom_field_id = self.custom_field_id

	def process(self):
		self.sanity_check_settings()
		log.debug("The ical2redmine processor was started, with these settings:")
		log.debug("\tiCal: %s", self.ical_url)
		log.debug("\tRedmine: %s", self.redmine_url)
		log.debug("\tRedmine API-key: %s", self.redmine_api_key)

		for mapping in self.mappings:
			if "prepend_comments" not in mapping.keys():
				# The default prepend_comments value, is an empty string.
				mapping["prepend_comments"] = ""
				
		# Compiling the regular expressions of the mappings.
		self.compile_regular_expressions()

		log.debug("Loading iCal feed and performing sanity checks:")
		self.fetch_ical()

		log.debug("Performing sanity checks on Redmine:")
		TimeEntries._site = self.redmine_url
		TimeEntries._user = self.redmine_api_key
		self.sanity_check_redmine()
		self.fetch_redmine_time_entries()

		log.debug("Pre processing is done.")

		if self.update_existing_entries:
			self.iterate_entries()
			for uid in self.redmine_entries.keys():
				del self.ical_events[uid] # As this was already updated.

		self.iterate_events()
		# self.entries = TimeEntries.find(limit = 100, offset = 59)

	def sanity_check_settings(self):
		assert self.ical_url, "The ical_url parameter was not sat."
		assert self.redmine_url, "The redmine_url parameter was not sat."
		assert self.redmine_api_key, "The redmine_api_key parameter was not sat."

	def compile_regular_expressions(self):
		for mapping in self.mappings:
			if "vevent_summary_pattern" in mapping.keys():
				mapping["vevent_summary_pattern"] = re.compile(mapping["vevent_summary_pattern"])
			if "vevent_description_pattern" in mapping.keys():
				mapping["vevent_description_pattern"] = re.compile(mapping["vevent_description_pattern"])
			if "vevent_location_pattern" in mapping.keys():
				mapping["vevent_location_pattern"] = re.compile(mapping["vevent_location_pattern"])

	def fetch_ical(self):
		try:
			assert self.ical_url, 'The iCal URL has to be sat.'
			# = httplib.HTTPConnection(self.ical_url)
			ical_handle = urllib2.urlopen(self.ical_url)
			ical_string = ical_handle.read()
			self.ical = Calendar.from_ical(ical_string)

			name = self.ical.get("X-WR-CALNAME")
			description = self.ical.get("X-WR-CALDESC")
			if name and description:
				log.info("Succeeded: Loaded '%s' (%s).", name, description)
			elif name:
				log.info("Succeeded: Loaded '%s'.", name)
			else:
				log.info("Succeeded: Loaded an unnamed calendar.")

			# Inserting events into a dictionary.
			self.ical_events = dict()
			for event in self.ical.walk("VEVENT"):
				self.ical_events[str(event.get('UID'))] = event
		except Exception as e:
			log.error("Failed to fetch ical feed: %s", e)
			sys.exit(-1)

	def sanity_check_redmine(self):
		try:
			assert self.redmine_url, 'The RedIssuemine URL has to be sat.'
			assert self.redmine_api_key, 'The Redmine API Key has to be sat.'
			# = httplib.HTTPConnection(self.ical_url)
			entries = TimeEntries.find(limit = 0)
			if entries == None:
				raise Exception("The Redmine service seems to be strange, or no .")
		except Exception as e:
			log.error("Redmine sanity check failed: %s", e)
			sys.exit(-1)

	def fetch_redmine_time_entries(self):
		log.info("Fetching all time entries from Redmine")
		self.redmine_entries = dict()
		offset = 0
		temp_entries = TimeEntries.find()
		while len(temp_entries) > 0:
			for entry in temp_entries:
				if entry.is_ical2redmine():
					entry_uid = entry.get_ical_uid()
					if entry_uid in self.redmine_entries.keys():
						log.warning("Doublicate time entry in Redmine #%s represents %s, which is already represented by Redmine #%s.", entry.id, entry_uid, self.redmine_entries[entry_uid].id)
					else:
						self.redmine_entries[entry.get_ical_uid()] = entry
				offset += 1
			temp_entries = TimeEntries.find(offset = offset)
		log.info("Found %u ical2redmine time entries on Redmine.", len(self.redmine_entries))

	def determine_mapping(self, event):
		summary = unicode(event.get('SUMMARY'))
		description = unicode(event.get('DESCRIPTION'))
		location = unicode(event.get('LOCATION'))
		for mapping in self.mappings:
			if "vevent_summary_pattern" in mapping.keys() and mapping["vevent_summary_pattern"].match(summary) == None:
				continue
			elif "vevent_description_pattern" in mapping.keys() and mapping["vevent_description_pattern"].match(description) == None:
				continue
			elif "vevent_location_pattern" in mapping.keys() and mapping["vevent_location_pattern"].match(location) == None:
				continue
			else:
				return mapping
		return None

	def iterate_entries(self):
		log.info("Iterating Redmine time entries:")
		for uid, entry in self.redmine_entries.items():
			log.info("\tProcessing Redmine time entry #%s", uid)
			if uid in self.ical_events.keys():
				event = self.ical_events[uid]
				# Update this entry from the ical information.
				mapping = self.determine_mapping(event)
				if mapping == None:
					log.info("\t\t[-] No mapping matches this entry: It will be deleted.")
					entry.destroy()
				else:
					log.info("\t\t[+] A mapping matches this entry: It will be updated.")
					entry.update_from_ical(event, mapping["issue"], mapping["activity"], mapping["user"], mapping["prepend_comments"])
			else:
				log.info("\t\t[-] This entry in no longer in the ical feed: It will be deleted.")
				entry.destroy()

	def iterate_events(self):
		log.info("Iterating ical events:")
		# TODO: Remember the self.insert_future_events option.
		for uid, event in self.ical_events.items():
			log.info("\tProcessing ical event #%s", uid)
			mapping = self.determine_mapping(event)
			if mapping:
				log.info("\t\t[+] A mapping matches this event: Maybe it should be created?")
				entry = TimeEntries()
				entry.update_from_ical(event, mapping["issue"], mapping["activity"], mapping["user"], mapping["prepend_comments"])

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
	print "|_|\____)_____|\_)_______)_|   |_____)\____|_|_|_|_|_| |_|_____)\n"
	log.info("Loading settings from: %s", args.settings)
	try:
		settings_handle = open(args.settings, 'r')
		settings = json.loads(settings_handle.read())
	except Exception as e:
		log.error("Couldn't load settings file: %s" % e)
		sys.exit(-1)

	processor = ICal2RedmineProcessor(settings)
	processor.process()

