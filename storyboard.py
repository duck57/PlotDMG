#!venv/bin/python
# coding=UTF-8
# -*- coding: UTF-8 -*-
# vim: set fileencoding=UTF-8 :

"""
Package to generate plot diagrams from TSV files
The output is a directed multigraph

---------

.tsv expectations

Header row:
TYPE    NAME    COLOR   SHORTNAME   *args

TYPE of entry: either Timeline, Event, or Character
NAME of entry, globally unique within its TYPE
COLOR to graph (optional)
SHORTNAME for graph display (or timestamp for an Event)
*args depend on the TYPE

All Timelines are expected before any Events
Likewise, all Events are expected before any Characters
Violating these may cause Not Found errors

TYPE: Timeline
A universe timeline.
For extensive time-skips in the same universe (think of time travelers from
the Clinton years visiting the mid-Triassic), it may be appropriate to consider
distant past and far future to be different timelines, even if they are connected
:args (at least 3 required)
1. horizontal offset (integer), defaults to 0
2. spacing (integer), defaults to 1
3. list of place names
must be globally unique among both Timeline and Place names:

TYPE: Event
Something that happened.
:SHORTNAME Integer timestamp for ordering relative to the rest of the Timeline or Place
    Timestamps should be unique for each Place
:args (1 required)
Name of the Timeline or Place where the event occurs
    Placing an event on a Timeline acts as a simultaneity marker
    (cannot be directly accessed by characters)
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
import networkx as nx
import matplotlib.pyplot as plt


class StoryElement(abc.ABC):
    def __init__(self, name: str, s: "Storyboard", /, **kwargs):
        assert s, f"No story connected with this element"
        assert name, f"Empty name"
        self.story = s
        self.name = name.strip()
        self.key: str = kwargs["key"] if kwargs.get("key") else self.name.lower()
        self.short_name: str = kwargs["short_name"] if kwargs.get(
            "short_name"
        ) else self.name
        self.color = kwargs.get("color")

    @property
    @abc.abstractmethod
    def roster(self) -> "Set[Character]":
        pass

    def __str__(self):
        return self.name


class EventSequence(StoryElement):
    def __init__(
        self,
        name: str,
        s: "Storyboard",
        /,
        es: "Optional[List[Event]]" = None,
        dashed_links: List[bool] = None,
        dash_default: bool = False,
        **kwargs,
    ):
        super().__init__(name, s, **kwargs)
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

    @property
    def roster(self) -> "Set[Character]":
        out: "Set[Character]" = set()
        for event in self.events:
            out |= event.roster
        return out

    def make_edges(
        self,
        prefix: Optional[str] = None,
        iterate_prefix: bool = True,
        link_type: str = "Unknown",
    ):
        name: Optional[str] = self.name
        if prefix and not iterate_prefix:
            name = prefix
        for i in range(len(self.events) - 1):
            if prefix and iterate_prefix:
                name = f"{prefix}-{i+1}"
            self.story.graph.add_edge(
                self.events[i],
                self.events[i + 1],
                dashed=self.dashed_links[i],
                name=name,
                key=self.story.edge_iterator,
                color=self.color,
                type=link_type,
            )
            self.story.edge_iterator += 1


class Timeline(EventSequence):
    type = "Timeline"

    def __init__(
        self, story: "Storyboard", name: str, **kwargs,
    ):
        super().__init__(name, story, **kwargs)
        assert (
            self.key not in story.line_list.keys()
        ), f"{self.name} already is a timeline or place"
        story.line_list[self.key] = self
        x = story.line_list.get(self.short_name.lower())
        assert (
            x is None or x == self
        ), f"{self.name} needs a unique short name ({self.short_name} in conflict)"
        if not x:
            story.line_list[self.short_name.lower()] = self
        self.ts: "Dict[int, Event]" = {}
        self.places: "Set[Place]" = set()
        if self.color is None:
            self.color = story.color

    @property
    def timestamps(self) -> "List[int]":
        """
        This is here instead of in EventSequence because these timestamps would
        make no sense on a Character that can cross multiple Timelines
        :return: a sorted list of timestamps for the events of a timeline
        """
        return sorted({e.counter for e in self.events})

    def __repr__(self):
        return f"Timeline {self.name}"

    def add_event(self, e: "Event", d: bool = False, push_copies: bool = True):
        assert (
            e.counter not in self.ts.keys()
        ), f"There's already an event in {self} at {e.counter}"
        assert (
            n := e.name.lower().strip()
        ) not in self.story.event_list.keys(), f"Event {n.upper()} already happened"
        self.story.event_list[n] = e
        super().add_event(e, d)
        self.ts[e.counter] = e
        if not push_copies:
            return
        if e.sync_arrows is None:
            e.sync_arrows = False
        {  # noqa
            Event(f"{e.name}-{p.name}", p, e.counter, push_copies=False)
            for p in self.places
        }  # noqa

    def make_edges(
        self,
        prefix: Optional[str] = None,
        iterate_prefix: bool = True,
        link_type: str = "Clock",
    ):
        return super().make_edges(prefix, iterate_prefix, link_type)


class Place(Timeline):
    type = "Place"

    def __init__(
        self, story: "Storyboard", tl: "Timeline", name: str, **kwargs,
    ):
        super().__init__(story, name, **kwargs)
        if self.color is None:
            self.color = tl.color
        self.dash_by_default = True
        self.timeline = tl
        tl.places.add(self)

    def add_event(self, e: "Event", d: bool = True, push_copies: bool = True):
        """
        Adds an event and also checks that it is unique in time
        :param d: not used
        :param e: the event to add
        :param push_copies: mirror over to the main timeline
        """
        super().add_event(e, d, push_copies=False)
        e.can_attend = True
        if e.sync_arrows is None:
            e.sync_arrows = push_copies
        if not push_copies:
            return  # don't create linking arrows on child events to reduce mess
        if e.counter in self.timeline.ts.keys():
            return  # another event is happening at the same time at another place
        Event(  # synchronization event
            f"{self.timeline.short_name}-{e.counter}",
            self.timeline,
            e.counter,
            push_copies=False,
        )

    def __repr__(self):
        return f"Place {self.name}"

    def make_edges(
        self,
        prefix: Optional[str] = None,
        iterate_prefix: bool = True,
        link_type: str = "History",
    ):
        super().make_edges(prefix, iterate_prefix, link_type)
        for ts in self.ts.keys():
            e: Event = self.ts[ts]
            if not e.sync_arrows:
                continue
            stamp: Event = self.timeline.ts[ts]
            ei: int = self.story.edge_iterator
            self.story.graph.add_edge(e, stamp, type="Sync", key=ei)
            self.story.graph.add_edge(stamp, e, type="Sync", key=ei + 1)
            self.story.edge_iterator = ei + 2


class Event(StoryElement):
    def __init__(
        self,
        name: str,
        tl: Timeline,
        counter: int,
        push_copies: bool = True,
        sync_arrows: Optional[bool] = None,
        **kwargs,
    ):
        super().__init__(name, tl.story, **kwargs)
        self.counter = counter
        self.can_attend: bool = False  # changed to True in Place.add_event()
        self.sync_arrows: bool = sync_arrows
        tl.add_event(self, push_copies=push_copies)
        self.attendees: "Set[Character]" = set()
        self.tl = tl

    @property
    def roster(self) -> "Set[Character]":
        return self.attendees

    def __repr__(self):
        return f"Event {self.name} at {self.counter} in {self.tl}"


class Character(EventSequence):
    def __init__(self, s: "Storyboard", name: str, *event_list: str, **kwargs):
        super().__init__(name, s, **kwargs)
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
        if self.color is None:
            self.color = s.color

    def __repr__(self):
        return f"Character {self.name}"

    @property
    def roster(self) -> "Set[Character]":
        return super().roster - {self}

    def add_event(self, e: "Event", d: bool = False):
        assert e.can_attend, f"Cannot attend a synchronization marker"
        super().add_event(e, d)
        # add yourself to the roster of the events you attend
        e.attendees.add(self)

    def make_edges(
        self,
        prefix: Optional[str] = None,
        iterate_prefix: bool = True,
        link_type: str = "Character",
    ):
        if prefix is None:
            prefix = self.short_name
        super().make_edges(prefix, iterate_prefix, link_type)


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
        self.edge_iterator: int = 0
        self.graph = nx.MultiDiGraph()
        self.node_positions: Dict[Event, Tuple[int, int]] = {}
        self.display_ready: bool = False
        self.v_scaling: int = kwargs.get("v_scale", 2)

    def load_file(self, file, /):
        f = csv.DictReader(open(file, "r"), delimiter="\t")
        for line in f:
            fn: Callable = self.line_loaders.get(line["TYPE"].upper().strip())
            if not fn:
                click.echo(f"invalid line: {line}", err=True)
                continue
            color: Optional[str] = line["COLOR"].strip() if line["COLOR"] else None
            everything_else: List[str] = line.get(None, [])  # noqa
            fn(line["NAME"], line["SHORTNAME"], *everything_else, color=color)

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
        """Adds start/end events for better graph output"""
        if self.is_final:
            return
        for t in self.timelines:
            if not t.timestamps:
                Event(f"empty_{t.name}_start", t, -1)
                Event(f"empty_{t.name}_end", t, 1)
                continue
            Event(f"{t.name}_start", t, t.timestamps[0] - 1)
            Event(f"{t.name}_end", t, t.timestamps[-1] + 1)
        self.is_final = True

    def output(self):
        if not self.graph:
            self.prep4display()
        print(f"{len(self.event_list)} events")
        print(f"{len(self.dramatis_personae)} characters")
        print(f"{len(self.line_list)} timelines and places")
        nx.write_graphml(self.graph, f"{self.name}.graphml", infer_numeric_types=True)
        nx.draw(self.graph)  # , self.node_positions)
        plt.show()

    def make_graph(self, leave_unfinished: bool = False) -> nx.MultiDiGraph:
        """Converts the loaded data into a graph"""
        if not self.is_final and not leave_unfinished:
            self.finalize()
        for p in set(self.line_list.values()):
            p.make_edges()
        for c in self.dramatis_personae:
            c.make_edges()
        return self.graph

    def prep4display(self):
        """Calculates the node positions for output"""
        if not self.graph:
            self.make_graph()
        if self.display_ready:
            return
        # TODO make this work
        self.display_ready = True

    @property
    def roster(self) -> "Set[Character]":
        return self.dramatis_personae

    def create_timeline(self, name: str, short_name: str, *places: str, **kwargs):
        assert places, f"A timeline without places makes no sense"
        t = Timeline(self, name, short_name=short_name, **kwargs)
        for p in places:
            Place(self, t, p, **kwargs)
        return t

    def create_event(self, name: str, timestamp: str, *args: str, **kwargs):
        assert args, f"Insufficient information to create an event: {name} {timestamp}"
        assert (
            tl := args[0].lower().strip()
        ) in self.line_list, f"{tl} isn't a real place"
        return Event(name, self.line_list[tl], int(timestamp), **kwargs)

    def create_character(self, name: str, short_name: str, *events: str, **kwargs):
        return Character(self, name, *events, short_name=short_name, **kwargs)


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
