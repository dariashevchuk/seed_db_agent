from __future__ import annotations
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field, HttpUrl, validator


class BudgetHard(BaseModel):
    max_actions: int = 40
    time_budget_s: int = 120


class BudgetSoft(BaseModel):
    plateau_window: int = 4
    min_new_ratio: float = 0.15  # new frontier / actions in last window


class StopConfig(BaseModel):
    hard: BudgetHard = BudgetHard()
    soft: BudgetSoft = BudgetSoft()


class Anchor(BaseModel):
    text: Optional[str] = None
    href: str


class Snapshot(BaseModel):
    url: str
    title: Optional[str] = None
    site_name: Optional[str] = None
    meta_description: Optional[str] = None
    markdown: Optional[str] = None
    html_truncated: Optional[str] = None
    jsonld_objects: List[Dict[str, Any]] = Field(default_factory=list)
    anchors: List[Anchor] = Field(default_factory=list)


ActionType = Literal["GOTO", "SCROLL", "OPEN_SITEMAP", "OPEN_ROBOTS", "SWITCH_LANGUAGE"]


class Action(BaseModel):
    type: ActionType
    url: Optional[str] = None
    pattern: Optional[str] = None
    arg: Optional[str] = None


class Plan(BaseModel):
    start_url: str
    same_domain_only: bool = True
    domain_allowlist: List[str] = Field(default_factory=list)
    prefer_languages: List[str] = Field(default_factory=lambda: ["uk", "en"])
    stop: StopConfig = StopConfig()


class Metrics(BaseModel):
    actions_total: int = 0
    pages_visited: int = 0
    frontier_size: int = 0
    new_in_window: int = 0
    window_actions: List[int] = Field(default_factory=list)   # rolling window of actions per step
    window_new: List[int] = Field(default_factory=list)       # rolling window of discovered links per step

    def push_window(self, actions: int, new_links: int, window: int) -> None:
        self.window_actions.append(actions)
        self.window_new.append(new_links)
        if len(self.window_actions) > window:
            self.window_actions.pop(0)
            self.window_new.pop(0)

    @property
    def frontier_new_ratio(self) -> float:
        a = sum(self.window_actions) or 1
        n = sum(self.window_new)
        return n / a


class WalkState(BaseModel):
    visited: List[str] = Field(default_factory=list)
    frontier: List[str] = Field(default_factory=list)
    metrics: Metrics = Metrics()


class OrganizationOut(BaseModel):
    organization_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    website: Optional[str] = None
    contact_email: Optional[str] = None
    created_at: Optional[str] = None


class ProjectOut(BaseModel):
    project_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    created_at: Optional[str] = None
    organization_id: Optional[int] = None
    source_url: Optional[str] = None


class ReflectOutput(BaseModel):
    done: bool = False
    coverage: Literal["none", "partial", "sufficient"] = "partial"
    justification: Optional[str] = None
    organization: Optional[OrganizationOut] = None
    projects: List[ProjectOut] = Field(default_factory=list)
    goto_urls: List[str] = Field(default_factory=list)
    actions: List[Action] = Field(default_factory=list)
    