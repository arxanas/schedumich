#!/usr/bin/env python3
import contextlib
import datetime
import itertools
import logging
import pickle
import time

import umich

ACCESS_KEY = "Bearer 9db6e46fefd3a89ab15405e63abda3c"
"""The access token to use for the API.

This particular one is for the 'Bar' app. In my infinite wisdom I have set
it to last for a year.

"""


class ClassPicker:
    """Picks classes as according to some arbitrary criteria."""

    def __init__(self, class_api, building_api):
        """Constructor.

        class_api: The ClassAPI instance.
        building_api: The BuildingAPI instance.

        """
        self.class_api = class_api
        self.building_api = building_api

    def _get_section_choices(self, section_groups):
        """Transform a list of section groups into its sections.

        Returns a list of lists of sections. In order to complete the schedule,
        one section from each section list must be chosen.

        """
        ret = []
        for section_group in section_groups.values():
            for section_type in section_group.section_types:
                ret.append([
                    i
                    for i
                    in section_group.section_list
                    if i.section_type == section_type
                ])
        return ret

    def _get_section_groups(self, section_group_names, season):
        section_groups = {}
        for i in section_group_names:
            term = umich.Term.from_season(self.class_api, season)
            section_groups[i] = term.get_section_group(i)
        return section_groups

    def pick_sections(self, section_group_names, season):
        section_choices = self._get_section_choices(self._get_section_groups(
            section_group_names, season
        ))

        def times_dont_overlap(candidate):
            for s1, s2 in itertools.combinations(candidate, 2):
                if s1.meeting_time.conflicts_with(s2.meeting_time):
                    return False
            return True

        def buildings_arent_too_far_away(candidate):
            # Minimum time between classes on different campuses.
            TIME_BETWEEN_CAMPUSES = datetime.timedelta(minutes=30)

            def get_building(section):
                return umich.Building.from_section(self.building_api, section)

            for s1, s2 in itertools.combinations(candidate, 2):
                s1_building = get_building(s1)
                s2_building = get_building(s2)

                # They don't both have assigned locations, so we can't tell
                # right now. In that case, we assume that they don't conflict.
                if not s1_building or not s2_building:
                    continue

                # If they're on the same campus, we can't have a timing conflict
                # between them.
                if s1_building.campus_name == s2_building.campus_name:
                    continue

                # If they're not on the same day, we can't have a timing
                # conflict.
                if not(
                    set(s1.meeting_time.day_list) & 
                    set(s2.meeting_time.day_list)
                ):
                    continue

                # Order them with respect to time.
                s1, s2 = sorted(
                    [s1, s2],
                    key=lambda x: x.meeting_time.time_begin
                )

                # They're on different campuses, so make sure they're far
                # enough apart in time.
                time_difference = umich.MeetingTime.time_difference(
                    s1.meeting_time.time_end,
                    s2.meeting_time.time_begin
                )
                if time_difference < TIME_BETWEEN_CAMPUSES:
                    return False
            return True

        return [
            i
            for i
            in itertools.product(*section_choices)
            if times_dont_overlap(i)
            if buildings_arent_too_far_away(i)
            if buildings_arent_too_far_away(i)
        ]


    class ScheduleCanvas:
        DAYS = ["Mo", "Tu", "We", "Th", "Fr"]

        # Block time, in seconds. 30 minutes.
        RESOLUTION = 30 * 60

        # Block height, in rows.
        BLOCK_HEIGHT = 4

        # The number of blocks in the schedule frame.
        NUM_BLOCKS = 24

        # The time to start the schedule, in seconds. 8 AM.
        START_TIME = 8 * 60 * 60

        # The padding in the block on either side.
        BLOCK_PADDING = 2

        def __init__(self, maximum_section_length):
            # The width of a column in the schedule frame.
            self.column_width = (
                maximum_section_length + 
               (2 * self.BLOCK_PADDING)
            )

            self.frame_width = (self.column_width * len(self.DAYS)) + 1

            # Four per block; and 24 thirty-minute periods in the day.
            self.frame_height = self.BLOCK_HEIGHT * self.NUM_BLOCKS

            # "11:00 AM" is eight characters long, and there's one character
            # for padding at the left.
            self.time_width = 8 + 1

            self.width = self.frame_width + self.time_width
            self.height = self.frame_height

            self.canvas = [
                [" "] * self.width
                for i
                in range(self.height)
            ]

            # Draw the frame.
            self._draw_box(
                (0, 0),
                (self.frame_height - 1, self.frame_width - 1)
            )

            # Draw the time markers.
            for i in range(self.NUM_BLOCKS):
                timestamp = self.START_TIME + (i * self.RESOLUTION)
                block_time = time.gmtime(timestamp)
                block_time_string = time.strftime(
                    " %I:%M %p",
                    block_time
                )
                self._draw_string((
                    i * self.BLOCK_HEIGHT,
                    self.frame_width,
                ), block_time_string)

        def __getitem__(self, index):
            row, column = index
            return self.canvas[row][column]

        def __setitem__(self, index, value):
            row, column = index
            self.canvas[row][column] = value

        def add_section(self, section):
            def seconds_to_blocks(seconds):
                seconds //= self.RESOLUTION
                seconds *= self.BLOCK_HEIGHT
                return seconds

            for day in section.meeting_time.day_list:
                height = seconds_to_blocks(umich.MeetingTime.time_difference(
                    time.gmtime(self.START_TIME),
                    section.meeting_time.time_begin
                ).seconds)
                top_left = (
                    height,
                    self.column_width * self.DAYS.index(day),
                )

                height = seconds_to_blocks(section.meeting_time.length.seconds)
                bottom_right = (
                    top_left[0] + height,
                    top_left[1] + self.column_width,
                )

                self._draw_box(top_left, bottom_right)

                # Try to center the string, roughly.
                row = (top_left[0] + bottom_right[0]) // 2
                column = top_left[1] + self.BLOCK_PADDING
                self._draw_string((
                    row - 1,
                    column,
                ), section.code)
                self._draw_string((
                    row,
                    column,
                ), section.section)


        def _draw_box(self, top_left, bottom_right):
            """Draws a box from the top left to bottom right corner.

            top_left: A tuple of (row, column).
            bottom_right: A tuple of (row, column).

            """
            top_right = (top_left[0], bottom_right[1])
            bottom_left = (bottom_right[0], top_left[1])

            self._draw_line(top_left, top_right)
            self._draw_line(top_left, bottom_left)
            self._draw_line(bottom_left, bottom_right)
            self._draw_line(top_right, bottom_right)

        def _draw_line(self, start_point, end_point):
            """Draws a line like "+-----+" from the start to end point.

            The line has "+" at either endpoint and is connected by "-" or
            "|"s. It should be a straight line, which is to say the the start
            and end point share either a row or column.

            start_point: The starting point for the line. Should be to the
                upper-left of the end point.
            end_point: The ending point for the line.

            """
            start_point, end_point = sorted([start_point, end_point])

            line_characters = {
                (1, 0): "|",
                (0, 1): "-",
                (1, 1): "\\",
            }

            current_point = start_point
            while current_point != end_point:
                # Decide the delta for the point.
                d_row = 0
                d_column = 0
                if start_point[0] < end_point[0]:
                    d_row = 1
                if start_point[1] < end_point[1]:
                    d_column = 1
                assert d_row or d_column, \
                       "Could not figure out which direction to go " \
                       "when drawing a line."
                
                # Apply the delta and draw the character.
                current_point = (
                    current_point[0] + d_row,
                    current_point[1] + d_column,
                )

                if self[current_point] != "+":
                    self[current_point] = line_characters[d_row, d_column]

            self[start_point] = "+"
            self[end_point] = "+"

        def _draw_string(self, point, string):
            """Draws a string starting at `point`.

            point: The point where the string starts. The first character of
                the string is placed at this point.
            string: The string to print. It must fit within the bounds of the
                canvas.

            """
            self[point] = string[0]

            # Draw the remaining characters of the string at the point one
            # column over.
            if string[1:]:
                self._draw_string((
                    point[0],
                    point[1] + 1,
                ), string[1:])

        def print(self):
            for i in range(self.height):
                string = ""
                for j in range(self.width):
                    string += self[i, j]
                print(string)


    @staticmethod
    def print_schedule(schedule):
        print(schedule)
        longest_code_length = max(
            len(i.code)
            for i
            in schedule
        )

        canvas = ClassPicker.ScheduleCanvas(longest_code_length)
        for i in schedule:
            canvas.add_section(i)
        canvas.print()

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


class Input:
    """Gets input from the user."""

    @staticmethod
    def get_section_group_names():
        """Get the section groups which the user wants to enroll in."""
        return [
            "EECS 281",
            "EECS 376",
            "LATIN 102",
            "STATS 412",
        ]

    @staticmethod
    def get_season():
        """Get the season for the term to enroll in."""
        return "FA 2014"


def main():
    logging.basicConfig(level=logging.INFO)

    with make_cache("class_api.cache") as class_api_cache:
        with make_cache("building_api.cache") as building_api_cache:
            class_api = umich.ClassAPI(
                access_key=ACCESS_KEY,
                cache=class_api_cache
            )
            building_api = umich.BuildingAPI(
                access_key=ACCESS_KEY,
                cache=building_api_cache
            )

            # Get input.
            section_group_names = Input.get_section_group_names()
            season = Input.get_season()

            # Find schedules.
            class_picker = ClassPicker(class_api, building_api)
            schedules = class_picker.pick_sections(section_group_names, season)
            for i in schedules:
                ClassPicker.print_schedule(i)
                input()

if __name__ == "__main__":
    main()

