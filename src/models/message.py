"""Canonical message models for the multi-channel sales agent."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class MediaAttachment(BaseModel):
    """Media attached to an inbound or outbound message."""
    type: Literal["image", "video", "audio", "document"]
    url: str
    mime_type: str | None = None
    caption: str | None = None


class InboundMessage(BaseModel):
    """What arrives from any channel — normalized.
    
    The channel adapter translates the platform-specific webhook
    payload into this channel-agnostic format.
    """
    channel: Literal["whatsapp", "instagram", "telegram", "web", "messenger"]
    channel_message_id: str
    channel_user_id: str
    tenant_id: str
    thread_id: str | None = None
    text: str | None = None
    media: list[MediaAttachment] = Field(default_factory=list)
    raw_payload: dict = Field(default_factory=dict)
    received_at: datetime


class OutboundMessage(BaseModel):
    """What the agent produces — channel adapter renders it.
    
    The agent outputs this channel-agnostic message, which the
    channel adapter then translates into platform-specific API calls.
    """
    text: str | None = None
    media: list[MediaAttachment] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
