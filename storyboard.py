#!venv/bin/python
# coding=UTF-8
# -*- coding: UTF-8 -*-
# vim: set fileencoding=UTF-8 :

"""
Package to generate plot diagrams from TSV files

---------

Output can be cleaned up with 'rm *.gv*'

---------

.tsv expectations

Header row:
TYPE    NAME    COLOR   SHORTNAME   *args

TYPE of entry: either Timeline, Event, or Character
NAME of entry, globally unique within its TYPE
COLOR to graph (optional), list of valid colors http://www.graphviz.org/doc/info/colors.html
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
:args (at least 1 required) list of place names:
Timeline and Place names must be globally-unique in a shared pool

TYPE: Event
Something that happened.
Event names must be globally-unique
:SHORTNAME Integer timestamp for ordering relative to the rest of the Timeline or Place
    Timestamps should be unique for each Place
:args (1 required)
Name of the Timeline or Place where the event occurs
    Placing an event on a Timeline creates child events for all Places within the Timeline
Adding a second arg will suppress the Event from being considered when drawing
the friendship graph.  This is useful for heavily-populated events that obscure,
rather than highlight, character connections.
:

TYPE: Character
Someone who moves between Events
If the last character of the name is '*', the character is skipped on the friendship graph
:args a list of Events
Dashed connections
    append -( to an event name to dash to next event
    prefix )- to an event name to dash from previous event
:

TYPE: Object
Synonym for Character

TYPE: Combiner
These characters (or objects) will share a line when traveling between the same events
Priority is given to the longest combiner that will fit.
If multiple combiners of the same length could be applied to a set of parallel travelers,
    the one listed later in the input file takes precedence
:args (2 or more required)
    list of character names to combine
:

TYPE: Comment
A comment line that will be skipped without errors or warnings
:args whatever you want:

"""
from copy import deepcopy

import click
import csv
from typing import *
import abc
import graphviz as gv
from collections import Counter, defaultdict
from defaultlist import defaultlist


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

    @property
    def tooltip_txt(self) -> str:
        if not self.roster:
            return ""
        return f"{self.name}" + ("\n📒Roster: " + Character.lst2str(self.roster))

    @property
    def tooltip_js(self) -> str:
        return self.jsa(self.tooltip_txt)

    @staticmethod
    def jsa(m: str) -> str:
        if not m:
            return m
        m = m.replace("\n", "\\n")
        m = m.replace("'", "\\'")
        return f"javascript:alert('{m}');"

    def __str__(self):
        return self.name


class EventConnector(StoryElement, abc.ABC):
    def __init__(self, name: str, s: "Storyboard", **kwargs):
        super().__init__(name, s, **kwargs)
        self.bridges: "List[EventBridge]" = []

    @abc.abstractmethod
    def build_bridges(self) -> None:
        pass

    def add_links_to_story(self) -> None:
        for b in self.bridges:
            b.add_to_story_queue()


