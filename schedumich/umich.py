#!/usr/bin/env python3
import collections
import contextlib
import datetime
import functools
import json
import logging
import operator
import pickle
import requests
import time

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


# Sometimes (read: often) the class location and building abbreviation may not
# sync up. The key is the class location and the value is the building
# abbreviation.
EXTRA_ABBREVIATIONS = {
    "GFL": "GFLAB",
    "BEYSTER": "BYSTR",
    "STAMPS": "STAMP",
}


class retry(object):
    """Handles retrying the request.

    It's easily possible that we'll exceed the rate-limiting, so in
    the event of a failure, we sleep for a while and try again.

    """
    def __init__(self, tries, wait_time, caught_errors):
        """Constructor.

        tries: The maximum number of tries to make before giving up.
            When giving up, the received error is rethrown.
        wait_time: The length of time to wait, in seconds.
        caught_errors: A tuple of errors which are allowed to be caught.

        """
        self.tries = tries
        self.wait_time = wait_time
        self.caught_errors = caught_errors

    def __call__(self, func):
        """Decorate the function.

        func: The function to decorate.

        """
        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            remaining_tries = self.tries
            while True:
                try:
                    # Try once more.
                    ret = func()

                    # If we got here, we succeeded! Return as usual.
                    return ret
                except self.caught_errors as e:
                    # If we got here, there was an error which we're supposed
                    # to catch.

                    logging.info(
                        "Function '{func}' failed with {error}: '{message}'. "
                        "{remaining_tries} tries left.".format(
                            func=func.__name__,
                            error=e.__class__.__name__,
                            message=str(e),
                            remaining_tries=remaining_tries
                        )
                    )

                    # Propagate the error if we're out of tries.
                    if remaining_tries <= 0:
                        raise e
                    else:
                        remaining_tries -= 1

                    # Otherwise, sleep and try again.
                    time.sleep(self.wait_time)
        return wrapped


class BaseAPI:
    """Thin wrapper around a umich API.

    A base API for a given umich API. Handles making requests and
    rate-limiting, and allows caching of requests which have been made.

    """
    class APIError(Exception):
        """Generic API error."""
        pass

    class RateLimiter:
        """Limits the rate at which some arbitrary requests are made.

        Not at all thread-safe.

        """
        REQUESTS_PER_TIME = 59
        """The number of requests which are allowed to be made per minute."""

        TIME_SPAN = 60
        """The number of seconds in the time span (which is a minute)."""

        def __init__(self):
            """Constructor."""
            self.request_times = []

        def time_until_next_request(self):
            """Returns the time in seconds until you can make another request.

            To determine if you're allowed to make another request, just check
            to see if this is zero; otherwise, wait for that length of time and
            try again. Returns a float of the number of seconds to wait.

            """
            self._drop_old_requests()
            if len(self.request_times) < self.REQUESTS_PER_TIME:
                return float(0)
            else:
                # The next request can be made after one request leaves the
                # pool, which is 60 seconds after it's happened.
                next_request_time = sorted(
                    self.request_times
                )[0] + self.REQUESTS_PER_TIME

                # Then get the delta.
                return max(0, next_request_time - time.time())

        def request_made(self):
            """Inform the rate limiter that a request was just made."""
            self.request_times.append(time.time())
            self._drop_old_requests()

            logging.info(
                "Request made at time {time}. "
                "Recent requests: {num_requests}. "
                "Time until next request: {next_request_time}".format(
                    time=time.time(),
                    num_requests=len(self.request_times),
                    next_request_time=self.time_until_next_request()
                )
            )

        def _drop_old_requests(self):
            """Forget about requests made a long time ago."""
            self.request_times = [
                i
                for i
                in self.request_times
                if i >= time.time() - self.TIME_SPAN
            ]

    def __init__(self, access_key, cache=None):
        """Constructor.

        access_key: The access token to use for the API. Something like
            "Bearer abcdef1234567890...".

        """
        # Set up the session to authenticate for the API automatically.
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": access_key,
            "Accept": "application/json",
        })

        self.rate_limiter = self.RateLimiter()

        self.cache = cache or {}

    def make_request(self, url):
        """Makes a request and parses its result as JSON.

        Returns the JSON content of the request.

        url: The relative URL to request, like "/Terms".

        """

        cache_key = url
        try:
            return self.cache[cache_key]
        except KeyError:
            pass

        @retry(tries=2, wait_time=60, caught_errors=(ValueError,))
        def try_request():
            self._sleep_until_next_request()
            self.rate_limiter.request_made()
            text = self.session.get(self.URL + url).text
            return json.loads(text)

        try:
            ret = try_request()
            self.cache[cache_key] = ret
            return ret
        except ValueError as e:
            raise self.APIError("Could not authenticate.") from e

    def _sleep_until_next_request(self):
        """Sleep until we're allowed to make another request."""
        time_to_wait = self.rate_limiter.time_until_next_request()
        while time_to_wait:
            time.sleep(time_to_wait)
            time_to_wait = self.rate_limiter.time_until_next_request()


