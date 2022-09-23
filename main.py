import argparse
from datetime import datetime
import logging
import random
from typing import List, Dict
import requests
import time

import yagmail as yagmail

from secrets import APP_PASS, SEND_TO, SEND_FROM

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)

REQUEST_DELAY = 2
TIMESLOT_URL = "https://ttp.cbp.dhs.gov/schedulerapi/slots?orderBy=soonest&limit={limit}&locationId={location_id}&minimum=1"
MAPPING_URL = "https://ttp.cbp.dhs.gov/schedulerapi/locations/?temporary=false&inviteOnly=false&operational=true&serviceName=Global%20Entry"


def delay() -> float:
    return REQUEST_DELAY + random.randint(-10, 10) / (10 * REQUEST_DELAY / 2)  # jitter


def make_request(url: str):
    resp = requests.get(url)
    if resp.status_code != 200:
        raise ValueError(f'Non-200 code returned ({resp.status_code}): {resp.json()}')

    return resp.json()


def import_mapping_from_url() -> Dict[int, str]:
    """Get mapping of location ids to location names from the TTP website."""
    resp_dict = make_request(MAPPING_URL)
    return {
        location["id"]: "{} ({}, {})".format(
            location["name"], location["city"], location["state"]
        )
        for location in resp_dict
    }


def parse_timeslot_datetime(timeslot: dict) -> datetime:
    """Parse the timestamp of a single timeslot."""
    return datetime.strptime(timeslot["startTimestamp"], "%Y-%m-%dT%H:%M")


def get_timeslots_for_location_id(location_id: int, limit: int) -> List[datetime]:
    """Get list of objects representing open slots for a certain location."""
    resp_dict = make_request(TIMESLOT_URL.format(location_id=location_id, limit=limit))

    timeslots = [parse_timeslot_datetime(timeslot) for timeslot in resp_dict]
    return sorted(list(set(timeslots)))


def get_timeslots_for_location_ids(location_ids: List[int], before: str = None, limit: int = 10,
                                   ) -> Dict[int, List[datetime]]:
    """Get a mapping of location ids to open timeslots. Takes in an optional YYYY-MM-DD
    parameter to filter the results."""
    all_timeslots = {}
    for location_id in location_ids:
        timeslots = [
            timeslot
            for timeslot in get_timeslots_for_location_id(location_id, limit)
            if before is None or timeslot < datetime.strptime(before, "%Y-%m-%d")
        ]
        all_timeslots[location_id] = timeslots
        time.sleep(delay())

    return all_timeslots


def generate_notification_texts(location_mapping: Dict[int, str], all_timeslots: Dict[int, List[datetime]],
                                silent: bool) -> List[str]:
    """Generate the text for the notification."""
    notification_texts = ["✈️ Global Entry Timeslot Bot ✈️"]
    for location_id, timeslots in all_timeslots.items():
        if len(timeslots) > 0:
            location_texts = [f"{location_mapping[location_id]} ({location_id})"]
            for timeslot in timeslots:
                location_texts.append(
                    f'    {timeslot.strftime("%B %d, %Y (%a) @ %I:%M %p").replace(" 0", " ")}'
                )
            notification_texts.append("\n".join(location_texts))
    if len(notification_texts) == 1:
        if silent:
            return []
        else:
            notification_texts.append("No open timeslots found!")
    return notification_texts


def send(notification_texts: List[str]):
    """Send a notification to Discord."""
    for message in notification_texts:
        print(message)

    yag = yagmail.SMTP(user=SEND_FROM, password=APP_PASS)
    yag.send(to=SEND_TO, subject='Global Entry - book Quick!', contents=notification_texts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--location-ids", '-l',
        action='append',
        type=int,
        default=[],
        help="List of location ids to check",
        required=True,
    )
    parser.add_argument(
        "--before",
        type=str,
        help="YYYY-MM-DD string of the date to filter results before",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Limit of appointments to fetch, per location",
    )
    parser.add_argument(
        "--silent",
        default=False,
        action="store_true",
        help="Suppress notifications if there are no open timeslots",
    )

    args = parser.parse_args()

    loc_mapping = import_mapping_from_url()

    keep_running = True
    while keep_running:
        ats = get_timeslots_for_location_ids(args.location_ids, args.before, args.limit)
        if any(val for val in ats.values()):
            keep_running = False
        else:
            time.sleep(delay())

    notification_text = generate_notification_texts(loc_mapping, ats, args.silent)
    send(notification_text)