class EventSequence(EventConnector, abc.ABC):
    def __init__(
        self,
        name: str,
        s: "Storyboard",
        /,
        es: "List[EventType]" = None,
        dashed_links: List[bool] = None,
        dash_default: bool = False,
        **kwargs,
    ):
        super().__init__(name, s, **kwargs)
        self.e_lst: "List[EventInSequence]" = []
        self.dash_by_default = dash_default
        if es:
            self.add_event_list(es, dashed_links)

    @property
    def events(self) -> "List[EventType]":
        return [e[0] for e in self.e_lst]

    def build_bridges(
        self,
        show_name: bool = True,
        show_number: bool = True,
        da: Dict[str, str] = None,
        add_now: bool = True,
    ) -> None:
        if not da:
            da = {}
        for i in range(1, len(self.e_lst)):
            past, future = self.e_lst[i - 1].event, self.e_lst[i].event
            dash = self.e_lst[i - 1].dash_to_next or self.e_lst[i].dash_from_previous
            x = EventBridge(self, i, past, future, dash, show_name, show_number, da)
            self.bridges.append(x)
        if add_now:  # you need to do this manually in the overriding method if False
            self.add_links_to_story()

    @property
    def has_loop(self) -> bool:
        """Does this sequence contain the same event twice?"""
        return False if len(self.events) == len(set(self.events)) else True

    @property
    def latest_event(self) -> "EventType":
        return self.e_lst[-1][0]

    @latest_event.setter
    def latest_event(self, new_event: "EventType"):
        self.add_event(new_event, self.dash_by_default, self.dash_by_default)

    def add_event_list(
        self, e: "List[EventType]", dashed_links: Optional[List[bool]] = None
    ):
        dash = defaultlist(lambda: self.dash_by_default)
        if dashed_links:
            for i, b in enumerate(dashed_links):
                dash[i] = b
        for j in range(len(e)):
            self.add_event(e[j], dash[j - 1], dash[j])

    def add_event(self, e: "EventType", dash_b4: bool = False, dash_next: bool = False):
        self.e_lst.append(EventInSequence(e, dash_b4, dash_next))

    @property
    def dash_list(self) -> List[bool]:
        return [self.dash_by_default] + [
            (self.e_lst[i - 1].dash_to_next or self.e_lst[i].dash_from_previous)
            for i in range(1, len(self.e_lst))
        ]

    @property
    def roster(self) -> "Set[Character]":
        out: "Set[Character]" = set()
        for event in self.events:
            out |= event.roster
        return out


class EventInSequence(NamedTuple):
    event: "EventType"
    dash_from_previous: bool
    dash_to_next: bool

    @property
    def counter(self) -> int:
        return self.event.counter

    @property
    def node_name(self) -> str:
        return self.event.node_name


class TimedEventSequence(EventSequence, abc.ABC):
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

    @property
    def timestamps(self) -> "List[int]":
        """
        :return: a sorted list of timestamps for the events of a timeline
        """
        return sorted({e.counter for e in self.events})

    def sort_events(self) -> None:
        """Sorts the event sequence into chronological order"""
        self.e_lst.sort(key=TimedEventSequence.time_key)

    @staticmethod
    def time_key(x: "EventInSequence") -> int:
        return x.event.counter

    def add_event(self, e: "EventType", dash_b4: bool = True, dash_next: bool = True):
        assert (
            e.counter not in self.ts.keys()
        ), f"There's already an event in {self} at {e.counter}"
        assert (
            n := e.name.lower().strip()
        ) not in self.story.event_list.keys(), f"Event {n.upper()} already happened"
        self.story.event_list[n] = e
        super().add_event(e, dash_b4, dash_next)
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
        direction: str = "LR",
        *,
        only_one: bool = False,
        color_names: bool = False,
    ) -> gv.Digraph:
        g = gv.Digraph(("" if only_one else "cluster-") + self.name)
        g.attr(compound="True", color=self.color)
        if not only_one:
            if color_names:
                g.attr(fontcolor=self.color)
            g.attr(
                label=self.name,
                penwidth="2",
                fontname="sans bold",
                fontsize="28",
                tooltip=self.tooltip_txt,
                URL=self.tooltip_js,
            )
        for ts in [e.make_cluster(direction) for e in self.events]:
            g.subgraph(ts)
        return g

    def build_bridges(
        self, show_name: bool = True, show_number: bool = True, **da
    ) -> None:
        if not da.get("style"):
            da["style"] = "bold"
        if not da.get("fontname"):
            da["fontname"] = "sans italic"
        if not da.get("minlen"):
            da["minlen"] = "1"
        super().build_bridges(show_name, show_number, da, add_now=False)
        for b in self.bridges:
            b.add_cluster_endings()
        self.add_links_to_story()


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

    def build_bridges(
        self, show_name: bool = False, show_number: bool = False, **da
    ) -> None:
        if not da.get("style"):
            da["style"] = "dotted"
        if not da.get("arrowhead"):
            da["arrowhead"] = "onormal"
        super().build_bridges(show_name, show_number, da)

    @property
    def tooltip_txt(self) -> str:
        return super().tooltip_txt.replace("\n📒Roster: ", "\nVisitors: ")