class ClassAPI(BaseAPI):
    URL = "http://api-gw.it.umich.edu/Curriculum/SOC/v1"
    """The API url for the class scheduling info."""


class BuildingAPI(BaseAPI):
    URL = "http://api-gw.it.umich.edu/Facilities/Buildings/v1"
    """The API url for the building info."""


class Building:
    def __init__(self, info):
        self.info = info

    def __repr__(self):
        return (
            "<Building"
            " Abbrev='{abbreviation}'"
            " Name='{name}'"
            " Campus='{campus}'"
            ">".format(
                abbreviation=self.abbreviation,
                name=self.name,
                campus=self.campus_name
            )
        )

    @property
    def abbreviation(self):
        return self.info["Abbreviation"]

    @property
    def name(self):
        return self.info["Name"]

    @property
    def campus_name(self):
        return self.info["Campus"]

    @classmethod
    def from_section(cls, building_api, section):
        """Returns the building where a section is taking place.

        If the section doesn't have a location decided (that is, it's at
        "ARR", to be arranged), returns `None`.

        building_api: The building API.
        section: The class section.

        """
        campuses = building_api.make_request("/Campuses")

        section_building = section.info["Meeting"]["Location"].split()[-1]

        # The building "ARR" means location to be arranged.
        if section_building == "ARR":
            return None

        # We get UMMA AUD instead of AUD UMMA, so we think there's a building
        # called "AUD".
        if "UMMA" in section.info["Meeting"]["Location"]:
            section_building = "UMMA"

        if section_building == "BUS":
            return None

        # Go through each campus and see if it has the given building.
        for i in campuses["Campuses"]["Campus"]:
            buildings = building_api.make_request(
                "/Buildings"
            )["Buildings"]["Building"]
            for j in buildings:
                if j["Abbreviation"] == section_building:
                    return Building(j)

                if (
                    section_building in EXTRA_ABBREVIATIONS and
                    j["Abbreviation"] == EXTRA_ABBREVIATIONS[section_building]
                ):
                    return Building(j)

        raise RuntimeError(
            "Could not find building for section {section}, "
            "which is in building {building}.".format(
                section=section,
                building=section_building
            )
        )


class Term:
    """A class term, e.g. Fall 2014."""
    def __init__(self, class_api, term_info):
        """Constructor.

        class_api: The Class API object.

        """
        self.class_api = class_api

        self.code = term_info["TermCode"]
        self.short_name = term_info["TermShortDescr"]
        self.long_name = term_info["TermDescr"]

    def __repr__(self):
        """Repr."""
        return "<Term Code={code} Name={short_name}>".format(
            code=self.code,
            short_name=self.short_name
        )

    def get_section_group(self, class_code):
        """Gets a `SectionGroup` from its code for the semester.

        class_code: A class code, like "EECS 280".

        """
        def get_all_class_numbers():
            info = self.class_api.make_request(
                "/Terms/{TermCode}/Classes/Search/{SearchCriteria}".format(
                    TermCode=self.code,
                    SearchCriteria=class_code
                )
            )
            # They return a list if there are multiple results, but a dict (of
            # the result) if there is only one result.
            search_results = info["searchSOCClassesResponse"]["SearchResult"]
            if isinstance(search_results, dict):
                search_results = [search_results]
            for i in search_results:
                yield i["ClassNumber"]

        sections = []
        for i in get_all_class_numbers():
            section = Section.from_class_number(self.class_api, self, i)
            if section.code == class_code:
                sections.append(Section.from_class_number(
                    self.class_api,
                    self,
                    i
                ))
        return SectionGroup(sections)

    @classmethod
    def from_season(cls, class_api, season):
        """Makes a Term corresponding to a given season.

        class_api: The ClassAPI instance.
        season: The season code, such as "FA 2014" or "SS 2014".

        """
        terms = class_api.make_request("/Terms")
        term_info = terms["getSOCTermsResponse"]["Term"]

        # If there's only one term, it looks like it will return only a single
        # value instead of a list of values.
        if isinstance(term_info, list):
            term = next(
                i
                for i
                in terms["getSOCTermsResponse"]["Term"]
                if i["TermShortDescr"] == season
            )
        else:
            term = term_info

        return cls(class_api, term)

    @classmethod
    def from_term_code(cls, class_api, term_code):
        """Makes a Term corresponding to the given term code.

        class_api: The ClassAPI instance.
        term_code: The term code.

        """
        terms = class_api.make_request("/Terms")
        return cls(class_api, next(
            i
            for i
            in terms["getSOCTermsResponse"]["Term"]
            if i["TermCode"] == term_code
        ))

    @classmethod
    def from_section(cls, class_api, section):
        return Term.from_term_code(class_api, section.info["TermCode"])


