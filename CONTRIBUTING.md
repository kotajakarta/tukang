# Contributing to tuKang

Thank you for helping. tuKang is dual-licensed (GNU AGPL-3.0-only and a commercial license), so a few
rules apply that a single-license project would not need.

## 1. Sign the CLA first

Every contributor signs the [Contributor License Agreement](CLA.md) **before** their first pull request
is merged. You keep the copyright on your work; the CLA only lets the maintainer ship it under both
licenses. To sign, post the statement from the "Penandatanganan / Signing" section of `CLA.md` as a
comment on your pull request, using the same email as your commits.

If you write code as part of a job or for a client, your employer may own it: they must sign an Entity
CLA (ask in an issue) or give you written permission.

## 2. Third-party code and AI tools

- Only add dependencies or copied code under licenses that allow both AGPL and closed-source use
  (MIT, BSD, ISC, Apache-2.0, PSF, and similar). No GPL/AGPL-only, SSPL, or "non-commercial" code.
- After changing `backend/requirements.lock` or `frontend/package-lock.json`, regenerate the notices
  and commit the result:

  ```bash
  (cd frontend && npm ci)
  python3 scripts/third_party_notices.py
  ```

- Say in the pull request which parts were written with AI tools. You must have reviewed them.

## 3. Development

See the README for running tuKang locally. Before opening a pull request:

```bash
PYTHONPATH=backend python3 -m pytest backend/tests/
(cd frontend && npm run build)
```

## 4. Name and logo

The AGPL covers the code, not the "tuKang" name or the AiT logo. Forks must use a different name.
