"""
Week 1 - Access Control & Authorization Tests

Project: Intelligent Document Processing & Workflow Automation
Member: 4 - Brijesh

Purpose:
Verify document ownership, upload permissions,
processing result access, and report permissions.
"""

import pytest

from app.security.permissions import (
    AuthenticatedUser,
    OwnedResource,
    is_authenticated_actor,
    can_upload_document,
    can_access_document,
    can_access_result,
    can_download_report,
)


# Test users
OWNER = AuthenticatedUser("user_101", True)
OTHER_USER = AuthenticatedUser("user_102", True)
INACTIVE_USER = AuthenticatedUser("user_101", False)

# Test document
DOCUMENT = OwnedResource("doc_001", "user_101")


# -----------------------------------------
# TESTS 1-4: USER STATUS
# -----------------------------------------

@pytest.mark.parametrize(
    "actor, expected",
    [
        (OWNER, True),
        (INACTIVE_USER, False),
        (None, False),
        (AuthenticatedUser("", True), False),
    ],
)
def test_user_authentication_status(actor, expected):
    assert is_authenticated_actor(actor) is expected


# -----------------------------------------
# TESTS 5-7: UPLOAD PERMISSIONS
# -----------------------------------------

@pytest.mark.parametrize(
    "actor, expected",
    [
        (OWNER, True),
        (INACTIVE_USER, False),
        (None, False),
    ],
)
def test_upload_permission(actor, expected):
    assert can_upload_document(actor) is expected


# -----------------------------------------
# TESTS 8-15: DOCUMENT ACCESS
# -----------------------------------------

@pytest.mark.parametrize(
    "actor, document, expected",
    [
        (OWNER, DOCUMENT, True),
        (OTHER_USER, DOCUMENT, False),
        (None, DOCUMENT, False),
        (INACTIVE_USER, DOCUMENT, False),
        (OWNER, OwnedResource("doc_001", ""), False),
        (OWNER, OwnedResource("", "user_101"), False),
        (OWNER, None, False),
        (OWNER, "invalid_document", False),
    ],
)
def test_document_access(actor, document, expected):
    assert can_access_document(actor, document) is expected


# -----------------------------------------
# TESTS 16-17: PROCESSING RESULTS
# -----------------------------------------

@pytest.mark.parametrize(
    "actor, expected",
    [
        (OWNER, True),
        (OTHER_USER, False),
    ],
)
def test_processing_result_access(actor, expected):

    result = OwnedResource(
        resource_id="result_001",
        owner_user_id="user_101"
    )

    assert can_access_result(actor, result) is expected


# -----------------------------------------
# TESTS 18-19: REPORT DOWNLOADS
# -----------------------------------------

@pytest.mark.parametrize(
    "actor, expected",
    [
        (OWNER, True),
        (OTHER_USER, False),
    ],
)
def test_report_download_permission(actor, expected):

    report = OwnedResource(
        resource_id="report_001",
        owner_user_id="user_101"
    )

    assert can_download_report(actor, report) is expected