class SectionGroup:
    """A class for a given term, with all of its sections."""
    def __init__(self, section_list):
        """Constructor.

        section_list: The list of `Section`s in this section group.

        """
        self.section_list = section_list
        assert len(section_list), "The section list doesn't have any sections."

        self.section_name = section_list[0].name
        for i in section_list:
            assert i.name == self.section_name, \
                "Not all sections have the same name."

        self.section_types = set(
            i.section_type
            for i
            in self.section_list
        )
        assert self.section_types, "There are no section types."

    def __repr__(self):
        """Repr."""
        return (
            "<SectionGroup"
            " Name={section_name}"
            " Sections={section_types}"
            ">".format(
                section_name=self.section_name,
                section_types=self.section_types
            )
        )


class MeetingTime:
    """A meeting time for a section, like MoWe 10:00 AM - 12:00 PM.

    Doesn't support sections which may have non-homogeneous meeting times. The
    sections for a section group should be treated separately, in which case
    this should be rare.

    """
    def __init__(self, day_list, time_begin, time_end):
        """Constructor.

        day_list: The list of days the section meets on, like ["Mo", "We"].
        time_begin: The time the section begins, like datetime.time(10, 00).
        time_end: The time the section ends, like datetime.time(12, 00).

        """
        self.day_list = day_list
        self.time_begin = time_begin
        self.time_end = time_end

    def __repr__(self):
        def time_as_string(time):
            return "{hour:02d}:{minute:02d}".format(
                hour=time.tm_hour,
                minute=time.tm_min
            )

        return (
            "<MeetingTime"
            " Days={days}"
            " Begin={time_begin}"
            " End={time_end}"
            ">".format(
                days="".join(self.day_list),
                time_begin=time_as_string(self.time_begin),
                time_end=time_as_string(self.time_end)
            )
        )

    @property
    def length(self):
        today = datetime.date.today()
        return datetime.datetime.combine(
            today,
            self.to_datetime_time(self.time_end)
        ) - datetime.datetime.combine(
            today,
            self.to_datetime_time(self.time_begin)
        )

    @staticmethod
    def to_datetime_time(time_struct):
        return datetime.time(
            hour=time_struct.tm_hour,
            minute=time_struct.tm_min
        )

    @staticmethod
    def time_difference(time1, time2):
        today = datetime.date.today()
        time1 = datetime.datetime.combine(
            today,
            MeetingTime.to_datetime_time(time1)
        )
        time2 = datetime.datetime.combine(
            today,
            MeetingTime.to_datetime_time(time2)
        )
        return time2 - time1

    @classmethod
    def from_days_and_times(cls, days, times):
        """Constructor.

        days: The days the section meets, like "MoWe".
        time: The time the section meets, like "10:00AM - 12:00PM".

        """
        # Split the string into two-character snippets.
        day_list = [""]
        for i in days:
            if len(day_list[-1]) == 2:
                day_list.append("")
            day_list[-1] += i

        # Assume the time string is in the format "11:00 AM - 1:00 PM".
        def convert_time(time_str):
            time_str = time_str.strip()
            return time.strptime(time_str, "%I:%M%p")
        time_begin, time_end = list(map(convert_time, times.split("-")))

        return cls(
            day_list,
            time_begin,
            time_end
        )

    def conflicts_with(self, other):
        """Whether or not this meeting time conflicts with another.

        A meeting time conflicts with another meeting time if the first either
        starts or ends during the other's section period on the same day. (They
        can still border each other: this meeting time can end when the other
        starts.)

        other: The other meeting time.

        """
        # They have to meet on the same day to conflict.
        if not(set(self.day_list) & set(other.day_list)):
            return False

        times = [
            (self.time_begin, self.time_end),
            (other.time_begin, other.time_end),
        ]
        times = sorted(times, key=operator.itemgetter(0))

        # If the beginning of the first section is before the end of the second
        # section, they conflict.
        return times[1][0] < times[0][1]


