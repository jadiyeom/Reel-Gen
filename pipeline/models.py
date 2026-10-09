"""Pydantic schema for the image-first script/scene JSON the LLM returns.

v2: no on-screen text. Each scene is a distinct cinematic image + one spoken line.
The only text the viewer sees is the karaoke captions.
"""
from __future__ import annotations

from typing import List, Literal
from pydantic import ValidationInfo, model_validator

from pydantic import BaseModel, Field


class Scene(BaseModel):
    index: int = Field(..., description="1-based scene order")
    image_prompt: str = Field("", description="A specific conceptual illustration direction; no generated text.")
    narration: str = Field(..., description="One spoken sentence for this scene")
    motion_prompt: str = Field(
        "", description="If this is the hero scene, what should move (for Wan i2v)"
    )
    hero: bool = Field(False, description="Mark ONE scene as the hero for optional Wan motion")
    scene_type: Literal["image", "blank", "image_with_text"] = "image"
    overlay_text: str = ""
    caption_position: Literal["top", "middle", "bottom"] | None = None


class Article(BaseModel):
    url: str
    title: str = ""
    author: str = ""
    published: str = ""
    site_name: str = ""
    content: str
    content_hash: str = ""


class ContentAnalysis(BaseModel):
    summary: str
    strongest_idea: str
    supporting_facts: List[str] = Field(default_factory=list)
    source_title: str = ""


class TimelineScene(BaseModel):
    index: int
    scene_type: Literal["image", "blank", "image_with_text"]
    start: float
    end: float
    narration: str


class Timeline(BaseModel):
    scenes: List[TimelineScene]
    duration: float


class Script(BaseModel):
    topic: str
    slug: str = Field(..., description="kebab-case file-safe slug")
    scenes: List[Scene] = Field(..., min_length=4, max_length=100)
    # Per-platform social copy.
    youtube_title: str
    youtube_description: str
    tiktok_caption: str
    x_caption: str
    hashtags: List[str]
    instagram_caption: str = ""

    @model_validator(mode="after")
    def validate_illustration_count(self, info: ValidationInfo):
        count = sum(s.scene_type != "blank" for s in self.scenes)
        extended = bool((info.context or {}).get("allow_extended_storyboard"))
        if len(self.scenes) > 12 and not extended:
            raise ValueError("Short-form storyboards may contain at most 12 scenes")
        max_illustrations = 100 if extended else 8
        min_illustrations = 1 if extended else 4
        if count < min_illustrations or count > max_illustrations:
            if extended:
                raise ValueError("An extended storyboard must contain 1–100 illustrated scenes; blank scenes do not count")
            raise ValueError("A storyboard must contain 4–8 illustrations; blank scenes do not count")
        return self
