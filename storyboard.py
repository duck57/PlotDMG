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
        es: "Optional[List[EventType]]" = None,
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
    def latest_event(self) -> "EventType":
        return self.events[-1]

    @latest_event.setter
    def latest_event(self, new_event: "EventType"):
        self.add_event(new_event, self.dash_by_default)

    def add_event(self, e: "EventType", d: bool = False):
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


class TimedEventSequence(EventSequence):
    def __init__(self, name: str, story: "Storyboard", **kwargs):
        super().__init__(name, story, **kwargs)
        assert (
            self.key not in story.line_list.keys()
        ), f"{self.name} already is a timeline or place"
        assert (
            self.short_name.lower() not in story.line_list.keys()
        ), f"{self.name} needs a unique short name ({self.short_name} in conflict)"
        story.line_list[self.key] = self
        if self.short_name.lower().strip() != self.key:
            story.line_list[self.short_name.lower()] = self
        self.ts: "Dict[int, EventType]" = {}
        self.v_pos: int = kwargs.get("v_pos", 0)

    @property
    def timestamps(self) -> "List[int]":
        """
        :return: a sorted list of timestamps for the events of a timeline
        """
        return sorted({e.counter for e in self.events})

    def add_event(self, e: "EventType", d: bool = False):
        assert (
            e.counter not in self.ts.keys()
        ), f"There's already an event in {self} at {e.counter}"
        assert (
            n := e.name.lower().strip()
        ) not in self.story.event_list.keys(), f"Event {n.upper()} already happened"
        self.story.event_list[n] = e
        super().add_event(e, d)
        self.ts[e.counter] = e

    def make_edges(self, link_type: str = "incomplete code error", **kwargs):
        return super().make_edges(None, True, link_type)


class Timeline(TimedEventSequence):
    """
    A world clock
    """

    def __init__(
        self, story: "Storyboard", name: str, **kwargs,
    ):
        super().__init__(name, story, **kwargs)

        self.places: "Set[Place]" = set()
        if self.color is None:
            self.color = story.color
        self.scaling: int = int(kwargs["scaling"]) if kwargs.get("scaling") else 2
        self.offset: int = int(kwargs["offset"]) if kwargs.get("offset") else 0
        story.timelines.add(self)

    def __repr__(self):
        return f"Timeline {self.name}"

    def make_edges(self, **kwargs):
        return super().make_edges("Clock")

    def position_events_h(self):
        pass


class Place(TimedEventSequence):
    """
    A sequence of events that happen in the same place
    """

    def __init__(
        self, story: "Storyboard", tl: "Timeline", name: str, **kwargs,
    ):
        super().__init__(name, story, **kwargs)
        if self.color is None:
            self.color = tl.color
        self.dash_by_default = True
        self.timeline = tl
        story.places.add(self)
        tl.places.add(self)

    def __repr__(self):
        return f"Place {self.name}"

    def make_edges(self, **kwargs):
        super().make_edges("History")


class EventBase(StoryElement):
    can_attend: bool

    def __init__(
        self, name: str, tl: "LineType", counter: int, **kwargs,
    ):
        """
        :param name: (Unique) name of event
        :param tl: Line of the event
        :param counter: When did it happen?
        :param kwargs: other stuff
        """
        super().__init__(name, tl.story, **kwargs)
        self.name = name
        self.line = tl
        self.counter = counter
        self.line.add_event(self)
        self.attendees: "Set[Character]" = set()

    @property
    def pos(self) -> Tuple[int, int]:
        return self.counter, self.line.v_pos

    def __repr__(self):
        return f"Event {self.name} at {self.counter} in {self.line}"

    @property
    def roster(self) -> "Set[Character]":
        return self.attendees


class EventAnchor(EventBase):
    """
    "Events" on a Timeline for time synchronization
    """

    can_attend = False

    def __init__(
        self, name: str, tl: Timeline, counter: int, make_related: bool = True, **kwargs
    ):
        super().__init__(name, tl, counter, **kwargs)
        self.draw_sync_lines: bool = not make_related
        if make_related:
            {Event(f"{name}-{p.name}", p, counter) for p in tl.places}  # noqa  # noqa

    @property
    def child_events(self) -> "Set[Event]":
        return {
            p.ts[self.counter] for p in self.line.places if self.counter in p.ts.keys()
        }


