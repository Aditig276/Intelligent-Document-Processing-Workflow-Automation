# Week 1 — Django authorization integration handoff

**Module:** Access Control & Authorization
**Member:** Brijesh (Member 4)
**PR:** #2 (`feature/access-control`)

## Implemented now

- Independent owner-only permission policy: `app/security/permissions.py`.
- Django request-user/ProcessingJob adapter: `app/security/django_adapter.py`.
- Framework-independent unit tests and additional adapter tests.
- Default-deny behavior for anonymous/inactive users, missing job ownership, and users who do not own a job.

## Still required from backend/database teammates

1. Confirm Django as the shared backend and resolve the two branches' overlapping `config/*` and `manage.py` files.
2. Add a `ProcessingJob.owner` ForeignKey referencing `settings.AUTH_USER_MODEL` with an approved migration strategy for existing jobs. **Do not automatically assign old jobs to the current user.** If older records have unknown owners, keep them inaccessible until correctly attributed or migrated under an approved policy.
3. Configure Django's real session authentication and secure login/logout routes; enable CSRF protection for state-changing form endpoints.
4. On upload, require an authenticated user, and write `owner=request.user` server-side. Never accept owner IDs from form fields.
5. Update the dashboard to query only `ProcessingJob.objects.filter(owner=request.user)` after authentication.
6. In each job-specific view, look up the job through an owner-scoped queryset, e.g. `get_object_or_404(ProcessingJob, pk=job_id, owner=request.user)`, **before** reading document contents, processing results, or downloads. The adapter function can provide an additional explicit permission check after retrieving the job.
7. Ensure generated result/report records inherit or reference the original job's owner; protect any direct storage URLs as well.
8. Keep extraction/status mutations to POST actions protected by CSRF; the current `extract_job` modifies status during GET and needs correction.
9. Add Django `TestCase`/client integration tests confirming unauthenticated access is blocked, one user cannot list/view/process/download another user's job, and the owner can use authorized endpoints.
10. Prevent public exposure of uploaded files; validate upload types and sizes and avoid showing raw exceptions or document contents in logs.

## Proposed ownership model change (database owner's responsibility)

```python
from django.conf import settings
from django.db import models

owner = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.PROTECT,
    related_name="processing_jobs",
)
```

Migration must be planned with the Processing Job Model owner. The current model has no `owner` field. Do not add this field or edit their migrations on the access-control branch without coordination.

## Proposed Django view usage (after ownership and authentication exist)

```python
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from processing_jobs.models import ProcessingJob

@login_required
def job_dashboard(request):
    jobs = ProcessingJob.objects.filter(owner=request.user)[:100]
    # Continue with your team's existing render(...) response.

@login_required
def download_extraction_json(request, job_id):
    job = get_object_or_404(
        ProcessingJob, pk=job_id, owner=request.user
    )
    # Only after the owner-scoped lookup, read the file/result.
    # Continue with your team's current response implementation.
```

### Important limitations

- **This PR does not provide login, token verification, protected Django views, or database migrations.**
- `actor_from_django_user` is safe only when called with Django's trusted `request.user`, not a user object created from an HTTP payload.
- `can_django_user_access_job` expects a database-backed `job.owner_id`; if absent, access is denied.
- Adapter tests use stubs and therefore do not replace Django client/database integration tests.
- Keep the PR in draft until the actual backend integration is implemented, tested, and approved.