class EventBase(StoryElement, abc.ABC):
    can_attend: bool
    grad_dir: Dict[str, str] = {
        "LR": "0",
        "TB": "270",
        "BT": "90",
        "RL": "180",
    }

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
        self.attendees: "Counter[Character]" = Counter()
        self.entrances: "Set[Character]" = set()
        self.exits: "Set[Character]" = set()
        self.opener: bool = kwargs.get("opener", False)
        self.closer: bool = kwargs.get("closer", False)
        self.ue: bool = kwargs.get("UE", False)
        self.skip_in_friendship_graph: bool = kwargs.get("vegan", not self.can_attend)

    @property
    def loopers(self) -> "Set[Character]":
        return {k for (k, v) in self.attendees.items() if v > 1}

    def __repr__(self):
        return f"Event {self.name} at {self.counter} in {self.line}"

    @property
    def tooltip_txt(self) -> str:
        o: str = super().tooltip_txt
        if o and self.skip_in_friendship_graph:
            o += "**"
        if not self.ue:
            o = o.replace(self.name, f"{self.name} [{self.line.name}]")
        if self.entrances:
            o += "\n🛬Entrances: " + Character.lst2str(self.entrances)
        if self.exits:
            o += "\n🛫Departures: " + Character.lst2str(self.exits)
        if self.loopers:
            o += "\n➰Loopers: " + Character.lst2str(self.loopers)
        if o and self.skip_in_friendship_graph:
            o += "\n** = skipped when drawing lines on the friendship graph"
        return o

    @property
    def roster(self) -> "Set[Character]":
        return set(self.attendees)

    @property
    def node_name(self) -> str:
        return self.name.replace("-", "\n")

    @staticmethod
    def event_key(e: "EventType") -> int:
        return e.counter

    def add_character(self, c: "Character", /):
        self.attendees[c] += 1


class EventAnchor(EventBase):
    """
    "Events" on a Timeline for time synchronization
    """

    can_attend = False

    def __init__(
        self, name: str, tl: Timeline, counter: int, make_related: bool = True, **kwargs
    ):
        super().__init__(name, tl, counter, **kwargs)
        if self.opener or self.closer:
            self.color = self.line.color
        self.child_events: "Set[Event]" = set()
        kwargs.pop("color", None)
        if make_related:
            self.child_events |= {
                Event(
                    f"{name}-{p.name}", p, counter, color=self.color, UE=True, **kwargs
                )
                for p in tl.places
            }

    @property
    def cluster_name(self) -> str:
        return f"cluster-{self.counter}"

    def make_cluster(self, g_dir: str = "LR") -> gv.Digraph:
        ga: Dict[str, str] = {
            "label": f"{self.counter}",
            "gradientangle": self.grad_dir[g_dir],
            "color": self.color if self.color else "",
            "fontsize": "",
            "fontname": "",
            "tooltip": self.tooltip_txt,
            "URL": self.tooltip_js,
        }
        color: str = self.line.color if self.line.color else "#00000088"
        na: Dict[str, str] = {}
        if self.opener or self.closer:
            ga["style"] = "filled,rounded"
            na["gradientangle"] = self.grad_dir[g_dir]
            na["style"] = "filled"
            ga["penwidth"] = "0"
            na["penwidth"] = "0"
        if self.opener:
            ga["color"] = f"{color}:#FFFFFF33"
            na["shape"] = "egg"
            na["color"] = f"#EDEDED99:{color}"
        elif self.closer:
            ga["color"] = f"#FFFFFF33:{color}"
            na["shape"] = "octagon"
            na["color"] = f"{color}:#EDEDED99"
        else:
            na["color"] = color
        c = gv.Digraph(name=self.cluster_name, graph_attr=ga)
        for v in self.child_events:
            use_event_color = v.color and not (self.opener or self.closer)
            na["tooltip"] = v.tooltip_txt
            na["URL"] = v.tooltip_js
            if use_event_color:
                na["color"] = v.color
            c.node(v.node_name, **na)
            if (
                use_event_color
            ):  # clear color so it doesn't bleed over into other events
                na.pop("color", "Blue")
        c.node(self.node_name, shape="point", style="invis")
        return c


