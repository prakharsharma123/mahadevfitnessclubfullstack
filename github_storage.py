"""
github_storage.py
------------------
Stores member photos inside a GitHub repository (free, permanent storage)
instead of the app server's disk (which is wiped on every Render redeploy).

Why GitHub for images?
- Completely free, no storage limits that matter for a gym's member photos.
- Survives redeploys/restarts (unlike Render's local filesystem).
- Served fast + free worldwide via the jsDelivr CDN, which mirrors any
  public GitHub repo automatically (https://www.jsdelivr.com/?docs=gh).

Required environment variables (set these on Render, see DEPLOYMENT_GUIDE.md):
- GITHUB_TOKEN   : a GitHub Personal Access Token with "repo" (contents) access
- GITHUB_REPO    : "your-username/your-image-repo"  (a small PUBLIC repo made just for photos)
- GITHUB_BRANCH  : branch to commit to, defaults to "main"
"""

import os
import base64
import uuid
import requests

GITHUB_API = "https://api.github.com"


def _config():
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")
    branch = os.environ.get("GITHUB_BRANCH", "main")
    return token, repo, branch


def is_configured():
    token, repo, _ = _config()
    return bool(token and repo)


def upload_photo(file_storage, member_id):
    """
    Uploads a Flask `file_storage` (from request.files['photo']) to the
    GitHub repo and returns (photo_url, github_path) for storage on the
    Member row. Returns (None, None) if not configured or on failure.
    """
    token, repo, branch = _config()
    if not (token and repo and file_storage and file_storage.filename):
        return None, None

    ext = os.path.splitext(file_storage.filename)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    path = f"members/{member_id}_{uuid.uuid4().hex[:8]}{ext}"

    content = base64.b64encode(file_storage.read()).decode("utf-8")
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {
        "message": f"Add photo for member {member_id}",
        "content": content,
        "branch": branch,
    }
    resp = requests.put(url, json=payload, headers=headers, timeout=20)
    if resp.status_code not in (200, 201):
        print(f"GitHub upload failed: {resp.status_code} {resp.text}")
        return None, None

    # jsDelivr CDN mirrors any public GitHub repo/branch for free, fast, cached delivery
    photo_url = f"https://cdn.jsdelivr.net/gh/{repo}@{branch}/{path}"
    return photo_url, path


def delete_photo(github_path):
    """Deletes a previously uploaded photo from the GitHub repo (best-effort)."""
    token, repo, branch = _config()
    if not (token and repo and github_path):
        return
    url = f"{GITHUB_API}/repos/{repo}/contents/{github_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    # Need the file's current sha to delete it
    get_resp = requests.get(url, headers=headers, params={"ref": branch}, timeout=20)
    if get_resp.status_code != 200:
        return
    sha = get_resp.json().get("sha")
    requests.delete(
        url,
        headers=headers,
        json={"message": f"Remove photo {github_path}", "sha": sha, "branch": branch},
        timeout=20,
    )


def fetch_photo(github_path):
    """Downloads one photo from the repo. Returns (bytes, content_type) or (None, None)."""
    token, repo, branch = _config()
    if not (token and repo and github_path):
        return None, None
    url = f"{GITHUB_API}/repos/{repo}/contents/{github_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.raw+json",
    }
    resp = requests.get(url, headers=headers, params={"ref": branch}, timeout=20)
    if resp.status_code != 200:
        print(f"GitHub fetch failed: {resp.status_code} {resp.text[:200]}")
        return None, None
    ext = os.path.splitext(github_path)[1].lower()
    ctype = {".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")
    return resp.content, ctype
