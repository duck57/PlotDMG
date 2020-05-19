#!venv/bin/python
# coding=UTF-8
# -*- coding: UTF-8 -*-
# vim: set fileencoding=UTF-8 :

"""
Package to generate plot diagrams from TSV files
The output is a directed multigraph

---------

.tsv expectations
TYPE    NAME    COLOR   *args

TYPE of entry: either Timeline, Event, or Character
NAME of entry, globally unique within its TYPE
COLOR to graph (optional)
*args depend on the TYPE

All Timelines are expected before any Events
Likewise, all Events are expected before any Characters
Violating these may cause Not Found errors

TYPE: Timeline
A universe timeline.
For extensive time-skips in the same universe (think of time travelers from
the Clinton years visiting the mid-Triassic), it may be appropriate to consider
distant past and far future to be different timelines, even if they are connected
:args (at least 1 required) list of place names
must be globally unique among both Timeline and Place names:

TYPE: Event
Something that happened.
:args (2 required)
First, the name of the Timeline or Place where the event occurs
    Placing an event on a Timeline acts as a simultaneity marker (cannot be accessed by characters)
Second, an integer timestamp for ordering relative to the rest of the Timeline or Place
    Timestamps should be unique for each Place
:

TYPE: Character
Someone who moves between Events
:args a list of Events
Dashed connections
    append -( to an event name to dash to next event
    prefix )- to an event name to dash from previous event
:

"""

import click
import csv
from typing import *
import abc


class StoryElement(abc.ABC):
    def __init__(self, name: str, s: "Storyboard", /, **kwargs):
        assert s, f"No story connected with this element"
        assert name, f"Empty name"
        self.story = s
        self.name = name
        self.color = kwargs.get("color")

    @property
    @abc.abstractmethod
    def roster(self) -> "Set[Character]":
        pass

    def __str__(self):
        return self.name


class EventSequence:
    def __init__(
        self,
        es: "Optional[List[Event]]" = None,
        dashed_links: List[bool] = None,
        dash_default: bool = False,
    ):
        self.events = es if es else []
        self.dash_by_default = dash_default
        if dashed_links and es:
            assert len(dashed_links) >= len(es) - 1
            self.dashed_links = dashed_links
        else:
            self.dashed_links: List[bool] = []

    @property
    def latest_event(self) -> "Event":
        return self.events[-1]

    @latest_event.setter
    def latest_event(self, new_event: "Event"):
        self.add_event(new_event, self.dash_by_default)

    def add_event(self, e: "Event", d: bool = False):
        self.events.append(e)
        self.dashed_links.append(d)


class Timeline(StoryElement, EventSequence):
    type = "Timeline"

    def __init__(
        self, story: "Storyboard", name: str, **kwargs,
    ):
        StoryElement.__init__(self, name, story, **kwargs)
        EventSequence.__init__(self)
        assert (
            n := name.lower().strip()
        ) not in story.line_list.keys(), f"{n} already is already a timeline or place"
        story.line_list[n] = self

        self.places: "Set[Place]" = set()

    @property
    def timestamps(self) -> "List[int]":
        """
        This is here instead of in EventSequence because these timestamps would
        make no sense on a Character
        :return: a sorted list of timestamps for the events of a timeline
        """
        return sorted({e.counter for e in self.events})

    @property
    def roster(self) -> "Set[Character]":
        out: "Set[Character]" = set()
        for event in self.events:
            out |= event.roster
        return out

    def __repr__(self):
        return f"Timeline {self.name}"

    def add_event(self, e: "Event", d: bool = False, push_copies: bool = True):
        super().add_event(e, d)
        if push_copies:
            for p in self.places:
                p.add_event(e, push_copies=False)


class Place(Timeline):
    type = "Place"

    def __init__(
        self, story: "Storyboard", tl: "Timeline", name: str, **kwargs,
    ):
        super().__init__(story, name, **kwargs)
        self.dash_by_default = True
        self.ts: "Dict[int, Event]" = {}
        self.timeline = tl
        tl.places.add(self)

    def add_event(self, e: "Event", d: bool = True, push_copies: bool = True):
        """
        Adds an event and also checks that it is unique in time
        :param d: not used
        :param e: the event to add
        :param push_copies: mirror over to the main timeline
        """
        assert (
            e.counter not in self.ts.keys()
        ), f"There's already an event in {self} at {e.counter}"
        self.events.append(e)
        self.ts[e.counter] = e
        if push_copies:
            self.timeline.add_event(e, push_copies=False)

    def __repr__(self):
        return f"Place {self.name}"