class Event(EventBase):
    """
    Events in a Place that characters can attend
    """

    def __init__(
        self, name: str, tl: Place, counter: int, **kwargs,
    ):
        super().__init__(name, tl, counter, **kwargs)
        kwargs.pop("color", None)  # don't infect other nodes with your color
        kwargs.pop("vegan", None)
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
        self.anchor.child_events.add(self)

    def add_character(self, c: "Character", /):
        super().add_character(c)
        self.anchor.add_character(c)

    @property
    def can_attend(self) -> bool:
        return False if self.opener or self.closer else True

    @property
    def tooltip_txt(self) -> str:
        return (
            self.line.tooltip_txt if self.opener or self.closer else super().tooltip_txt
        )


EventType = TypeVar("EventType", bound=EventBase)
LineType = TypeVar("LineType", bound=TimedEventSequence)
ESType = TypeVar("ESType", bound=EventConnector)


class EventBridge:
    def __init__(
        self,
        seq: ESType,
        index: int,
        past: EventType,
        future: EventType,
        dash: bool = False,
        show_name: bool = True,
        show_number: bool = True,
        display_attrs: Dict[str, str] = None,
    ):
        self.seq = seq
        self.index = index
        self.past = past
        self.future = future
        self.dash = dash
        self.show_name = show_name
        self.show_number = show_number
        self.display_attrs = display_attrs if display_attrs else {}
        self.child_bridges: "List[EventBridge]" = []

    def line_str(self, show_name: bool = True, show_number: bool = True) -> str:
        return (self.seq.short_name if show_name else "") + (
            f"-{self.index}" if show_number else ""
        )

    @property
    def child_bridge_by_char(self) -> "Dict[ESType, EventBridge]":
        return {b.seq: b for b in self.child_bridges}

    @property
    def dash_link(self) -> bool:
        if not self.child_bridges:
            return self.dash
        return any(c.dash for c in self.child_bridges)

    def __repr__(self):
        return f"{self.index} Bridge from {self.past} to {self.future} for {self.seq}"

    def draw_line(
        self, g: gv.Digraph, color_labels: bool = True, **override_attrs
    ) -> None:
        # inherent attributes
        attrs = deepcopy(self.display_attrs)
        for x in override_attrs:  # manual overrides
            attrs[x] = override_attrs[x]  # can be a one-line in 3.9

        # default properties
        if not attrs.get("style"):
            if self.dash_link:
                attrs["style"] = "dashed"
        if not attrs.get("label"):
            attrs["label"] = self.line_str(self.show_name, self.show_number)
        if not attrs.get("color"):
            attrs["color"] = self.color
        if not attrs.get("fontcolor"):
            attrs["fontcolor"] = self.color if color_labels else ""

        # fancy Timeline rendering
        if isinstance(self.seq, Timeline):
            attrs["ltail"] = self.past.cluster_name
            attrs["lhead"] = self.future.cluster_name
            attrs["arrowhead"] = "lvee" if self.index % 2 else "rvee"

        # SVG tooltips for combined lines
        if len(self.child_bridges) > 1:
            attrs["labeltooltip"] = "\n\t".join(
                [f"{self.past.name} -> {self.future.name}: {attrs['label']}"]
                + [b.line_str() for b in self.child_bridges]
            )
            if not attrs.get("URL"):
                attrs["URL"] = StoryElement.jsa(attrs["labeltooltip"])

        # assign estimated straightness
        if "weight" not in attrs.keys():
            attrs["weight"] = str(self.weight)

        # draw the edge on the graph
        try:
            g.edge(self.past.node_name, self.future.node_name, **attrs)
        except TypeError:
            click.echo(attrs, err=True)

    @property
    def weight(self) -> int:
        if isinstance(self.seq, Timeline):
            return 123
        if isinstance(self.seq, Place):
            return 69
        w: int = 10 * len(self.child_bridges) + 7
        if self.dash_link:
            return round(w / 9)
        return w

    def modify_display_attrs(self, **da):
        for attr in da:
            self.display_attrs[attr] = da[attr]

    def add_cluster_endings(self) -> None:
        self.modify_display_attrs(
            ltail=self.past.cluster_name,
            lhead=self.future.cluster_name,
            arrowhead="lvee" if self.index % 2 else "rvee",
        )

    def add_to_story_queue(self) -> None:
        self.seq.story.links2process[self.past, self.future].append(self)

    @property
    def color(self) -> str:
        return self.seq.color