class Event(EventBase):
    """
    Events in a Place that characters can attend
    """

    can_attend = True

    def __init__(
        self, name: str, tl: Place, counter: int, **kwargs,
    ):
        super().__init__(name, tl, counter, **kwargs)
        self.anchor = (
            tl.timeline.ts[counter]
            if counter in tl.timeline.ts.keys()
            else EventAnchor(
                f"{self.line.short_name}-{counter}",
                self.line.timeline,
                counter,
                False,
                **kwargs,
            )
        )


EventType = TypeVar("EventType", bound=EventBase)
LineType = TypeVar("LineType", bound=TimedEventSequence)


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
    def __init__(
        self,
        *,
        name: Optional[str] = None,
        file=None,
        load_final: bool = True,
        **kwargs,
    ):
        assert name or file, f"Need a name or a file to load from"
        if not name:
            name = file.split(".tsv")[0]
        super().__init__(name, self, **kwargs)

        # set up all the blank variables
        self.line_list: Dict[str, LineType] = {}
        self.event_list: Dict[str, Event] = {}
        self.dramatis_personae: Set[Character] = set()
        self.is_final: bool = False
        self.line_loaders: Dict[str, Callable] = {
            "TIMELINE": self.create_timeline,
            "EVENT": self.create_event,
            "CHARACTER": self.create_character,
        }
        self.edge_iterator: int = 0
        self.graph = nx.MultiDiGraph()
        self.display_ready: bool = False
        self.v_scaling: int = kwargs.get("v_scale", 1)
        self.v_count: int = 0
        self.timelines: Set[Timeline] = set()
        self.places: Set[Place] = set()

        if not file:
            return
        self.load_file(file)
        if load_final:
            pass  # TODO finalize, generate graph

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
    def nested_lines(self) -> "Dict[Timeline, Set[Place]]":
        return {t: t.places for t in self.timelines}

    def finalize(self):
        """Adds start/end events for better graph output"""
        if self.is_final:
            return
        for t in self.timelines:
            if not t.timestamps:
                EventAnchor(f"empty_{t.name}_start", t, -1)
                EventAnchor(f"empty_{t.name}_end", t, 1)
                continue
            EventAnchor(f"{t.name}_start", t, t.timestamps[0] - 1)
            EventAnchor(f"{t.name}_end", t, t.timestamps[-1] + 1)
        self.is_final = True

    def output(self):
        if not self.graph:
            self.prep4display()
        print(f"{len(self.event_list)} events")
        print(f"{len(self.dramatis_personae)} characters")
        print(f"{len(self.line_list)} timelines and places")
        nx.write_graphml(self.graph, f"{self.name}.graphml", infer_numeric_types=True)
        # nx.write_gexf(self.graph, f"{self.name}.gexf")
        nx.draw_networkx(self.graph, {n: n.pos for n in self.event_list.values()})
        plt.savefig(f"{self.name}.png")
        plt.savefig(f"{self.name}.svg")

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
        # calculate the horizontal positions of each node
        self.display_ready = True

    @property
    def roster(self) -> "Set[Character]":
        return self.dramatis_personae

    def create_timeline(self, name: str, short_name: str, *places: str, **kwargs):
        assert len(places) > 1, f"A timeline without places makes no sense"
        t = Timeline(
            self,
            name if places[2:] else f"{name}-tl",
            short_name=short_name,
            scaling=places[0],
            offset=places[1],
            v_pos=self.v_count,
            **kwargs,
        )
        if not places[2:]:  # single-place timelines
            Place(self, t, name, v_pos=self.v_count, **kwargs)
            self.v_count -= self.v_scaling
        for p in places[2:]:
            Place(self, t, p, v_pos=self.v_count, **kwargs)
            self.v_count -= self.v_scaling
        t.v_pos = self.v_count
        self.v_count -= self.v_scaling * 2
        return t

    def create_event(self, name: str, timestamp: str, *args: str, **kwargs):
        assert args, f"Insufficient information to create an event: {name} {timestamp}"
        assert (
            tl := args[0].lower().strip()
        ) in self.line_list.keys(), f"{tl} isn't a real place"
        line = self.line_list[tl]
        return (
            Event(name, line, int(timestamp), **kwargs)
            if isinstance(line, Place)
            else EventAnchor(name, line, int(timestamp), **kwargs)
        )

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
