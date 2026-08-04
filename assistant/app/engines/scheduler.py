from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, time
from typing import Optional, List, Dict, Any, Tuple

SLOT_MINUTES = 30
QUADRANT_PRIORITY = {"urgent_important": 0, "important": 1, "urgent": 2, "neither": 3}


@dataclass
class UserPreferences:
    wake_up: time = time(7, 0)
    work_start: time = time(9, 0)
    work_end: time = time(18, 0)
    sleep_time: time = time(23, 0)
    peak_hours: Tuple[time, time] = (time(9, 0), time(12, 0))
    lunch_break: Tuple[time, time] = (time(12, 0), time(13, 0))


@dataclass
class ScheduleSlot:
    start_time: time
    end_time: time
    slot_type: str
    title: str = ""
    linked_id: Optional[Any] = None


@dataclass
class ScheduleResult:
    date: date
    slots: List[ScheduleSlot]
    version: int = 1


@dataclass
class ScheduleInput:
    date: date
    preferences: UserPreferences
    tasks: List[Dict[str, Any]]
    habits: List[Dict[str, Any]]
    calendar_events: List[Dict[str, Any]]


def _time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute

def _minutes_to_time(m: int) -> time:
    return time(m // 60, m % 60)


class SchedulerEngine:
    def generate(self, input: ScheduleInput) -> ScheduleResult:
        prefs = input.preferences
        work_start = _time_to_minutes(prefs.work_start)
        work_end = _time_to_minutes(prefs.work_end)
        lunch_start = _time_to_minutes(prefs.lunch_break[0])
        lunch_end = _time_to_minutes(prefs.lunch_break[1])
        peak_start = _time_to_minutes(prefs.peak_hours[0])

        all_slots: Dict[int, ScheduleSlot] = {}
        t = work_start
        while t < work_end:
            end = min(t + SLOT_MINUTES, work_end)
            all_slots[t] = ScheduleSlot(start_time=_minutes_to_time(t), end_time=_minutes_to_time(end), slot_type="free")
            t += SLOT_MINUTES

        # Lunch break
        t = lunch_start
        while t < lunch_end:
            if t in all_slots:
                all_slots[t] = ScheduleSlot(start_time=_minutes_to_time(t), end_time=_minutes_to_time(t + SLOT_MINUTES), slot_type="break", title="Lunch")
            t += SLOT_MINUTES

        # Calendar events (immovable)
        for event in input.calendar_events:
            ev_start = _time_to_minutes(event["start"])
            ev_end = _time_to_minutes(event["end"])
            t = ev_start
            while t < ev_end:
                if t in all_slots:
                    all_slots[t] = ScheduleSlot(start_time=_minutes_to_time(t), end_time=_minutes_to_time(t + SLOT_MINUTES), slot_type="calendar_event", title=event.get("title", ""), linked_id=event.get("id"))
                t += SLOT_MINUTES

        # Habits at preferred times
        for habit in input.habits:
            duration = habit.get("duration_minutes", 30)
            preferred = _time_to_minutes(habit.get("preferred_time", prefs.work_end))
            slots_needed = max(1, duration // SLOT_MINUTES)
            self._place_item(all_slots, preferred, slots_needed, work_start, work_end, "habit", habit.get("title", ""), habit.get("id"))

        # Tasks sorted by priority
        sorted_tasks = sorted(input.tasks, key=lambda t: QUADRANT_PRIORITY.get(t.get("quadrant", "neither"), 3))
        for task in sorted_tasks:
            duration = task.get("estimated_minutes", 30)
            slots_needed = max(1, (duration + SLOT_MINUTES - 1) // SLOT_MINUTES)
            priority = QUADRANT_PRIORITY.get(task.get("quadrant", "neither"), 3)
            start_from = peak_start if priority <= 1 else work_start
            self._place_item(all_slots, start_from, slots_needed, work_start, work_end, "task", task.get("title", ""), task.get("id"))

        sorted_times = sorted(all_slots.keys())
        return ScheduleResult(date=input.date, slots=[all_slots[t] for t in sorted_times])

    def _place_item(self, slots, preferred_start, count, range_start, range_end, slot_type, title, linked_id) -> bool:
        if self._try_place(slots, preferred_start, count, range_end, slot_type, title, linked_id):
            return True
        t = range_start
        while t < range_end:
            if self._try_place(slots, t, count, range_end, slot_type, title, linked_id):
                return True
            t += SLOT_MINUTES
        return False

    def _try_place(self, slots, start, count, range_end, slot_type, title, linked_id) -> bool:
        times = []
        t = start
        for _ in range(count):
            if t >= range_end or t not in slots or slots[t].slot_type != "free":
                return False
            times.append(t)
            t += SLOT_MINUTES
        for t in times:
            slots[t] = ScheduleSlot(start_time=_minutes_to_time(t), end_time=_minutes_to_time(t + SLOT_MINUTES), slot_type=slot_type, title=title, linked_id=linked_id)
        return True