class Character(EventSequence):
    def __init__(self, s: "Storyboard", name: str, *event_list: str, **kwargs):
        assert (
            name not in s.dramatis_personae.keys()
        ), f"A character named {name} already exists"
        if name[-1] == "*":
            self.skip_in_friendship_graph = True
            name = name[:-1]
        else:
            self.skip_in_friendship_graph = False
        super().__init__(name, s, **kwargs)
        s.dramatis_personae[name] = self
        Combiner(s, name, self)
        if self.short_name != self.name:
            assert (
                self.short_name not in s.dramatis_personae.keys()
            ), f"{self.short_name} is already taken as a character (short)name"
            s.dramatis_personae[self.short_name] = self
        for e in event_list:
            e = e.strip().lower()
            if not e:
                continue  # prevent errors for rearranged&deleted events
            n = e.split("-")
            dash_previous: bool = True if n[0] == ")" else False
            dash_next: bool = True if n[-1] == "(" else False
            if dash_next:
                e = e[:-2]
            if dash_previous:
                e = e[2:]
            self.add_event(s.event_list[e], dash_previous, dash_next)
        if self.events:
            self.events[0].entrances.add(self)
            self.events[0].anchor.entrances.add(self)
            self.latest_event.exits.add(self)
            self.latest_event.anchor.exits.add(self)

    def __repr__(self) -> str:
        return f"Character {self.name}"

    @property
    def roster(self) -> "Set[Character]":
        """This is the list of characters met along the way"""
        return super().roster - (set() if self.has_loop else {self})

    @property
    def mod_roster(self) -> "Set[Character]":
        ros: "Set[Character]" = set()
        for e in self.events:
            if not e.skip_in_friendship_graph:
                ros |= {c for c in e.roster if not c.skip_in_friendship_graph}
        return ros - (set() if self.has_loop else {self})

    def add_event(self, e: "Event", dash_b4: bool = False, dash_next: bool = False):
        assert e.can_attend, f"{self} cannot attend a synchronization marker, {e}"
        super().add_event(e, dash_b4, dash_next)
        # add yourself to the roster of the events you attend
        e.add_character(self)

    @staticmethod
    def lst2str(a: "Iterable[Character]") -> str:
        return ", ".join(c.name for c in a)

    def draw_friendships(self, g: gv.Graph) -> None:
        if self.skip_in_friendship_graph:
            return
        n = self.name
        dc = "#111111"
        c = self.color if self.color else dc
        t = f"Meets {len(self.roster)} others"
        t += " (looper)" if self.has_loop else ""
        u = self.jsa(
            (
                (
                    f"{n} meets\n➡"
                    + "\n➡".join(
                        f"{x.name}\t({self.count_meetings(x)[0]} times)"
                        for x in self.roster
                    )
                )
                if self.roster
                else f"{n} is lonely"
            )
            + f"\nover {len(set(self.events))} events"
        )
        g.node(
            n, color=c, tooltip=t, shape="signature", URL=u,
        )
        general_args: Dict[str, str] = {
            "penwidth": "2",
        }
        for r in self.mod_roster:
            x = r.color if r.color else dc
            rn = r.name
            color = f"{c}:{x}"
            d = ""
            m, e = self.count_meetings(r)
            tt = f"{n}--{rn}\nMeet {m} times"
            if r == self:
                if not m:
                    continue
                color, d = c, "forward"
                tt = f"{n}\n{m} self-encounters"
            g.edge(
                n,
                rn,
                **general_args,
                color=color,
                dir=d,
                tooltip=tt + f" over {e} events",
                weight="0" if r == self else str(m),
                labelfontname="monospace",
                labelfontsize="8",
                URL=self.jsa(
                    tt + ":\n➡" + "\n➡".join(n.name for n in self.shared_events(r))
                ),
            )

    def shared_events(self, c: "Character") -> Set[Event]:
        return {e for e in self.events if e.attendees[c] > (1 if c == self else 0)}

    def count_meetings(self, c: "Character") -> Tuple[int, int]:
        """
        :param c: who did you meet?
        :return: how many times did you meet over how many events?
        """
        meeting_list: List[int] = [
            e.attendees[c] - (1 if c == self else 0) for e in set(self.events)
        ]
        return sum(meeting_list), len([i for i in meeting_list if i > 0])


