"""Pydantic models for ticket creation request and response."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ContactModel(BaseModel):
    lastName: str
    firstName: str | None = None
    email: str | None = None
    phone: str | None = None


class TicketRequest(BaseModel):
    subject: str
    description: str
    departmentId: str | None = None
    contact: ContactModel
    productId: str | None = None
    productName: str | None = None
    channel: str | None = None
    priority: str | None = None
    status: str | None = None
    phone: str | None = None
    email: str | None = None
    category: str | None = None
    classification: str | None = None
    extra: dict[str, Any] | None = None


class TicketResponse(BaseModel):
    id: str
    ticketNumber: str
    webUrl: str | None = None
    subject: str
    raw: dict[str, Any]
