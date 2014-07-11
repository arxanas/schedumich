#!/usr/bin/env python3
import logging

import umichsched.scheduler as scheduler
import umichsched.umich as umich


def get_api_key():
    """Get the access token to use for the umich API."""
    with open("access_token") as f:
        return f.read().strip()


class Input:
    """Gets input from the user."""

    @staticmethod
    def get_section_group_names():
        """Get the section groups which the user wants to enroll in."""
        return [
            "EECS 281",
            "EECS 370",
        ]

    @staticmethod
    def get_season():
        """Get the season for the term to enroll in."""
        return "FA 2014"

LUNCH = umich.MeetingTime.from_days_and_times(
    "MoTuWeThFr",
    "11:00AM - 12:00PM"
)


def doesnt_conflict_with_lunch(candidate):
    for section in candidate:
        if section.meeting_time.conflicts_with(LUNCH):
            return False
    return True


def main():
    logging.basicConfig(level=logging.INFO)

    with umich.make_cache("class_api.cache") as class_api_cache:
        with umich.make_cache("building_api.cache") as building_api_cache:
            access_key = get_api_key()
            class_api = umich.ClassAPI(
                access_key=access_key,
                cache=class_api_cache
            )
            building_api = umich.BuildingAPI(
                access_key=access_key,
                cache=building_api_cache
            )
            section_group_names = Input.get_section_group_names()
            season = Input.get_season()

            class_picker = scheduler.ClassPicker(class_api, building_api)
            schedules = class_picker.pick_sections(section_group_names, season)

            # Add our lunchtime.
            class_picker.add_criterion(doesnt_conflict_with_lunch)

            # Display all the schedules to the user, one-by-one.
            for i in schedules:
                scheduler.print_schedule(i)
                if input() == "q":
                    break

if __name__ == "__main__":
    main()