class Combiner(Set[Character], EventConnector):
    def __init__(
        self, s: "Storyboard", name: str, *chars: Union[Character, str], **kwargs
    ):
        self.chars = frozenset(
            c if isinstance(c, Character) else s.dramatis_personae[c] for c in chars
        )
        EventConnector.__init__(self, name, s, **kwargs)
        if len(chars) == 1:  # called from the Character.__init__
            self.color = chars[0].color
            self.short_name = chars[0].short_name
        assert (
            self.chars not in s.grouped_roster.keys()
        ), f"A combiner with {chars} already exists"
        s.grouped_roster[self.chars] = self
        self.priority: int = kwargs.get("num", 0)

    @property
    def roster(self) -> "Set[Character]":
        return set(self.chars)

    @staticmethod
    def size_key(c: "Combiner") -> int:
        return len(c.chars) * 1000 + c.priority

    def build_bridges(self) -> None:
        """
        Generates index numbers for all bridges
        """
        if len(self.chars) == 1:
            for b in self.bridges:
                b.index = b.child_bridges[0].index
            return
        index_char: Character = sorted(self.chars, key=lambda c: len(c.events))[-1]
        for x, b in enumerate(
            sorted(self.bridges, key=lambda z: z.child_bridge_by_char[index_char].index)
        ):
            b.index = x + 1


