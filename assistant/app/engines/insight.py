from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, time
from typing import List, Dict, Any, Tuple


def _slot_minutes(start: time, end: time) -> int:
    return (end.hour*60+end.minute) - (start.hour*60+start.minute)


@dataclass
class DailyStats:
    date: date
    completion_rate: float = 0.0
    total_planned_minutes: int = 0
    meeting_minutes: int = 0
    screen_time_minutes: int = 0
    time_distribution: Dict[str, int] = field(default_factory=dict)


@dataclass
class WeeklyStats:
    avg_completion_rate: float = 0.0
    total_planned_minutes: int = 0
    total_meeting_minutes: int = 0
    avg_screen_time_minutes: float = 0.0
    habit_adherence: Dict[str, float] = field(default_factory=dict)
    time_distribution: Dict[str, int] = field(default_factory=dict)


class InsightEngine:
    def compute_daily(self, date: date, planned_slots: List[Dict[str, Any]], completed_task_ids: List[int], total_task_ids: List[int], screen_time_minutes: int = 0) -> DailyStats:
        total_min = 0
        meeting_min = 0
        dist: Dict[str, int] = {}
        for slot in planned_slots:
            minutes = _slot_minutes(slot["start"], slot["end"])
            total_min += minutes
            st = slot.get("type", "free")
            dist[st] = dist.get(st, 0) + minutes
            if st == "calendar_event":
                meeting_min += minutes
        rate = len(completed_task_ids) / len(total_task_ids) if total_task_ids else 0.0
        return DailyStats(date=date, completion_rate=rate, total_planned_minutes=total_min, meeting_minutes=meeting_min, screen_time_minutes=screen_time_minutes, time_distribution=dist)

    def compute_weekly(self, daily_stats: List[DailyStats], habit_completions: Dict[str, Tuple[int, int]]) -> WeeklyStats:
        if not daily_stats:
            return WeeklyStats()
        avg_rate = sum(d.completion_rate for d in daily_stats) / len(daily_stats)
        total_planned = sum(d.total_planned_minutes for d in daily_stats)
        total_meeting = sum(d.meeting_minutes for d in daily_stats)
        avg_screen = sum(d.screen_time_minutes for d in daily_stats) / len(daily_stats)
        dist: Dict[str, int] = {}
        for d in daily_stats:
            for k, v in d.time_distribution.items():
                dist[k] = dist.get(k, 0) + v
        habit_adh = {name: done/target if target > 0 else 0.0 for name, (done, target) in habit_completions.items()}
        return WeeklyStats(avg_completion_rate=avg_rate, total_planned_minutes=total_planned, total_meeting_minutes=total_meeting, avg_screen_time_minutes=avg_screen, habit_adherence=habit_adh, time_distribution=dist)

    def compute_goal_progress(self, goals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [{"title": g["title"], "target": g.get("target", 1), "current": g.get("current", 0), "progress": g.get("current", 0) / g.get("target", 1) if g.get("target", 1) > 0 else 0.0} for g in goals]
