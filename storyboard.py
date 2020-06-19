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
import graphviz as gv


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
            self.dashed_links: List[bool] = [dash_default]

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
        g: gv.Digraph,
        /,
        *,
        show_name: bool = True,
        iterate_prefix: bool = True,
        start_node: Optional[str] = None,
        end_node: Optional[str] = None,
        use_color: bool = True,
        **junk_args,
    ) -> None:
        if (not self.events or not self.dashed_links) and (
            not start_node or not end_node
        ):
            return  # Nothing to display

        def attrs_d() -> Dict[str, str]:
            r: Dict[str, str] = {}
            if use_color:
                r["color"] = self.color
            if junk_args.get("style"):
                r["style"] = junk_args["style"]
            return r

        if start_node:
            g.edge(
                start_node,
                self.events[0].node_name if self.events else end_node,
                self.name if show_name else None,
                **attrs_d(),
            )
        for i in range(len(self.events)):
            attrs: Dict[str, str] = attrs_d()
            if not i:
                continue  # can't draw a line from the previous node
            if show_name:
                attrs["label"] = self.short_name + (f"-{i}" if iterate_prefix else "")
            if self.dashed_links[i]:
                attrs["style"] = "dashed"
            g.edge(self.events[i - 1].node_name, self.events[i].node_name, **attrs)
        if end_node and self.events:
            g.edge(
                self.events[-1].node_name,
                end_node,
                self.name if show_name else None,
                **attrs_d(),
            )


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

    def sort_events(self) -> None:
        """Sorts the event sequence into chronological order"""
        self.events.sort(key=Event.event_key)

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
        story.timelines.add(self)

    def __repr__(self):
        return f"Timeline {self.name}"

    def make_graph(
        self,
        *,
        universal_clock: bool = True,
        start_stop: bool = True,
        only_one: bool = False,
    ) -> gv.Digraph:
        g = gv.Digraph(("" if only_one else "cluster-") + self.name)
        g.attr(compound="True")
        if not only_one:
            g.attr(label=self.name)
        g.attr(color=self.color)
        time_slices: List[gv.Digraph] = [e.make_cluster() for e in self.events]
        for i in range(len(time_slices)):
            g.subgraph(time_slices[i])
            if not i or not universal_clock:
                continue  # there needs to be a previous time for the link to work
            g.edge(
                self.events[i - 1].node_name,
                self.events[i].node_name,
                minlen="1",
                ltail=time_slices[i - 1].name,
                lhead=time_slices[i].name,
                color=self.color,
                label=f"{self.short_name}-{i}",
                style="bold",
            )
        if start_stop:
            start: str = "Start" if only_one else f"{self.short_name}\nstart"
            stop: str = "End" if only_one else f"{self.short_name}\nfinish"
            g.node(start, shape="star", color=self.color)
            g.node(stop, shape="tripleoctagon", color=self.color)
            g.edge(
                start,
                self.events[0].node_name if self.events else stop,
                lhead=time_slices[0].name if self.events else None,
                color=self.color,
                style="bold",
            )
            if self.events:
                g.edge(
                    self.events[-1].node_name,
                    stop,
                    ltail=time_slices[-1].name,
                    color=self.color,
                    style="bold",
                )
        for p in self.places:
            p.make_edges(g)
        return g


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

    def make_edges(
        self,
        g: gv.Digraph,
        /,
        *,
        show_name: bool = True,
        iterate_prefix: bool = False,
        start_node: Optional[str] = True,
        end_node: Optional[str] = True,
        use_color: bool = False,
        **junk_args,
    ) -> None:
        if start_node == True:  # noqa
            start_node = f"{self.short_name}\nstart"
        if end_node == True:  # noqa
            end_node = f"{self.short_name}\nfinish"
        if start_node:
            g.node(start_node, shape="invtrapezium")
        if end_node:
            g.node(end_node, shape="octagon")
            g.node(end_node, shape="octagon")
        return super().make_edges(
            g,
            show_name=show_name,
            iterate_prefix=iterate_prefix,
            start_node=start_node,
            end_node=end_node,
            use_color=use_color,
            style="dotted",
            **junk_args,
        )  # is there a better way to do this?


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

    @property
    def node_name(self) -> str:
        return self.name.replace("-", "\n")

    @classmethod
    def event_key(cls, e: "EventType") -> int:
        return e.counter


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

    def make_cluster(self) -> gv.Digraph:
        c = gv.Digraph(
            name=f"cluster-{self.counter}", graph_attr={"label": f"{self.counter}"}
        )
        for v in self.child_events:
            c.node(v.node_name)
        c.node(self.node_name, shape="point", style="invis")
        return c


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
            "COMMENT": self.comment,
        }
        self.edge_iterator: int = 0
        self.graph = gv.Digraph(name=self.name)
        self.graph.attr(compound="True")
        self.timelines: Set[Timeline] = set()
        self.places: Set[Place] = set()

        if not file:
            return
        self.load_file(file)
        if load_final:
            self.finalize()
            self.make_graph()

    def load_file(self, file, /):
        f = csv.DictReader(open(file, "r"), delimiter="\t")
        for line in f:
            if not line["TYPE"]:
                continue  # skip blank lines without throwing an error
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
        for t in self.line_list.values():
            t.sort_events()
        self.is_final = True

    def output(self):
        if not self.is_final:
            self.finalize()
            self.make_graph()
        click.echo(f"{len(self.event_list)} events")
        click.echo(f"{len(self.dramatis_personae)} characters")
        click.echo(f"{len(self.line_list)} timelines and places")
        self.graph.view(quiet_view=True)

    def make_graph(self) -> gv.Digraph:
        """Converts the loaded data into a graph"""
        # 1. create timelines
        for t in self.timelines:
            self.graph.subgraph(
                t.make_graph(only_one=True if len(self.timelines) < 2 else False)
            )
        # 2. add characters
        for c in self.dramatis_personae:
            c.make_edges(self.graph)
        return self.graph

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
            **kwargs,
        )
        if not places[2:]:  # single-place timelines
            Place(self, t, name, **kwargs)
        for p in places[2:]:
            Place(self, t, p, **kwargs)
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

    @staticmethod
    def comment(*args, **kwargs):
        """Skips a comment without throwing an error"""
        pass


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