class Event(StoryElement):
    def __init__(self, name: str, tl: Timeline, counter: int, **kwargs):
        super().__init__(name, tl.story, **kwargs)
        self.counter = counter
        self.tl = tl
        assert (
            n := name.lower().strip()
        ) not in self.story.event_list.keys(), f"Event {n.upper()} already happened"
        self.story.event_list[n] = self
        tl.add_event(self, push_copies=True)
        self.attendees: "Set[Character]" = set()
        self.can_attend: bool = True if isinstance(tl, Place) else False

    @property
    def roster(self) -> "Set[Character]":
        return self.attendees

    def __repr__(self):
        return f"Event {self.name} at {self.counter} in {self.tl}"


class Character(StoryElement, EventSequence):
    def __init__(self, s: "Storyboard", name: str, *event_list: str, **kwargs):
        StoryElement.__init__(self, name, s, **kwargs)
        EventSequence.__init__(self)
        self.story.dramatis_personae.add(self)
        for e in event_list:
            e = e.strip().lower()
            n = e.split("-")
            dash_previous: bool = True if n[0] == ")" else False
            dash_next: bool = True if n[-1] == "(" else False
            if dash_next:
                e = e[:-2]
            if dash_previous:
                e = e[2:]
                self.dashed_links[-1] = True
            self.add_event(s.event_list[e], dash_next)

    def __repr__(self):
        return f"Character {self.name}"

    @property
    def roster(self) -> "Set[Character]":
        return {self}

    def add_event(self, e: "Event", d: bool = False):
        super().add_event(e, d)
        assert isinstance(e.tl, Place), f"Cannot attend a synchronization marker"
        # add yourself to the roster of the events you attend
        e.attendees.add(self)


class Storyboard(StoryElement):
    def __init__(self, *, name: Optional[str] = None, file=None, **kwargs):
        assert name or file, f"Need a name or a file to load from"
        if not name:
            name = file.split(".tsv")[0]
        super().__init__(name, self, **kwargs)

        self.line_list: Dict[str, Timeline] = {}
        self.event_list: Dict[str, Event] = {}
        self.dramatis_personae: Set[Character] = set()
        self.is_final: bool = False

        self.line_loaders: Dict[str, Callable] = {
            "TIMELINE": self.create_timeline,
            "EVENT": self.create_event,
            "CHARACTER": self.create_character,
        }

        if file:
            self.load_file(file)

    def load_file(self, file, /):
        f = csv.reader(open(file, "r"), delimiter="\t")
        for line in f:
            if len(line) < 4:
                continue
            fn: Callable = self.line_loaders.get(line[0].upper().strip())
            if not fn:
                click.echo(f"invalid line: {line}", err=True)
                continue
            name: str = line[1].strip()
            if not name:
                click.echo(f"Skipping nameless line", err=True)
                continue
            color: Optional[str] = line[2].strip() if line[2] else None
            everything_else: List[str] = line[3:]
            fn(name, *everything_else, color=color)

    @property
    def timelines(self) -> "Set[Timeline]":
        return {t for t in self.line_list.values() if not isinstance(t, Place)}

    @property
    def places(self) -> "Set[Place]":
        return {p for p in self.line_list.values() if isinstance(p, Place)}

    @property
    def nested_lines(self) -> "Dict[Timeline, Set[Place]]":
        return {t: t.places for t in self.timelines}

    def finalize(self):
        for t in self.timelines:
            pass

        self.is_final = True

    def output(self):
        if not self.is_final:
            self.finalize()
        print(f"{len(self.event_list)} events")
        print(f"{len(self.dramatis_personae)} characters")
        print(f"{len(self.line_list)} timelines and places")
        # TODO output

    @property
    def roster(self) -> "Set[Character]":
        return self.dramatis_personae

    def create_timeline(self, name: str, *places: str, **kwargs):
        assert places, f"A timeline without places makes no sense"
        t = Timeline(self, name, **kwargs)
        for p in places:
            Place(self, t, p, **kwargs)
        return t

    def create_event(self, name: str, *args: str, **kwargs):
        assert len(args) > 1, f"{args} lacks sufficient information to create an event"
        assert (
            tl := args[0].lower().strip()
        ) in self.line_list, f"{tl} isn't a real place"
        return Event(name, self.line_list[tl], int(args[1]), **kwargs)

    def create_character(self, name: str, *events: str, **kwargs):
        return Character(self, name, *events, **kwargs)


@click.command()
@click.argument(
    "loadfile",
    type=click.Path(exists=True, dir_okay=False, readable=True, allow_dash=True),
)
def main(loadfile):
    s = Storyboard(file=loadfile)
    s.output()


if __name__ == "__main__":
    main()
