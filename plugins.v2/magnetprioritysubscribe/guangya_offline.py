from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import requests


@dataclass
class GuangYaOfflineConfig:
    access_token: str
    refresh_token: str
    device_id: str
    client_id: str = "aMe-8VSlkrbQXpUR"
    timeout: int = 20


class GuangYaOfflineError(RuntimeError):
    pass


class GuangYaOfflineClient:
    ACCOUNT = "https://account.guangyapan.com"
    API = "https://api.guangyapan.com"

    def __init__(self, config: GuangYaOfflineConfig, session: Optional[requests.Session] = None):
        self.config = config
        self.session = session or requests.Session()

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.access_token.strip()}",
            "Did": self.config.device_id.strip(),
            "Dt": "4",
        }

    @staticmethod
    def _success(payload: dict) -> bool:
        msg = str(payload.get("msg") or "").strip().lower()
        return msg in ("", "success")

    def _refresh(self) -> None:
        response = self.session.post(
            f"{self.ACCOUNT}/v1/auth/token",
            json={
                "client_id": self.config.client_id,
                "grant_type": "refresh_token",
                "refresh_token": self.config.refresh_token.strip(),
            }, timeout=self.config.timeout,
        )
        data = response.json() if response.content else {}
        token = str(data.get("access_token") or "").strip()
        if response.status_code >= 400 or not token:
            raise GuangYaOfflineError(f"光鸭 Token 刷新失败: HTTP {response.status_code} {data}")
        self.config.access_token = token
        new_refresh = str(data.get("refresh_token") or "").strip()
        if new_refresh:
            self.config.refresh_token = new_refresh

    def _post(self, path: str, body: dict, retried: bool = False) -> dict:
        try:
            response = self.session.post(
                f"{self.API}{path}", headers=self._headers(), json=body,
                timeout=self.config.timeout,
            )
        except requests.RequestException as err:
            raise GuangYaOfflineError(f"光鸭请求失败: {err}") from err
        if response.status_code == 401 and not retried:
            self._refresh()
            return self._post(path, body, retried=True)
        try:
            payload = response.json() if response.content else {}
        except Exception as err:
            raise GuangYaOfflineError(f"光鸭返回非 JSON: HTTP {response.status_code}") from err
        if response.status_code >= 400 or not self._success(payload):
            raise GuangYaOfflineError(
                f"光鸭 API 失败: {path} HTTP {response.status_code} msg={payload.get('msg')}"
            )
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    def resolve_magnet(self, magnet: str) -> dict:
        return self._post("/cloudcollection/v1/resolve_res", {"url": magnet})

    def create_task(self, magnet: str, parent_id: str, new_name: str,
                    file_indexes: Optional[list[int]] = None) -> str:
        body = {"url": magnet, "parentId": parent_id, "newName": new_name}
        if file_indexes is not None:
            body["fileIndexes"] = list(file_indexes)
        data = self._post("/cloudcollection/v1/create_task", body)
        task_id = str(data.get("taskId") or "").strip()
        if not task_id:
            raise GuangYaOfflineError("光鸭创建离线任务失败: 响应缺少 taskId")
        return task_id

    def list_task(self, task_id: str) -> dict:
        data = self._post("/cloudcollection/v1/list_task", {"taskIds": [task_id]})
        items = data.get("list") or []
        if not isinstance(items, list):
            return {}
        for item in items:
            if str((item or {}).get("taskId") or "") == str(task_id):
                return item or {}
        return {}
