"""
Access Control and Authorization Module

Project: Intelligent Document Processing & Workflow Automation
Member: 4 - Brijesh
Week: 1

Purpose:
Control access to uploaded documents, processing results,
and generated reports.

Note:
This module performs authorization only.
Authentication must be handled by the backend.
"""

from dataclasses import dataclass


# ----------------------------------------
# 1. USER MODEL
# ----------------------------------------

@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    is_active: bool


# ----------------------------------------
# 2. RESOURCE MODEL
# ----------------------------------------

@dataclass(frozen=True)
class OwnedResource:
    resource_id: str
    owner_user_id: str


# ----------------------------------------
# 3. IDENTIFIER VALIDATION
# ----------------------------------------

def _valid_identifier(value: object) -> bool:
    """Check if an identifier is a non-empty string."""

    return isinstance(value, str) and bool(value.strip())


# ----------------------------------------
# 4. CHECK USER STATUS
# ----------------------------------------

def is_authenticated_actor(actor: object) -> bool:
    """
    Check whether a trusted user context
    represents an active user.

    This does not authenticate passwords or tokens.
    """

    return (
        isinstance(actor, AuthenticatedUser)
        and actor.is_active is True
        and _valid_identifier(actor.user_id)
    )


# ----------------------------------------
# 5. DOCUMENT UPLOAD PERMISSION
# ----------------------------------------

def can_upload_document(actor: object) -> bool:
    """
    Allow active authenticated users to upload documents.
    """

    return is_authenticated_actor(actor)


# ----------------------------------------
# 6. RESOURCE ACCESS PERMISSION
# ----------------------------------------

def can_access_owned_resource(
    actor: object,
    resource: object
) -> bool:
    """
    Allow access only when the authenticated
    user owns the requested resource.
    """

    return (
        is_authenticated_actor(actor)
        and isinstance(resource, OwnedResource)
        and _valid_identifier(resource.resource_id)
        and _valid_identifier(resource.owner_user_id)
        and actor.user_id == resource.owner_user_id
    )


# ----------------------------------------
# 7. DOCUMENT ACCESS
# ----------------------------------------

def can_access_document(
    actor: object,
    document: object
) -> bool:
    """
    Check permission to access an uploaded document.
    """

    return can_access_owned_resource(actor, document)


# ----------------------------------------
# 8. PROCESSING RESULT ACCESS
# ----------------------------------------

def can_access_result(
    actor: object,
    result: object
) -> bool:
    """
    Check permission to access processing results.
    """

    return can_access_owned_resource(actor, result)


# ----------------------------------------
# 9. REPORT DOWNLOAD PERMISSION
# ----------------------------------------

def can_download_report(
    actor: object,
    report: object
) -> bool:
    """
    Check permission to download a generated report.
    """

    return can_access_owned_resource(actor, report)
