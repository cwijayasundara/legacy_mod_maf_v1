"""
Azure DevOps Client

Handles all ADO interactions:
- Clone repository
- Create pull requests
- Update work item state
- Add work item comments

Uses the ADO REST API v7.1 with PAT authentication.
"""

import base64
import logging

import httpx

logger = logging.getLogger("ado-client")


class AdoClient:
    """Azure DevOps REST API client."""

    def __init__(self, org_url: str, project: str, repo: str, pat: str):
        self.org_url = org_url.rstrip("/")
        self.project = project
        self.repo = repo
        self.pat = pat
        self._auth_header = ""
        if pat:
            encoded = base64.b64encode(f":{pat}".encode()).decode()
            self._auth_header = f"Basic {encoded}"

    def is_configured(self) -> bool:
        """Check if ADO credentials are set."""
        return bool(self.org_url and self.project and self.repo and self.pat)

    def _headers(self) -> dict:
        return {
            "Authorization": self._auth_header,
            "Content-Type": "application/json",
        }

    def _api_base(self) -> str:
        return f"{self.org_url}/{self.project}/_apis"

    async def create_pull_request(
        self,
        source_branch: str,
        title: str,
        description: str,
        work_item_id: str,
        target_branch: str = "main",
    ) -> str | None:
        """
        Create a pull request in Azure DevOps.
        Returns the PR URL on success, None on failure.
        """
        if not self.is_configured():
            logger.warning("ADO not configured — skipping PR creation")
            return None

        # Ensure branch refs are fully qualified
        if not source_branch.startswith("refs/heads/"):
            source_branch = f"refs/heads/{source_branch}"
        if not target_branch.startswith("refs/heads/"):
            target_branch = f"refs/heads/{target_branch}"

        pr_body = {
            "sourceRefName": source_branch,
            "targetRefName": target_branch,
            "title": title,
            "description": description,
        }

        # Link work item if provided and numeric
        wi_num = work_item_id.replace("WI-", "").replace("LOCAL", "")
        if wi_num.isdigit():
            pr_body["workItemRefs"] = [{"id": wi_num}]

        url = f"{self._api_base()}/git/repositories/{self.repo}/pullrequests?api-version=7.1"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=pr_body, headers=self._headers())
                resp.raise_for_status()
                pr_data = resp.json()
                pr_url = pr_data.get("url", "")
                web_url = pr_data.get("repository", {}).get("webUrl", "")
                pr_id = pr_data.get("pullRequestId", "")
                if web_url and pr_id:
                    pr_url = f"{web_url}/pullrequest/{pr_id}"
                logger.info("PR created: %s", pr_url)
                return pr_url
        except httpx.HTTPStatusError as e:
            logger.error("ADO PR creation failed (%d): %s", e.response.status_code, e.response.text)
            return None
        except Exception as e:
            logger.error("ADO PR creation error: %s", e)
            return None

    async def update_work_item_state(self, work_item_id: str, state: str, comment: str = "") -> bool:
        """
        Update a work item's state in ADO.
        Used to set state to "Blocked" or "In Progress" based on migration result.
        """
        if not self.is_configured():
            return False

        wi_num = work_item_id.replace("WI-", "")
        if not wi_num.isdigit():
            logger.warning("Cannot update non-numeric work item ID: %s", work_item_id)
            return False

        url = f"{self._api_base()}/wit/workitems/{wi_num}?api-version=7.1"

        # PATCH body uses JSON Patch format
        patches = [
            {
                "op": "replace",
                "path": "/fields/System.State",
                "value": state,
            }
        ]

        if comment:
            patches.append({
                "op": "add",
                "path": "/fields/System.History",
                "value": comment,
            })

        headers = self._headers()
        headers["Content-Type"] = "application/json-patch+json"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.patch(url, json=patches, headers=headers)
                resp.raise_for_status()
                logger.info("Work item %s updated to state: %s", wi_num, state)
                return True
        except Exception as e:
            logger.error("Failed to update work item %s: %s", wi_num, e)
            return False

    async def add_work_item_comment(self, work_item_id: str, comment: str) -> bool:
        """Add a comment to a work item (for progress updates)."""
        if not self.is_configured():
            return False

        wi_num = work_item_id.replace("WI-", "")
        if not wi_num.isdigit():
            return False

        url = f"{self._api_base()}/wit/workitems/{wi_num}/comments?api-version=7.1-preview.4"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    url,
                    json={"text": comment},
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.error("Failed to add comment to work item %s: %s", wi_num, e)
            return False

    def get_clone_url(self) -> str:
        """Get the git clone URL for the repo (with embedded PAT for auth)."""
        if not self.is_configured():
            return ""
        # ADO clone URL with PAT embedded
        return f"{self.org_url}/{self.project}/_git/{self.repo}"