class Storyboard(EventConnector):
    def __init__(
        self,
        *,
        name: Optional[str] = None,
        file=None,
        load_final: bool = True,
        g_attr: Optional[Dict[str, str]] = None,
        **kwargs,
    ):
        assert name or file, f"Need a name or a file to load from"
        if not name:
            name = file.split(".tsv")[0]
        super().__init__(name, self, **kwargs)

        # set up all the blank variables
        self.line_list: Dict[str, LineType] = {}
        self.event_list: Dict[str, Event] = {}
        self.is_final: bool = False
        self.line_loaders: Dict[str, Callable] = {
            "TIMELINE": self.create_timeline,
            "EVENT": self.create_event,
            "CHARACTER": self.create_character,
            "COMMENT": self.create_comment,
            "COMBINER": self.create_combiner,
            "OBJECT": self.create_character,
        }
        self.dramatis_personae: Dict[str, Character] = {}
        self.graph = gv.Digraph(name=self.name)
        self.graph.attr(compound="True", **g_attr)
        self.timelines: Set[Timeline] = set()
        self.places: Set[Place] = set()
        self.direction: str = g_attr.get("rankdir", "LR")
        self.color_names: bool = kwargs.get("color_names")
        self.friendships = gv.Graph(
            name=f"{self.name}~friendships",
            strict=True,
            graph_attr={"fontname": "signature"},
        )
        self.links2process: DefaultDict[
            Tuple[EventType, EventType], List[EventBridge]
        ] = defaultdict(lambda: [])
        self.grouped_roster: Dict[FrozenSet[Character], Combiner] = {}

        if not file:
            return
        self.load_file(file)
        if load_final:
            self.finalize()
            self.make_graph()

    def load_file(self, file, /):
        f = csv.DictReader(open(file, "r"), delimiter="\t")
        l: int = 0
        for line in f:
            if not line["TYPE"].strip():
                continue  # skip blank lines without throwing an error
            fn: Callable = self.line_loaders.get(line["TYPE"].upper().strip())
            if not fn:
                click.echo(f"invalid line: {line}", err=True)
                continue
            color: Optional[str] = line["COLOR"].strip() if line["COLOR"] else None
            everything_else: List[str] = line.get(None, [])  # noqa
            fn(
                line["NAME"],
                line["SHORTNAME"],
                *everything_else,
                color=color,
                num=(l := l + 1),
            )

    @property
    def nested_lines(self) -> "Dict[Timeline, Set[Place]]":
        return {t: t.places for t in self.timelines}

    @property
    def location_count(self) -> int:
        return sum(len(v) for v in self.nested_lines.values())

    def finalize(self):
        """Adds start/end events for better graph output"""
        if self.is_final:
            return
        for t in self.timelines:
            if not t.timestamps:
                EventAnchor(f"empty-{t.name}-start", t, -1, opener=True)
                EventAnchor(f"empty-{t.name}-finish", t, 1, closer=True)
            else:
                EventAnchor(f"{t.name} start", t, t.timestamps[0] - 1, opener=True)
                EventAnchor(f"{t.name} finish", t, t.timestamps[-1] + 1, closer=True)
        for t in set(self.line_list.values()):
            t.sort_events()
            t.build_bridges()
        for c in self.roster:
            c.build_bridges()
        self.build_bridges()  # more like sort/process bridges
        self.is_final = True

    def build_bridges(self):
        """This should be called sort_bridges"""
        for past, future in self.links2process:
            y = []
            for bridge in self.links2process[past, future]:
                if isinstance(bridge.seq, Character):
                    y.append(bridge)
                else:
                    self.bridges.append(bridge)
            while y:  # convert Character lines into Combiner lines
                c_out: Combiner = sorted(
                    [
                        s
                        for s in self.grouped_roster.values()
                        if s.chars <= {b.seq for b in y}
                    ],
                    key=Combiner.size_key,
                )[
                    -1
                ]  # find the longest matching Combiner
                b = EventBridge(c_out, 0, past, future)
                for c in c_out.chars:
                    e: EventBridge = [r for r in y if r.seq == c][0]
                    y.remove(e)
                    b.child_bridges.append(e)
                c_out.bridges.append(b)
        for combo in self.grouped_roster.values():
            combo.build_bridges()
            self.bridges.extend(combo.bridges)

    @property
    def events(self) -> "List[EventType]":
        """Returns a list of events that characters may attend"""
        return [e for e in self.event_list.values() if e.can_attend]

    @property
    def timeboxen(self) -> "List[EventType]":
        """
        Returns the list of event anchors created by the story
        (ignores the start/stop boxen)
        """
        return [
            e
            for e in self.event_list.values()
            if not e.can_attend and not (e.opener or e.closer)
        ]

    def output(self, quiet: bool = False, formats: List[str] = None):
        if formats is None:
            formats = ["pdf"]
        else:
            formats = [f.strip().lower() for f in formats]
        if not self.is_final:
            self.make_graph()
        stats = "\n".join(
            [
                f"{len(self.events)} events",
                f"\t(sorted into {len(self.timeboxen)} timeboxen)",
                f"{len(self.roster)} characters",
                f"\t({len([k for k in self.grouped_roster.keys() if len(k) > 1])} combined groups)",
                f"{len(set(self.line_list.values()))} timelines and places",  # always plural
            ]
        )
        click.echo(stats)
        self.graph.attr(tooltip=f"{self.name}\n{stats}")
        for f in formats:
            if not f:
                continue
            try:
                self.graph.render(format=f, quiet_view=False if quiet else True)
                self.friendships.render(format=f, quiet_view=False if quiet else True)
            except ValueError:
                click.echo(f"Skipping invalid format {f}", err=True)
                continue

    def make_graph(self) -> None:
        """Converts the loaded data into a graph"""
        if not self.is_final:
            self.finalize()
        # 1. create timelines, timeboxen, and events
        for t in self.timelines:
            self.graph.subgraph(
                t.make_graph(
                    only_one=True if len(self.timelines) < 2 else False,
                    direction=self.direction,
                    color_names=self.color_names,
                )
            )
        # 2. make the friendship graph
        for c in self.roster:
            c.draw_friendships(self.friendships)
        # 3. add connecting lines to the graph
        for b in self.bridges:
            b.draw_line(self.graph, color_labels=self.color_names)

    @property
    def roster(self) -> "Set[Character]":
        return set(self.dramatis_personae.values())

    def create_timeline(self, name: str, short_name: str, *places: str, **kwargs):
        places = [p for p in places if p]
        t = Timeline(
            self, name if places else f"{name}-tl", short_name=short_name, **kwargs,
        )
        if not places:  # single-place timelines
            Place(self, t, name, **kwargs)
        for p in places:
            Place(self, t, p, **kwargs)
        return t

    def create_event(self, name: str, timestamp: str, *args: str, **kwargs):
        assert args, f"Insufficient information to create an event: {name} {timestamp}"
        assert (
            tl := args[0].lower().strip()
        ) in self.line_list.keys(), f"{tl} isn't a real place"
        line = self.line_list[tl]
        if len(args) > 1 and args[1]:
            kwargs["vegan"] = True  # pun on "no meet"
        return (
            Event(name, line, int(timestamp), **kwargs)
            if isinstance(line, Place)
            else EventAnchor(name, line, int(timestamp), **kwargs)
        )

    def create_character(self, name: str, short_name: str, *events: str, **kwargs):
        return Character(self, name, *events, short_name=short_name, **kwargs)

    @staticmethod
    def create_comment(*args, **kwargs):
        """Skips a comment without throwing an error"""
        pass

    def create_combiner(self, name: str, short_name: str, *chars: str, **kwargs):
        assert len(chars) > 1, f"Cannot create combiner {name}: too few characters."
        return Combiner(self, name, *chars, short_name=short_name, **kwargs)