class Section:
    """A single section in a SectionGroup.

    This is one of the lecture or discussion or lab sections.

    """
    def __init__(self, info):
        """Constructor.

        info: The JSON information for the class.

        """
        self.info = info

    def __repr__(self):
        """Repr."""
        return (
            "<Section"
            " Name='{name}'"
            " Code='{code}'"
            " Section='{section}'"
            " Days={days}"
            " Times={times}"
            ">".format(
                name=self.name,
                code=self.code,
                section=self.section,
                days=self.days,
                times=self.times
            )
        )

    @property
    def code(self):
        """The class code, like "EECS 280".

        TODO: Rename to `class_code`.

        """
        return "{subject} {number}".format(
            subject=self.subject,
            number=self.number,
            section_number=self.section_number
        )

    @property
    def days(self):
        """The days on which the section meets, like "MoWeFr"."""
        return self.info["Meeting"]["Days"]

    @property
    def meeting_time(self):
        """The `MeetingTime` for the section."""
        try:
            return self._meeting_time_cached
        except AttributeError:
            self._meeting_time_cached = MeetingTime.from_days_and_times(
                self.days,
                self.times
            )
            return self._meeting_time_cached

    @property
    def name(self):
        """The name of the section, like "Prog&Data Struct"."""
        return self.info["CourseDescr"]

    @property
    def number(self):
        """The number of the class, like "280" for EECS 280."""
        return self.info["CatalogNumber"]

    @property
    def section(self):
        """The section, like DIS-002."""
        return "{section_type} {section_number}".format(
            section_type=self.section_type,
            section_number=self.section_number
        )

    @property
    def section_number(self):
        """The section number for the section, like 022 in EECS 280-022."""
        return self.info["SectionNumber"]

    @property
    def section_type(self):
        """The type of the section, like DIS or LEC."""
        return self.info["SectionType"]

    @property
    def subject(self):
        """The subject code for the class, like EECS."""
        return self.info["SubjectCode"]

    @property
    def times(self):
        """The times for the section, like "10:00 AM - 12:00 PM".

        There's no guarantee on exactly how the date is formatted.

        """
        return self.info["Meeting"]["Times"]

    @classmethod
    def from_class_number(cls, class_api, term, class_number):
        """Constructor.

        The 'class number' in this scenario is unusually named,
        since the usual terminology is 'section'. The various sections are
        identified by 'class numbers', so that is why we use the term 'class
        number and not 'section number'. However, a class number still
        identifies a single section, and not a set of sections which would
        constitute a class, despite its misnomer.

        class_api: The ClassAPI instance.
        term: The `Term` instance.
        class_number: The class number, like 14009.

        """
        info = class_api.make_request(
            "/Terms/{TermCode}/Classes/{ClassNumber}".format(
                TermCode=term.code,
                ClassNumber=class_number
            )
        )
        info = info["getSOCSectionListByNbrResponse"]["ClassOffered"]
        return cls(info)


class FileBackedCache:
    """Cache which saves to a file, which is used for caching API requests."""

    def __init__(self, file_name):
        """Constructor.

        file_name: The name of the cache file.

        """
        self.file_name = file_name

    def __getitem__(self, key):
        """Get a value by key from the cache.

        key: The key corresponding to the value..

        """
        return self.cache[key]

    def __setitem__(self, key, value):
        """Cache a value.

        key: The key for the value.
        value: The value.

        """
        self.cache[key] = value

    def __contains__(self, key):
        """Returns whether or not there is an item with key `key`.

        key: The key of the item.

        """
        return key in self.cache

    def load(self):
        """Load the cache from disk."""
        try:
            with open(self.file_name, "rb") as cache_file:
                self.cache = pickle.load(cache_file)
        except IOError:
            self.cache = {}

    def save(self):
        """Save the cache to disk."""
        with open(self.file_name, "wb") as cache_file:
            pickle.dump(self.cache, cache_file)


@contextlib.contextmanager
def make_cache(file_name):
    """Makes a cache which persists to disk."""
    cache = FileBackedCache(file_name)
    cache.load()
    try:
        yield cache
    finally:
        cache.save()
