"""Pydantic models for Zoho Desk ticket creation request and response."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class ContactModel(BaseModel):
    """Contact information attached to the Zoho Desk ticket."""

    lastName: str = Field(
        ...,
        min_length=1,
        description="Contact last name (required by Zoho Desk).",
        examples=["Doe"],
    )
    firstName: str | None = Field(
        default=None,
        description="Contact first name.",
        examples=["Jane"],
    )
    email: str | None = Field(
        default=None,
        description="Contact email address.",
        examples=["jane.doe@example.com"],
    )
    phone: str | None = Field(
        default=None,
        description="Contact phone number.",
        examples=["+1-555-0123"],
    )

    model_config = {"populate_by_name": True, "str_strip_whitespace": True}


class TicketRequest(BaseModel):
    """Payload accepted by ``POST /v1/tickets`` to create a Zoho Desk ticket."""

    subject: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Short summary shown as the ticket title.",
        examples=["Code Stroke Alert - MRN 123456"],
    )
    description: str = Field(
        ...,
        min_length=1,
        description="HTML or plain-text body of the ticket.",
        examples=["<p>Stroke alert triggered at 14:32 UTC for MRN 123456.</p>"],
    )
    departmentId: str | None = Field(
        default=None,
        description="Zoho department ID. Falls back to ZOHO_DESK_DEFAULT_DEPARTMENT_ID env var.",
        examples=["1166045000000006907"],
    )
    contact: ContactModel = Field(
        ...,
        description="Contact to attach to the ticket (Zoho requires at least lastName).",
    )

    # Product resolution — supply either productId (fast) or productName (resolved via PRODUCT_MAP / API).
    productId: str | None = Field(
        default=None,
        description="Zoho product ID. Preferred path — skips any lookup.",
        examples=["1166045000001146278"],
    )
    productName: str | None = Field(
        default=None,
        description=(
            "Human-readable product name (e.g. 'Code Stroke Alert'). "
            "Resolved to productId via the PRODUCT_MAP in .env, "
            "or by querying the Zoho products API on cache miss."
        ),
        examples=["Code Stroke Alert"],
    )

    channel: str | None = Field(
        default=None,
        description="Communication channel for the ticket.",
        examples=["Phone", "Email", "SMS"],
    )
    priority: str | None = Field(
        default=None,
        description="Ticket priority level.",
        examples=["High", "Medium", "Low"],
    )
    status: str | None = Field(
        default=None,
        description="Initial ticket status.",
        examples=["Open", "Escalated"],
    )
    phone: str | None = Field(
        default=None,
        description="Customer phone number (top-level, separate from contact).",
        examples=["+1-555-0123"],
    )
    email: str | None = Field(
        default=None,
        description="Customer email address (top-level, separate from contact).",
        examples=["patient@example.com"],
    )
    category: str | None = Field(
        default=None,
        description="Ticket category.",
        examples=["Radiology"],
    )
    classification: str | None = Field(
        default=None,
        description="Ticket classification.",
        examples=["Urgent"],
    )
    extra: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Arbitrary key-value pairs merged into the outgoing Zoho payload. "
            "Use this for any Zoho Desk fields not covered above."
        ),
        examples=[{"cf_medical_record_number_mrn": "123456"}],
    )

    model_config = {
        "populate_by_name": True,
        "str_strip_whitespace": True,
        "json_schema_extra": {
            "examples": [
                {
                    "subject": "Code Stroke Alert - MRN 123456",
                    "description": "<p>Stroke alert triggered at 14:32 UTC.</p>",
                    "contact": {"lastName": "Doe", "firstName": "Jane"},
                    "productName": "Code Stroke Alert",
                    "departmentId": "1166045000000006907",
                    "priority": "High",
                }
            ]
        },
    }

    @model_validator(mode="after")
    def _check_product_fields(self) -> TicketRequest:
        """Warn-free: if both productId and productName are given, productId wins."""
        return self


class TicketResponse(BaseModel):
    """Payload returned after a ticket is successfully created."""

    id: str = Field(
        ...,
        description="Zoho internal ticket ID.",
        examples=["1166045000006881756"],
    )
    ticketNumber: str = Field(
        ...,
        description="Human-readable ticket number (visible in Zoho Desk UI).",
        examples=["6846"],
    )
    webUrl: str | None = Field(
        default=None,
        description="Direct link to the ticket in the Zoho Desk web UI.",
        examples=["https://desk.zoho.com/support/webzter/ShowHomePage.do#Cases/dv/1166045000006881756"],
    )
    subject: str = Field(
        ...,
        description="Confirmed ticket subject.",
        examples=["Code Stroke Alert - MRN 123456"],
    )
    raw: dict[str, Any] = Field(
        ...,
        description="Full JSON response from the Zoho Desk API.",
    )

    model_config = {"populate_by_name": True}


class ErrorResponse(BaseModel):
    """Standard error envelope returned for all non-2xx responses."""

    detail: str = Field(
        ...,
        description="Human-readable error message.",
        examples=["departmentId is required"],
    )
    request_id: str | None = Field(
        default=None,
        description="Correlation ID for request tracing (echoed from X-Request-ID header).",
        examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
    )