@click.command()
@click.argument(
    "loadfile",
    type=click.Path(exists=True, dir_okay=False, readable=True, allow_dash=True),
)
@click.option(
    "-d",
    "--dir",
    "rankdir",
    type=click.Choice(["TB", "LR", "BT", "RL"], case_sensitive=False),
    default="LR",
    help="""
    Rendering direction of the output
    
    The default left to right format works very nicely on simple storyboards.
    Top to bottom rendering tends to produce better results on very complex
    stories.  However, you will need to experiment both ways to discover which better
    suits your plot.
    """,
)
@click.option(
    "-o",
    "--format",
    "output_list",
    type=click.STRING,
    multiple=True,
    default=["svg", "pdf"],
    help="""
    Output format as specified by http://www.graphviz.org/doc/info/output.html
    
    Repeat to render to multiple formats at once.
    Two .gv files are always produced.
    Invalid formats are skipped.
    
    Output files all end with '.gv*': run 'rm *.gv*' to clean up.
    Input tsv files are left untouched.
    """,
)
@click.option(
    "-q",
    "--quiet",
    type=click.BOOL,
    is_flag=True,
    help="Do not open the output file(s) immediately after render.",
)
@click.option(
    "-c",
    "--color-names",
    type=click.BOOL,
    is_flag=True,
    help="Names follow their associated line color",
)
def main(
    loadfile, rankdir: str, output_list: List[str], quiet: bool, color_names: bool
):
    s = Storyboard(
        file=loadfile,
        g_attr={"rankdir": rankdir.upper().strip()},
        color_names=color_names,
    )
    s.output(quiet, output_list)


if __name__ == "__main__":
    main()
